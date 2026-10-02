import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from codex_token_report.config import Settings
from codex_token_report.main import create_app
from codex_token_report.quota import QuotaService

WEEK = 7 * 24 * 60 * 60


def reading(key, reset=None, used=0):
    return {
        "status": "ready", "plan_type": "pro", "_account_key": key,
        "windows": [] if reset is None else [{
            "limit_id": "codex", "limit_name": "Codex", "slot": "primary",
            "used_percent": used, "remaining_percent": 100 - used,
            "window_minutes": 10080, "resets_at": reset,
        }],
    }


def sampling_app(tmp_path, monkeypatch, interval=0.02):
    monkeypatch.setattr("codex_token_report.main.QUOTA_SAMPLE_INTERVAL_SECONDS", interval)
    home = tmp_path / "codex"
    (home / "sessions").mkdir(parents=True)
    return create_app(Settings(
        codex_home=home, data_dir=tmp_path / "data", scan_interval_minutes=0,
    ))


def test_sampling_confirms_an_early_reset_without_browser_requests(tmp_path, monkeypatch):
    app = sampling_app(tmp_path, monkeypatch)
    service = app.state.quota
    # Periodic reads must collect fresh evidence even if the cache is still valid.
    service.cache_seconds = 3600
    reset = datetime.fromisoformat("2026-10-02T21:14:00+00:00").timestamp()
    times = [reset - 300, reset + 10, reset + 75]
    state = {"now": times[0], "calls": 0}
    confirmed = threading.Event()

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromtimestamp(state["now"], tz or UTC)

    def fetch():
        index = min(state["calls"], 2)
        state["calls"] += 1
        state["now"] = times[index]
        return reading("account", reset + (2 * 86400 if index == 0 else WEEK),
                       used=98 if index == 0 else 0)

    observe = service.history.observe

    def observed(*args, **kwargs):
        events = observe(*args, **kwargs)
        if events:
            confirmed.set()
        return events

    monkeypatch.setattr("codex_token_report.quota.datetime", Clock)
    monkeypatch.setattr(service, "_fetch", fetch)
    monkeypatch.setattr(service.history, "observe", observed)
    with TestClient(app):
        assert confirmed.wait(3)
        records = service.history.records("account", state["now"], confirmed_only=True)
        assert len(records) == 1
        assert records[0]["method"] == "early"
        assert records[0]["reset_at"] == "2026-10-02T21:14:00+00:00"
        assert records[0]["date"] == "2026-10-03"
        assert state["calls"] >= 3


def test_sampling_retries_after_unexpected_read_failure(tmp_path, monkeypatch, caplog):
    app = sampling_app(tmp_path, monkeypatch)
    recovered = threading.Event()
    calls = 0

    def fetch():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("fixture sampling failure")
        return reading("account")

    read = app.state.quota.read

    def observed_read(**kwargs):
        result = read(**kwargs)
        if result["status"] == "ready":
            recovered.set()
        return result

    monkeypatch.setattr(app.state.quota, "_fetch", fetch)
    monkeypatch.setattr(app.state.quota, "read", observed_read)
    with TestClient(app):
        assert recovered.wait(3)
        assert calls >= 2
        assert app.state.quota.cached["status"] == "ready"
    assert "Automatic quota sampling failed" in caplog.text


def test_directory_switch_waits_for_sampler_and_following_samples_use_new_home(
    tmp_path, monkeypatch,
):
    app = sampling_app(tmp_path, monkeypatch)
    original = app.state.settings.codex_home
    selected = tmp_path / "selected"
    (selected / "sessions").mkdir(parents=True)
    started, release, switched_read, validated = (threading.Event() for _ in range(4))
    homes = []
    from codex_token_report import main

    validate = main.validate_codex_home

    def observed_validate(path):
        result = validate(path)
        validated.set()
        return result

    def fetch(service):
        homes.append(service.codex_home)
        if service.codex_home == original:
            started.set()
            assert release.wait(5)
        else:
            switched_read.set()
        return reading(str(service.codex_home))

    monkeypatch.setattr(main, "validate_codex_home", observed_validate)
    monkeypatch.setattr(QuotaService, "_fetch", fetch)
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as executor:
        try:
            assert started.wait(2)
            switching = executor.submit(client.put, "/api/settings", json={"codex_home": str(selected)})
            assert validated.wait(2)
            assert not switching.done()
            assert app.state.quota.codex_home == original
        finally:
            release.set()
        assert switching.result(timeout=3).status_code == 200
        assert switched_read.wait(3)
        assert homes[0] == original
        assert all(home == selected.resolve() for home in homes[1:])


def test_shutdown_waits_for_sampler_worker_and_stops_future_samples(tmp_path, monkeypatch):
    app = sampling_app(tmp_path, monkeypatch)
    started, release = threading.Event(), threading.Event()
    calls = 0

    def fetch():
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(5)
        return reading("account")

    monkeypatch.setattr(app.state.quota, "_fetch", fetch)

    async def exercise():
        lifespan = app.router.lifespan_context(app)
        await lifespan.__aenter__()
        try:
            assert await asyncio.to_thread(started.wait, 2)
            closing = asyncio.create_task(lifespan.__aexit__(None, None, None))
            await asyncio.sleep(0.02)
            assert not closing.done()
        finally:
            release.set()
        await asyncio.wait_for(closing, timeout=3)
        count = calls
        await asyncio.sleep(0.06)
        assert calls == count == 1
        assert app.state.quota.cached["status"] == "ready"

    asyncio.run(exercise())
