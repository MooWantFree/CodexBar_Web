import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from codex_token_report.config import Settings
from codex_token_report.main import create_app


def test_startup_pricing_waits_for_scan_without_blocking_pages(tmp_path):
    app = create_app(Settings(codex_home=tmp_path, data_dir=tmp_path / "data", scan_interval_minutes=0))
    scanned = threading.Event()
    fetching = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    scan = app.state.scanner.scan
    refresh = app.state.pricing.refresh_on_startup

    def initial_scan():
        result = scan()
        scanned.set()
        return result

    def fetch():
        assert scanned.is_set()
        fetching.set()
        if not release.wait(5):
            raise ValueError("Test did not release pricing fetch")
        return {"openai": {"models": {"gpt-5.6-sol": {"cost": {"input": 8, "cache_read": 0.8, "output": 40}}}}}

    def startup_refresh(timezone):
        try:
            return refresh(timezone)
        finally:
            finished.set()

    app.state.scanner.scan = initial_scan
    app.state.pricing._fetch_models_override = fetch
    app.state.pricing.refresh_on_startup = startup_refresh
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as executor:
        try:
            assert fetching.wait(2)
            assert client.get("/api/health").json()["pricing_refresh"]["state"] == "running"
            assert executor.submit(client.get, "/overview").result(timeout=2).status_code == 200
            assert executor.submit(client.get, "/api/pricing").result(timeout=2).json()["source"] == "bundled"
            response = executor.submit(client.put, "/api/pricing/models/gpt-5.6-sol/override",
                                       json={"input": 7, "cached_input": 0.7, "output": 35,
                                             "cache_write": None, "api_fast_multiplier": 3}).result(timeout=2)
            assert response.status_code == 200
        finally:
            release.set()
        assert finished.wait(2)
        model = app.state.pricing.catalog().models["gpt-5.6-sol"]
        assert model["api_usd"]["input"] == 7
        assert model["api_fast_multiplier"] == 3


def test_server_startup_does_not_wait_for_initial_scan(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    (codex_home / "sessions").mkdir(parents=True)
    app = create_app(
        Settings(codex_home=codex_home, data_dir=tmp_path / "data", scan_interval_minutes=0)
    )
    started = threading.Event()
    release = threading.Event()
    original_scan = app.state.scanner.scan

    def slow_scan():
        started.set()
        if not release.wait(2):
            raise RuntimeError("startup waited for the initial scan")
        return original_scan()

    app.state.scanner.scan = slow_scan

    with TestClient(app) as client:
        assert started.wait(1)
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["scan"]["state"] == "running"
        release.set()


def test_pricing_override_api_round_trip(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    (codex_home / "sessions").mkdir(parents=True)
    app = create_app(
        Settings(
            codex_home=codex_home,
            data_dir=tmp_path / "data",
            scan_interval_minutes=0,
        )
    )

    with TestClient(app) as client:
        invalid = client.put(
            "/api/pricing/models/gpt-5.6-sol/override",
            json={
                "input": -1,
                "cached_input": 0.4,
                "cache_write": None,
                "output": 20,
                "api_fast_multiplier": 2,
            },
        )
        assert invalid.status_code == 400

        response = client.put(
            "/api/pricing/models/gpt-5.6-sol/override",
            json={
                "input": 7,
                "cached_input": 0.7,
                "cache_write": None,
                "output": 35,
                "api_fast_multiplier": 3,
            },
        )
        assert response.status_code == 200
        state = client.get("/api/pricing").json()
        model = next(item for item in state["models"] if item["model"] == "gpt-5.6-sol")
        assert model["effective"]["input"] == 7.0
        assert model["override"]["api_fast_multiplier"] == "3"

        assert client.delete("/api/pricing/models/gpt-5.6-sol/override").status_code == 200
        restored = client.get("/api/pricing").json()
        model = next(item for item in restored["models"] if item["model"] == "gpt-5.6-sol")
        assert model["override"] is None
        assert model["effective"]["input"] == 4.0


def test_page_routes_and_project_api(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    (codex_home / "sessions").mkdir(parents=True)
    app = create_app(
        Settings(codex_home=codex_home, data_dir=tmp_path / "data", scan_interval_minutes=0)
    )
    app.state.database.replace_file_events(
        source_file="missing-rollout.jsonl",
        mtime_ns=1,
        size_bytes=1,
        parse_errors=0,
        scanned_at="2026-09-20T02:00:00+00:00",
        events=[
            {
                "event_id": "project-event",
                "source_file": "missing-rollout.jsonl",
                "source_kind": "token_usage_record",
                "timestamp_utc": "2026-09-20T01:00:00+00:00",
                "local_date": "2026-09-20",
                "model": "gpt-5.6-sol",
                "turn_id": "turn-1",
                "response_id": "response-1",
                "input_tokens": 100,
                "cached_input_tokens": 40,
                "cache_write_input_tokens": 0,
                "output_tokens": 10,
                "reasoning_output_tokens": 2,
                "total_tokens": 110,
                "service_tier": "standard",
                "tier_source": "logs_2_absence",
                "pricing_model": "gpt-5.6-sol",
                "project_key": "e:/code/example",
                "project_path": "E:\\Code\\example",
                "workspace_root": "E:\\Code\\example",
                "working_directory": "E:\\Code\\example",
            }
        ],
    )

    with TestClient(app) as client:
        for path in ("/", "/overview", "/pricing", "/daily", "/projects", "/resets"):
            response = client.get(path)
            assert response.status_code == 200
            assert "Codex Report" in response.text
            assert 'data-days="1">今天' in response.text

        projects = client.get("/api/projects?start=2026-09-20&end=2026-09-20")
        assert projects.status_code == 200
        assert projects.json()["projects"][0]["total_tokens"] == 110

        daily = client.get(
            "/api/projects/daily",
            params={"project": "e:/code/example", "start": "2026-09-20"},
        )
        assert daily.status_code == 200
        assert daily.json()["project"]["display_name"] == "example"
        assert client.get("/api/projects/daily", params={"project": "missing"}).status_code == 404
