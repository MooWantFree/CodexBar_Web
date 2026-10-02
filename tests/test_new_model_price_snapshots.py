import copy
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from codex_token_report.db import Database
from codex_token_report.pricing_store import PricingStore
from codex_token_report.reports import build_report

FUTURE_MODEL = "gpt-future-snapshot"
START = datetime(2026, 10, 1, tzinfo=UTC)


def remote_catalog(model=None, *, input_price=3, output_price=9, provider="openai"):
    catalog = {"openai": {"models": {
        "gpt-6.1-sol": {"cost": {"input": 2, "cache_read": 0.2, "output": 10}},
    }}}
    if model:
        catalog.setdefault(provider, {"models": {}})["models"][model] = {
            "cost": {"input": input_price, "cache_read": input_price / 10,
                     "output": output_price},
        }
    return catalog


@pytest.fixture
def pricing_case(tmp_path, monkeypatch):
    clock = {"now": START}

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"].astimezone(tz or UTC)

    monkeypatch.setattr("codex_token_report.pricing_store.datetime", Clock)
    database = Database(tmp_path / "usage.sqlite3")
    remote = {"catalog": remote_catalog()}
    store = PricingStore(database=database, fetch_models=lambda: copy.deepcopy(remote["catalog"]))
    store.refresh(now=clock["now"])
    return database, store, remote, clock


def insert_event(database, *, model=FUTURE_MODEL, tier="standard", event_id="request"):
    with database.connect() as connection:
        connection.execute(
            """INSERT INTO usage_events
            (event_id, source_file, source_kind, timestamp_utc, local_date, model,
             input_tokens, cached_input_tokens, cache_write_input_tokens, output_tokens,
             reasoning_output_tokens, total_tokens, service_tier)
            VALUES (?, 'fixture', 'token_usage_record', ?, '2026-10-01', ?,
                    100, 0, 0, 10, 0, 110, ?)""",
            (event_id, (START + timedelta(minutes=1)).isoformat(), model, tier),
        )


def prepare(database, store, *, mode="snapshot"):
    return store.prepare_events(database.fetch_events(), mode)


def total(store, events):
    return build_report(events, store.catalog(), start=None, end=None)["total"]


def pinned_data(database):
    snapshots, revisions = database.price_snapshot_data(["request"])
    return copy.deepcopy(snapshots), copy.deepcopy(revisions)


def test_unknown_snapshot_uses_first_available_model_price_and_survives_later_repricing(pricing_case):
    database, store, remote, clock = pricing_case
    insert_event(database)
    clock["now"] = START + timedelta(minutes=2)
    unknown = prepare(database, store)
    assert total(store, unknown)["unknown_price_calls"] == 1
    assert unknown[0]["price_snapshot"]["inferred"] is False
    original = pinned_data(database)

    clock["now"] = START + timedelta(days=1)
    remote["catalog"] = remote_catalog(FUTURE_MODEL)
    assert FUTURE_MODEL in store.refresh(now=clock["now"])["updated_models"]
    first = database.first_model_price_revision(FUTURE_MODEL)
    backfilled = prepare(database, store)
    metadata = backfilled[0]["price_snapshot"]
    assert metadata["revision_id"] == unknown[0]["price_snapshot"]["revision_id"]
    assert metadata["backfilled_revision_id"] == first["id"]
    assert metadata["inferred"] is True
    assert metadata["price_date"] == "2026-10-02"
    assert metadata["observed_at"] == first["observed_at"]
    assert metadata["source"] == "models_dev"
    first_total = total(store, backfilled)
    assert first_total["api_usd_known"] == pytest.approx(0.00039)
    assert first_total["unknown_price_calls"] == 0
    assert first_total["inferred_price_calls"] == 1
    assert pinned_data(database) == original

    clock["now"] = START + timedelta(days=2)
    remote["catalog"] = remote_catalog(FUTURE_MODEL, input_price=9, output_price=27)
    store.refresh(now=clock["now"])
    current = prepare(database, store, mode="current")
    snapshot = prepare(database, store)
    assert total(store, current)["api_usd_known"] == pytest.approx(0.00117)
    assert total(store, snapshot)["api_usd_known"] == pytest.approx(0.00039)
    assert snapshot[0]["price_snapshot"] == metadata
    assert database.first_model_price_revision(FUTURE_MODEL)["id"] == first["id"]
    assert pinned_data(database) == original


def test_snapshot_with_original_model_price_is_not_backfilled(pricing_case):
    database, store, remote, clock = pricing_case
    model = "gpt-6.1-sol"
    remote["catalog"] = remote_catalog(model)
    store.refresh(now=clock["now"])
    insert_event(database, model=model)
    clock["now"] = START + timedelta(minutes=2)
    before = prepare(database, store)
    metadata = copy.deepcopy(before[0]["price_snapshot"])
    original = pinned_data(database)

    clock["now"] = START + timedelta(days=1)
    remote["catalog"] = remote_catalog(model, input_price=9, output_price=27)
    store.refresh(now=clock["now"])
    after = prepare(database, store)

    assert total(store, after)["api_usd_known"] == pytest.approx(0.00039)
    assert total(store, prepare(database, store, mode="current"))["api_usd_known"] == pytest.approx(0.00117)
    assert after[0]["price_snapshot"] == metadata
    assert "backfilled_revision_id" not in metadata
    assert metadata["inferred"] is False
    assert pinned_data(database) == original


