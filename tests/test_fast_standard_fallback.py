import copy
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from codex_token_report.db import Database
from codex_token_report.pricing import PriceCatalog
from codex_token_report.pricing_store import PricingStore
from codex_token_report.quota_value import build_quota_value_report
from codex_token_report.reports import (
    build_project_daily_report,
    build_projects_report,
    build_report,
    build_sessions_report,
    request_rows,
)

MODEL = "gpt-7-future"


def _catalog(*, model=MODEL, source="models_dev", manual_snapshot=False):
    return PriceCatalog({
        "as_of": "2026-10-01", "currency": "USD", "basis_tokens": 1_000_000,
        "fast_pricing_version": 3, "snapshot_source": source,
        "snapshot_overrides": [model] if manual_snapshot else [],
        "context": {
            "long_context_threshold": 272000, "long_input_multiplier": 2,
            "long_cached_input_multiplier": 2, "long_cache_write_multiplier": 2,
            "long_output_multiplier": 1.5,
        },
        "models": {model: {
            "display_name": "Future OpenAI model", "price_source": source,
            "api_usd": {"input": 2, "cached_input": 0.2, "cache_write": 2.5, "output": 10},
            "api_usd_long_context": {
                "input": 4, "cached_input": 0.4, "cache_write": 5, "output": 15,
            },
            "context_threshold": 272000, "api_fast_multiplier": None,
            "codex_credits": None, "credit_fast_multiplier": None,
        }},
    })


def _event(key="fast", *, long_context=False, **changes):
    result = {
        "event_id": key, "session_id": "child", "source_file": "fixture.jsonl",
        "timestamp_utc": "2026-10-01T01:00:00+00:00", "local_date": "2026-10-01",
        "model": MODEL, "pricing_model": None, "service_tier": "priority",
        "project_key": "fixture-project", "project_path": "E:/Code/fixture",
        "input_tokens": 300000 if long_context else 1000,
        "cached_input_tokens": 10000 if long_context else 100,
        "cache_write_input_tokens": 5000 if long_context else 50,
        "output_tokens": 1000 if long_context else 20, "reasoning_output_tokens": 0,
    }
    result.update(changes)
    return result


@pytest.mark.parametrize("long_context,standard", [(False, 0.002045), (True, 1.184)])
def test_unknown_openai_fast_displays_standard_without_claiming_confirmed_price(long_context, standard):
    catalog = _catalog()
    event = _event(long_context=long_context)
    original = copy.deepcopy(event)

    total = build_report([event], catalog, start=None, end=None)["total"]

    assert total["api_usd_known"] == pytest.approx(standard)
    assert total["standard_api_usd_known"] == pytest.approx(standard)
    assert total["fast_standard_fallback_usd"] == pytest.approx(standard)
    assert total["fast_standard_fallback_calls"] == total["priced_calls"] == 1
    assert total["unknown_fast_price_calls"] == total["unknown_price_calls"] == 1
    assert total["price_coverage_percent"] == 0
    assert total["unpriced_tokens"] == event["input_tokens"] + event["output_tokens"]
    assert total["fast_surcharge_usd"] == 0
    assert total["credit_priced_calls"] == 0
    assert event == original
    price = catalog.calculate(
        model=MODEL, input_tokens=event["input_tokens"],
        cached_input_tokens=event["cached_input_tokens"],
        cache_write_input_tokens=event["cache_write_input_tokens"],
        output_tokens=event["output_tokens"], service_tier="priority",
    )
    assert price.api_usd is None
    assert price.api_tier_multiplier is None


def test_all_usage_buckets_share_fallback_and_unknown_price_metadata():
    catalog = _catalog()
    events = [_event()]
    report = build_report(events, catalog, start=None, end=None)
    projects = build_projects_report(events, catalog, start=None, end=None)
    project_daily = build_project_daily_report(
        events, catalog, project_key="fixture-project", project_path="E:/Code/fixture",
        start=None, end=None,
    )
    sessions = build_sessions_report(events, catalog, {}, {"child": {"parent_session_id": "root"}})
    buckets = [
        report["total"], report["daily"][0], report["models"][0],
        report["daily"][0]["models"][0], report["hourly"][0],
        report["hourly"][0]["models"][0], projects["projects"][0],
        projects["projects"][0]["models"][0], project_daily["total"],
        sessions[0], sessions[0]["members"][1],
    ]
    for bucket in buckets:
        assert bucket["api_usd_known"] == pytest.approx(0.002045)
        assert bucket["fast_standard_fallback_calls"] == 1
        assert bucket["fast_standard_fallback_usd"] == pytest.approx(0.002045)
        assert bucket["unknown_price_calls"] == bucket["unknown_fast_price_calls"] == 1
        assert bucket["price_coverage_percent"] == 0
    assert sessions[0]["members"][0]["fast_standard_fallback_calls"] == 0


def test_mixed_prices_keep_true_unknown_counts_and_coverage():
    report = build_report([
        _event("standard", service_tier="standard"), _event("fast"),
        _event("unknown", model="not-priced"),
    ], _catalog(), start=None, end=None)
    total = report["total"]
    assert total["calls"] == 3
    assert total["priced_calls"] == 2
    assert total["unknown_price_calls"] == total["unknown_fast_price_calls"] == 2
    assert total["price_coverage_percent"] == 33.33
    assert total["api_usd_known"] == pytest.approx(0.002045 * 2)
    assert total["fast_standard_fallback_calls"] == 1
    assert total["fast_standard_fallback_usd"] == pytest.approx(0.002045)
    assert set(report["unknown_models"]) == {MODEL, "not-priced"}


