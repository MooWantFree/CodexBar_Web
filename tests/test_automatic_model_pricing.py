import asyncio
import copy
import json
import threading
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from codex_token_report.config import Settings
from codex_token_report.main import create_app
from codex_token_report.models_dev import CATALOG_CACHE_KEY

FUTURE_MODEL = "gpt-future-exact"


def remote_catalog(*, future=False, other_provider=False):
    catalog = {"openai": {"models": {
        "gpt-6.1-sol": {"cost": {"input": 2, "cache_read": 0.2, "output": 10}},
    }}}
    row = {"name": "Future OpenAI model", "cost": {
        "input": 3, "cache_read": 0.3, "cache_write": 3.5, "output": 9,
    }}
    if future:
        catalog["openai"]["models"][FUTURE_MODEL] = row
    if other_provider:
        catalog["other"] = {"models": {FUTURE_MODEL: {"cost": {
            "input": 999, "output": 999,
        }}}}
    return catalog


def write_rollout(home, model=FUTURE_MODEL):
    records = [
        {"timestamp": "2026-10-01T01:00:00Z", "type": "session_meta",
         "payload": {"id": "future-session", "cwd": str(home)}},
        {"timestamp": "2026-10-01T01:00:01Z", "type": "turn_context",
         "payload": {"model": model, "turn_id": "future-turn", "cwd": str(home)}},
        {"timestamp": "2026-10-01T01:00:02Z", "type": "token_usage_record",
         "payload": {"turn_id": "future-turn", "response_id": "future-response",
                     "usage": {"input_tokens": 100, "cached_input_tokens": 0,
                               "output_tokens": 10, "total_tokens": 110}}},
    ]
    (home / "sessions" / "future.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records), encoding="utf-8",
    )


@pytest.fixture
def pricing_app(tmp_path):
    home = tmp_path / "codex"
    (home / "sessions").mkdir(parents=True)
    return create_app(Settings(
        codex_home=home, data_dir=tmp_path / "data", scan_interval_minutes=0,
    ))


def bootstrap_cache(app, *, now=None, catalog=None):
    store = app.state.pricing
    remote = {"catalog": catalog or remote_catalog(), "calls": []}

    def fetch():
        remote["calls"].append(tuple(app.state.database.distinct_models()))
        return copy.deepcopy(remote["catalog"])

    store._fetch_models_override = fetch
    store.refresh(now=now or datetime.now(UTC) - timedelta(minutes=16))
    return remote


def model_state(client):
    return next(row for row in client.get("/api/pricing").json()["models"]
                if row["model"] == FUTURE_MODEL)


def test_manual_scan_fetches_new_exact_openai_model_before_returning(pricing_app):
    remote = bootstrap_cache(pricing_app)
    remote["catalog"] = remote_catalog(future=True, other_provider=True)
    write_rollout(pricing_app.state.settings.codex_home)
    client = TestClient(pricing_app)

    result = client.post("/api/scan")

    assert result.status_code == 200
    assert result.json()["stored_events"] == 1
    assert len(remote["calls"]) == 2
    assert FUTURE_MODEL in remote["calls"][-1]
    price = model_state(client)
    assert price["effective"]["input"] == 3
    assert price["effective"]["output"] == 9
    assert price["effective"]["api_fast_multiplier"] is None
    total = client.get("/api/summary?price_mode=current").json()["total"]
    assert total["unknown_price_calls"] == 0
    assert total["api_usd_known"] == pytest.approx(0.00039)


def test_scan_reuses_complete_cache_for_previously_unused_openai_model(pricing_app):
    remote = bootstrap_cache(pricing_app, catalog=remote_catalog(future=True))
    write_rollout(pricing_app.state.settings.codex_home)
    client = TestClient(pricing_app)

    assert client.post("/api/scan").status_code == 200
    assert len(remote["calls"]) == 1
    assert model_state(client)["effective"]["input"] == 3


def test_scan_never_borrows_the_same_model_from_another_provider(pricing_app):
    remote = bootstrap_cache(pricing_app)
    remote["catalog"] = remote_catalog(other_provider=True)
    write_rollout(pricing_app.state.settings.codex_home)
    client = TestClient(pricing_app)

    assert client.post("/api/scan").status_code == 200
    assert len(remote["calls"]) == 2
    assert model_state(client)["effective"] is None
    cache = json.loads(pricing_app.state.database.get_metadata(CATALOG_CACHE_KEY))
    assert FUTURE_MODEL not in cache["catalog"]["openai"]["models"]
    total = client.get("/api/summary?price_mode=current").json()["total"]
    assert total["unknown_price_calls"] == 1
    assert total["api_usd_known"] == 0


