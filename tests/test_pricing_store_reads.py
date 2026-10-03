import json

import pytest

from codex_token_report.db import Database
from codex_token_report.models_dev import CATALOG_CACHE_KEY
from codex_token_report.pricing import PriceCatalog
from codex_token_report.pricing_store import PricingStore


def _insert_event(database, model="gpt-5.4"):
    with database.connect() as connection:
        connection.execute(
            """INSERT INTO usage_events
            (event_id, source_file, source_kind, timestamp_utc, local_date, model,
             input_tokens, cached_input_tokens, cache_write_input_tokens, output_tokens,
             reasoning_output_tokens, total_tokens)
            VALUES ('request', 'fixture', 'token_usage_record',
                    '2026-10-01T00:00:00+00:00', '2026-10-01', ?, 10, 0, 0, 1, 0, 11)""",
            (model,),
        )


def test_catalog_reads_bundled_prices_once_and_keeps_fallbacks_isolated(tmp_path, monkeypatch):
    database = Database(tmp_path / "usage.sqlite3")
    store = PricingStore(database=database)
    _insert_event(database, "openai/gpt-5.6-fast")
    saved = store.catalog().payload
    saved["models"]["gpt-5.4"].update(price_source="models_dev")
    saved["models"]["gpt-5.4"]["api_usd"]["cache_write"] = 99
    database.save_pricing_catalog(
        payload_json=json.dumps(saved), source="models_dev", fetched_at="2026-10-01",
        refresh_attempted_at="2026-10-01", refresh_error=None,
    )
    remote = {"openai": {"models": {
        "gpt-5.4": {"cost": {"input": 2.5, "output": 15}},
        "gpt-5.6-sol": {"cost": {"input": 8, "output": 40}},
    }}}
    database.set_metadata(CATALOG_CACHE_KEY, json.dumps({
        "fetched_at": "2026-10-01T00:00:00+00:00", "catalog": remote,
    }))
    calls = []
    original = PriceCatalog.load_default

    def load_default():
        calls.append(True)
        return original()

    monkeypatch.setattr(PriceCatalog, "load_default", load_default)
    catalog = store.catalog()
    assert len(calls) == 1
    assert catalog.models["gpt-5.4"]["api_usd"]["cache_write"] == 3.125
    assert catalog.models["gpt-5.4"]["api_usd"]["cached_input"] == 0.25
    assert catalog.models["gpt-5.6-sol"]["api_usd"]["input"] == 8

    catalog.models["gpt-5.4"]["api_usd"]["cache_write"] = 123
    assert store.catalog().models["gpt-5.4"]["api_usd"]["cache_write"] == 3.125
    assert len(calls) == 2


@pytest.mark.parametrize("mode", ["snapshot", "current"])
def test_prepare_events_builds_one_catalog_without_adding_snapshot_metadata(
    tmp_path, monkeypatch, mode,
):
    database = Database(tmp_path / "usage.sqlite3")
    store = PricingStore(database=database)
    _insert_event(database)
    catalogs = []
    original = store.catalog

    def catalog():
        current = original()
        catalogs.append(current)
        return current

    monkeypatch.setattr(store, "catalog", catalog)
    events = store.prepare_events(database.fetch_events(), mode)
    assert len(catalogs) == 1
    assert "snapshot_source" not in catalogs[0].payload
    assert "snapshot_overrides" not in catalogs[0].payload
    assert events[0]["price_snapshot"]["source"] == "bundled"
    assert ("_price_catalog" in events[0]) == (mode == "snapshot")