def test_request_fallback_amount_is_displayable_and_marked_unknown():
    row = request_rows([_event()], _catalog())[0]
    assert row["api_standard_fallback"] is True
    assert row["api_cost_unknown"] is True
    assert row["api_usd_known"] == pytest.approx(0.002045)
    assert row["priced_calls"] == 1
    assert row["unknown_price_calls"] == 1


def test_zero_standard_fallback_is_known_base_amount_not_missing_price():
    catalog = _catalog()
    catalog.models[MODEL]["api_usd"] = dict.fromkeys(catalog.models[MODEL]["api_usd"], 0)
    row = request_rows([_event()], catalog)[0]
    assert row["api_usd_known"] == row["fast_standard_fallback_usd"] == 0
    assert row["api_standard_fallback"] is True
    assert row["priced_calls"] == 1
    assert row["api_cost_unknown"] is True


@pytest.mark.parametrize("service_tier", ["standard", "unknown"])
def test_existing_standard_and_unknown_tier_estimates_are_not_fast_fallback(service_tier):
    row = request_rows([_event(service_tier=service_tier)], _catalog())[0]
    assert row["api_usd_known"] == pytest.approx(0.002045)
    assert row["api_standard_fallback"] is False
    assert row["api_cost_unknown"] is False
    assert row["fast_standard_fallback_calls"] == 0
    assert row["unknown_tier_calls"] == int(service_tier == "unknown")


def test_missing_standard_cache_price_cannot_be_fallback():
    catalog = _catalog()
    catalog.models[MODEL]["api_usd"]["cache_write"] = None
    row = request_rows([_event()], catalog)[0]
    assert row["api_usd_known"] == 0
    assert row["priced_calls"] == 0
    assert row["api_standard_fallback"] is False
    assert row["api_cost_unknown"] is True
    assert row["unknown_price_calls"] == 1


def test_non_openai_model_is_not_given_standard_fast_fallback():
    catalog = _catalog(model="claude-test", source="bundled")
    row = request_rows([_event(model="claude-test")], catalog)[0]
    assert row["api_usd_known"] == 0
    assert row["standard_api_usd_known"] == pytest.approx(0.002045)
    assert row["api_standard_fallback"] is False
    assert row["priced_calls"] == 0


@pytest.mark.parametrize("saved_manual", [False, True])
def test_event_snapshot_controls_fallback_instead_of_current_catalog(saved_manual):
    current = _catalog(manual_snapshot=not saved_manual)
    saved = _catalog(manual_snapshot=saved_manual)
    row = request_rows([_event(_price_catalog=saved)], current)[0]
    assert row["api_standard_fallback"] is not saved_manual
    assert row["priced_calls"] == int(not saved_manual)
    assert row["api_cost_unknown"] is True


@pytest.mark.parametrize("multiplier", [None, Decimal(3)])
def test_current_manual_price_takes_priority_over_standard_fallback(tmp_path, monkeypatch, multiplier):
    database = Database(tmp_path / "usage.sqlite3")
    monkeypatch.setattr(database, "distinct_models", lambda: [MODEL])
    remote = {"openai": {"models": {MODEL: {"cost": {
        "input": 2, "cache_read": 0.2, "cache_write": 2.5, "output": 10,
    }}}}}
    store = PricingStore(database=database, fetch_models=lambda: remote)
    assert MODEL in store.refresh()["updated_models"]
    store.set_override(MODEL, {
        "input": Decimal(2), "cached_input": Decimal("0.2"), "cache_write": Decimal("2.5"),
        "output": Decimal(10), "api_fast_multiplier": multiplier,
    })

    row = request_rows([_event()], store.catalog())[0]
    assert row["api_standard_fallback"] is False
    if multiplier is None:
        assert row["priced_calls"] == 0
        assert row["api_usd_known"] == 0
        assert row["api_cost_unknown"] is True
    else:
        assert row["priced_calls"] == 1
        assert row["api_usd_known"] == pytest.approx(0.002045 * 3)
        assert row["api_cost_unknown"] is False


def test_usage_report_can_disable_standard_fallback():
    total = build_report(
        [_event()], _catalog(), start=None, end=None, fast_standard_fallback=False,
    )["total"]
    assert total["api_usd_known"] == 0
    assert total["priced_calls"] == total["fast_standard_fallback_calls"] == 0
    assert total["unknown_fast_price_calls"] == total["unknown_price_calls"] == 1


@pytest.mark.parametrize("has_standard", [False, True])
def test_quota_extrapolation_excludes_unknown_fast_standard_fallback(has_standard):
    catalog = _catalog()
    events = [_event()]
    if has_standard:
        events.append(_event("standard", service_tier="standard"))
    database = SimpleNamespace(fetch_events=lambda **kwargs: events)
    pricing = SimpleNamespace(prepare_events=lambda selected, mode: selected, catalog=lambda: catalog)
    quota = {
        "status": "ready", "fetched_at": "2026-10-01T02:00:00+00:00",
        "reset_records": [], "windows": [{
            "limit_id": "codex", "slot": "primary", "window_minutes": 300,
            "used_percent": 25,
            "resets_at": datetime.fromisoformat("2026-10-01T05:00:00+00:00").timestamp(),
        }],
    }

    row = build_quota_value_report(quota, database, pricing)["windows"][0]

    assert row["status"] == "partial_pricing"
    assert row["total"]["fast_standard_fallback_calls"] == 0
    assert row["total"]["unknown_fast_price_calls"] == 1
    assert row["total"]["unknown_price_calls"] == 1
    assert row["total"]["priced_calls"] == int(has_standard)
    if has_standard:
        assert row["total"]["api_usd_known"] == pytest.approx(0.002045)
        assert row["usd_per_percent"] == pytest.approx(0.002045 / 25)
    else:
        assert row["total"]["api_usd_known"] == 0
        assert row["usd_per_percent"] is None
        assert row["full_quota_usd"] is None