def test_scan_respects_refresh_cooldown_and_retries_after_it(pricing_app, monkeypatch):
    start = datetime(2026, 10, 1, tzinfo=UTC)
    clock = {"now": start + timedelta(minutes=14)}

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"].astimezone(tz or UTC)

    monkeypatch.setattr("codex_token_report.pricing_store.datetime", Clock)
    remote = bootstrap_cache(pricing_app, now=start)
    remote["catalog"] = remote_catalog(future=True)
    write_rollout(pricing_app.state.settings.codex_home)
    client = TestClient(pricing_app)

    assert client.post("/api/scan").status_code == 200
    assert len(remote["calls"]) == 1
    assert model_state(client)["effective"] is None
    clock["now"] = start + timedelta(minutes=16)
    assert client.post("/api/scan").status_code == 200
    assert len(remote["calls"]) == 2
    assert model_state(client)["effective"]["input"] == 3


def test_directory_save_then_scan_prices_models_from_selected_home(pricing_app, tmp_path):
    remote = bootstrap_cache(pricing_app)
    remote["catalog"] = remote_catalog(future=True)
    selected = tmp_path / "selected-codex"
    (selected / "sessions").mkdir(parents=True)
    write_rollout(selected)
    client = TestClient(pricing_app)

    assert client.put("/api/settings", json={"codex_home": str(selected)}).status_code == 200
    assert len(remote["calls"]) == 1
    assert client.post("/api/scan").status_code == 200
    assert len(remote["calls"]) == 2
    assert model_state(client)["effective"]["input"] == 3


def test_periodic_price_checks_retry_without_scanning_or_browser_requests(
    pricing_app, monkeypatch,
):
    monkeypatch.setattr("codex_token_report.main.PRICING_CHECK_INTERVAL_SECONDS", 0.02)
    start = datetime(2026, 10, 1, tzinfo=UTC)
    clock = {"now": start + timedelta(minutes=14)}

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"].astimezone(tz or UTC)

    monkeypatch.setattr("codex_token_report.pricing_store.datetime", Clock)
    remote = bootstrap_cache(pricing_app, now=start)
    remote["catalog"] = remote_catalog(future=True)
    write_rollout(pricing_app.state.settings.codex_home)
    first_check, priced = threading.Event(), threading.Event()
    store = pricing_app.state.pricing
    check = store.refresh_on_startup
    scan = pricing_app.state.scanner.scan
    scan_count = 0

    def observed_check(timezone):
        result = check(timezone)
        first_check.set()
        if result and FUTURE_MODEL in result["updated_models"]:
            priced.set()
        return result

    def observed_scan():
        nonlocal scan_count
        scan_count += 1
        return scan()

    monkeypatch.setattr(store, "refresh_on_startup", observed_check)
    monkeypatch.setattr(pricing_app.state.scanner, "scan", observed_scan)
    with TestClient(pricing_app):
        assert first_check.wait(2)
        assert len(remote["calls"]) == 1
        clock["now"] = start + timedelta(minutes=16)
        assert priced.wait(3)
        assert store.catalog().models[FUTURE_MODEL]["api_usd"]["input"] == 3
        assert scan_count == 1


def test_manual_refresh_waits_for_inflight_automatic_fetch(pricing_app):
    started, release = threading.Event(), threading.Event()
    calls = 0

    def fetch():
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            assert release.wait(5)
        return remote_catalog()

    pricing_app.state.pricing._fetch_models_override = fetch

    async def exercise():
        async with pricing_app.router.lifespan_context(pricing_app):
            assert await asyncio.to_thread(started.wait, 2)
            async with AsyncClient(transport=ASGITransport(pricing_app), base_url="http://test") as client:
                forced = asyncio.create_task(client.post("/api/pricing/refresh"))
                try:
                    await asyncio.sleep(0.02)
                    assert calls == 1
                    assert not forced.done()
                finally:
                    release.set()
                assert (await asyncio.wait_for(forced, timeout=3)).status_code == 200
                assert calls == 2

    asyncio.run(exercise())


def test_shutdown_finishes_inflight_price_worker_and_stops_periodic_checks(
    pricing_app, monkeypatch,
):
    monkeypatch.setattr("codex_token_report.main.PRICING_CHECK_INTERVAL_SECONDS", 0.02)
    started, release = threading.Event(), threading.Event()
    calls = 0

    def fetch():
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(5)
        return remote_catalog()

    pricing_app.state.pricing._fetch_models_override = fetch

    async def exercise():
        lifespan = pricing_app.router.lifespan_context(pricing_app)
        await lifespan.__aenter__()
        try:
            assert await asyncio.to_thread(started.wait, 2)
            closing = asyncio.create_task(lifespan.__aexit__(None, None, None))
            await asyncio.sleep(0.02)
            assert not closing.done()
        finally:
            release.set()
        await asyncio.wait_for(closing, timeout=3)
        await asyncio.sleep(0.06)
        assert calls == 1

    asyncio.run(exercise())