@pytest.mark.parametrize("provider", [None, "other"])
def test_snapshot_stays_unknown_without_openai_model_price(pricing_case, provider):
    database, store, remote, clock = pricing_case
    insert_event(database)
    clock["now"] = START + timedelta(minutes=2)
    before = prepare(database, store)
    original = pinned_data(database)

    clock["now"] = START + timedelta(days=1)
    remote["catalog"] = remote_catalog(FUTURE_MODEL, provider=provider) if provider else remote_catalog()
    store.refresh(now=clock["now"])
    after = prepare(database, store)

    assert database.first_model_price_revision(FUTURE_MODEL) is None
    assert total(store, after)["api_usd_known"] == 0
    assert total(store, after)["unknown_price_calls"] == 1
    assert after[0]["price_snapshot"] == before[0]["price_snapshot"]
    assert pinned_data(database) == original


def test_provider_qualified_event_does_not_borrow_openai_first_known_price(pricing_case):
    database, store, remote, clock = pricing_case
    insert_event(database, model=f"other/{FUTURE_MODEL}")
    clock["now"] = START + timedelta(minutes=2)
    before = prepare(database, store)
    # An independent OpenAI event makes the same bare ID a known local price.
    insert_event(database, event_id="openai-request")
    clock["now"] = START + timedelta(days=1)
    remote["catalog"] = remote_catalog(FUTURE_MODEL)
    store.refresh(now=clock["now"])
    after = next(event for event in prepare(database, store) if event["event_id"] == "request")

    assert database.first_model_price_revision(FUTURE_MODEL) is not None
    assert total(store, [after])["unknown_price_calls"] == 1
    assert total(store, [after])["api_usd_known"] == 0
    assert after["price_snapshot"] == before[0]["price_snapshot"]


def test_first_known_manual_unknown_fast_override_is_preserved_after_official_price_arrives(pricing_case):
    database, store, remote, clock = pricing_case
    model = "gpt-6-sol"
    insert_event(database, model=model, tier="priority")
    clock["now"] = START + timedelta(minutes=2)
    assert total(store, prepare(database, store))["unknown_price_calls"] == 1
    original = pinned_data(database)

    clock["now"] = START + timedelta(days=1)
    store.set_override(model, {
        "input": Decimal(3), "cached_input": Decimal("0.3"), "cache_write": None,
        "output": Decimal(9), "api_fast_multiplier": None,
    })
    first = database.first_model_price_revision(model)
    manual = prepare(database, store)
    catalog = manual[0]["_price_catalog"]
    assert manual[0]["price_snapshot"]["source"] == "override"
    assert manual[0]["price_snapshot"]["backfilled_revision_id"] == first["id"]
    assert catalog.models[model]["api_fast_multiplier"] is None
    assert catalog.can_estimate_fast_from_standard(model) is False
    assert total(store, manual)["api_usd_known"] == 0
    assert total(store, manual)["standard_api_usd_known"] == pytest.approx(0.00039)
    assert total(store, manual)["unknown_fast_price_calls"] == 1

    clock["now"] = START + timedelta(days=2)
    remote["catalog"] = remote_catalog(model, input_price=9, output_price=27)
    store.refresh(now=clock["now"])
    assert store.delete_override(model) is True
    assert store.catalog().models[model]["api_fast_multiplier"] == 2
    snapshot = prepare(database, store)
    assert snapshot[0]["price_snapshot"] == manual[0]["price_snapshot"]
    assert snapshot[0]["_price_catalog"].models[model]["api_fast_multiplier"] is None
    assert total(store, snapshot)["api_usd_known"] == 0
    assert total(store, snapshot)["fast_standard_fallback_calls"] == 0
    assert total(store, prepare(database, store, mode="current"))["api_usd_known"] == pytest.approx(0.00234)
    assert pinned_data(database) == original


def test_first_model_revision_skips_incomplete_rates_and_accepts_zero(pricing_case):
    database, store, _, clock = pricing_case
    partial = copy.deepcopy(store.catalog().payload)
    partial["models"][FUTURE_MODEL] = {"api_usd": {"input": 3, "output": None}}
    database.record_price_revision(partial, clock["now"].isoformat())
    assert database.first_model_price_revision(FUTURE_MODEL) is None
    complete = copy.deepcopy(partial)
    complete["models"][FUTURE_MODEL]["api_usd"] = {"input": 0, "output": 0}
    clock["now"] += timedelta(minutes=1)
    database.record_price_revision(complete, clock["now"].isoformat())

    first = database.first_model_price_revision(FUTURE_MODEL)
    assert json.loads(first["payload_json"])["models"][FUTURE_MODEL]["api_usd"] == {"input": 0, "output": 0}
    assert first["observed_at"] == clock["now"].isoformat()
