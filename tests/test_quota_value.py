from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from codex_token_report.db import Database
from codex_token_report.pricing_store import PricingStore
from codex_token_report.quota_value import build_quota_value_report

FETCHED = "2026-09-20T12:00:00+00:00"
START = "2026-09-20T10:00:00+00:00"
RESET = "2026-09-20T15:00:00+00:00"


def epoch(value):
    return datetime.fromisoformat(value).timestamp()


def quota(**changes):
    result = {
        "status": "ready", "message": None, "plan_type": "pro",
        "fetched_at": FETCHED, "reset_records": [],
        "windows": [{
            "limit_id": "codex", "limit_name": "Codex", "slot": "primary",
            "window_minutes": 300, "used_percent": 25, "remaining_percent": 75,
            "resets_at": epoch(RESET),
        }],
    }
    result.update(changes)
    return result


def event(key, stamp="2026-09-20T11:00:00+00:00", **changes):
    result = {
        "event_id": key, "source_file": "fixture.jsonl", "session_id": "one",
        "source_kind": "token_usage_record", "timestamp_utc": stamp,
        "local_date": datetime.fromisoformat(stamp).astimezone(
            ZoneInfo("Asia/Taipei"),
        ).date().isoformat(),
        "model": "gpt-5.6-sol", "pricing_model": None, "turn_id": None,
        "response_id": None, "input_tokens": 100, "cached_input_tokens": 20,
        "cache_write_input_tokens": 0, "output_tokens": 10,
        "reasoning_output_tokens": 0, "total_tokens": 110,
        "service_tier": "standard", "tier_source": "fixture",
    }
    result.update(changes)
    result["total_tokens"] = result["input_tokens"] + result["output_tokens"]
    return result


@pytest.fixture
def local_store(tmp_path):
    database = Database(tmp_path / "usage.sqlite3")
    return database, PricingStore(database=database)


def save(database, events):
    database.replace_file_events(
        source_file="fixture.jsonl", mtime_ns=1, size_bytes=1, parse_errors=0,
        scanned_at=FETCHED, events=events,
    )


def build(local_store, reading=None, **options):
    database, pricing = local_store
    return build_quota_value_report(reading or quota(), database, pricing, **options)


def test_cycle_value_reuses_fast_cache_and_long_context_pricing(local_store):
    database, _ = local_store
    tokens = {"input_tokens": 1_000_000, "cached_input_tokens": 900_000, "output_tokens": 10_000}
    save(database, [event("standard", **tokens), event("fast", service_tier="priority", **tokens)])

    result = build(local_store)
    row = result["windows"][0]
    assert result["status"] == "ready" and result["price_mode"] == "snapshot"
    assert row["cycle_start_at"] == START and row["cycle_start_estimated"]
    assert row["resets_at"] == RESET
    assert row["used_percent"] == 25 and row["remaining_percent"] == 75
    assert row["total"]["api_usd_known"] == pytest.approx(5.46)
    assert row["total"]["long_context_calls"] == 2
    assert row["total"]["fast_calls"] == 1
    assert row["total"]["fast_surcharge_usd"] == pytest.approx(1.82)
    assert row["usd_per_percent"] == pytest.approx(0.2184)
    assert row["full_quota_usd"] == pytest.approx(21.84)
    assert row["remaining_quota_usd"] == pytest.approx(16.38)


def test_interval_includes_start_and_excludes_snapshot_and_later_usage(local_store):
    database, _ = local_store
    save(database, [
        event("before", "2026-09-20T09:59:59.999999+00:00"),
        event("start", START), event("inside", "2026-09-20T11:59:59.999999+00:00"),
        event("snapshot", FETCHED), event("after", "2026-09-20T12:00:00.000001+00:00"),
    ])
    row = build(local_store)["windows"][0]
    assert row["total"]["calls"] == 2
    # Cache age must not move the end of the interval to the present wall clock.
    assert build(local_store)["windows"][0]["total"] == row["total"]


def test_fractional_timestamp_precision_cannot_drop_a_boundary_request(local_store):
    database, _ = local_store
    reading = quota(fetched_at="2026-09-20T12:00:00.100000+00:00")
    reading["windows"][0]["resets_at"] = epoch("2026-09-20T15:00:00.100000+00:00")
    save(database, [
        event("before", "2026-09-20T10:00:00.099999+00:00"),
        event("exact-start", "2026-09-20T10:00:00.1+00:00"),
        event("exact-end", "2026-09-20T12:00:00.1+00:00"),
    ])
    assert build(local_store, reading)["windows"][0]["total"]["calls"] == 1


def test_confirmed_boundary_wins_over_closer_estimate(local_store):
    database, _ = local_store
    reading = quota(reset_records=[
        {"limit_id": "codex", "window_minutes": 300, "reset_at": START,
         "confidence": "estimated", "time_estimated": True},
        {"limit_id": "codex", "window_minutes": 300,
         "reset_at": "2026-09-20T09:59:30+00:00", "confidence": "confirmed",
         "method": "scheduled", "time_estimated": False},
        {"limit_id": "other", "window_minutes": 300, "reset_at": START,
         "confidence": "confirmed", "time_estimated": False},
    ])
    save(database, [event("boundary", "2026-09-20T09:59:45+00:00")])
    row = build(local_store, reading)["windows"][0]
    assert row["cycle_start_at"] == "2026-09-20T09:59:30+00:00"
    assert row["cycle_start_estimated"] is False
    assert row["total"]["calls"] == 1


def test_unrelated_and_distant_reset_records_do_not_change_current_cycle(local_store):
    reading = quota(reset_records=[
        {"limit_id": "codex", "window_minutes": 10080, "reset_at": START,
         "confidence": "confirmed"},
        {"limit_id": "codex", "window_minutes": 300,
         "reset_at": "2026-09-20T09:55:00+00:00", "confidence": "confirmed"},
    ])
    row = build(local_store, reading)["windows"][0]
    assert row["cycle_start_at"] == START and row["cycle_start_estimated"]


def test_early_confirmed_reset_still_marks_its_time_as_estimated(local_store):
    reading = quota(reset_records=[{
        "limit_id": "codex", "window_minutes": 300, "reset_at": START,
        "confidence": "confirmed", "method": "early", "time_estimated": True,
    }])
    assert build(local_store, reading)["windows"][0]["cycle_start_estimated"] is True


def test_overlapping_windows_use_one_fetch_and_prepare_without_a_combined_total(
    local_store, monkeypatch,
):
    database, pricing = local_store
    save(database, [event("older", "2026-09-19T11:00:00+00:00"), event("current")])
    reading = quota()
    reading["windows"].append({
        **reading["windows"][0], "slot": "secondary", "window_minutes": 10080,
        "used_percent": 50, "resets_at": epoch("2026-09-26T10:00:00+00:00"),
    })
    calls = {"fetch": 0, "prepare": 0}
    original_fetch = database.fetch_events
    original_prepare = pricing.prepare_events

    def fetch(*args, **kwargs):
        calls["fetch"] += 1
        return original_fetch(*args, **kwargs)

    def prepare(*args, **kwargs):
        calls["prepare"] += 1
        return original_prepare(*args, **kwargs)

    monkeypatch.setattr(database, "fetch_events", fetch)
    monkeypatch.setattr(pricing, "prepare_events", prepare)
    result = build(local_store, reading)
    assert [row["total"]["calls"] for row in result["windows"]] == [1, 2]
    assert calls == {"fetch": 1, "prepare": 1}
    assert "total" not in result


def test_zero_usage_does_not_invent_a_rolling_cycle_or_a_dollar_value(local_store):
    database, _ = local_store
    save(database, [event("current")])
    reading = quota()
    reading["windows"][0]["used_percent"] = 0
    row = build(local_store, reading)["windows"][0]
    assert row["status"] == "no_usage" and row["remaining_percent"] == 100
    assert row["cycle_start_at"] is None and row["total"] is None
    assert row["usd_per_percent"] is None and row["full_quota_usd"] is None


def test_zero_usage_with_recorded_boundary_can_show_logs_without_extrapolating(local_store):
    database, _ = local_store
    save(database, [event("current")])
    reading = quota(reset_records=[{
        "limit_id": "codex", "window_minutes": 300, "reset_at": START,
        "confidence": "confirmed", "time_estimated": False,
    }])
    reading["windows"][0]["used_percent"] = 0
    row = build(local_store, reading)["windows"][0]
    assert row["status"] == "no_usage" and row["total"]["calls"] == 1
    assert row["usd_per_percent"] is None and row["remaining_quota_usd"] is None


def test_used_quota_without_local_requests_is_unknown_instead_of_free(local_store):
    row = build(local_store)["windows"][0]
    assert row["status"] == "missing_usage"
    assert row["total"] is None and row["full_quota_usd"] is None


@pytest.mark.parametrize("value", [None, -1, 101, float("nan"), float("inf"), True])
def test_missing_and_invalid_percentages_cannot_produce_amounts(local_store, value):
    database, _ = local_store
    save(database, [event("current")])
    reading = quota()
    reading["windows"][0]["used_percent"] = value
    row = build(local_store, reading)["windows"][0]
    assert row["status"] == "unavailable"
    assert row["total"] is None and row["full_quota_usd"] is None


@pytest.mark.parametrize("field,value", [
    ("resets_at", None), ("resets_at", float("inf")), ("resets_at", "invalid"),
    ("window_minutes", None), ("window_minutes", 0), ("window_minutes", -1),
    ("window_minutes", float("inf")), ("window_minutes", 1e100),
])
def test_missing_and_invalid_window_times_cannot_produce_amounts(local_store, field, value):
    reading = quota()
    reading["windows"][0][field] = value
    row = build(local_store, reading)["windows"][0]
    assert row["status"] == "unavailable" and row["total"] is None


@pytest.mark.parametrize("fetched", [None, "invalid", "2026-09-20T12:00:00"])
def test_invalid_snapshot_time_makes_report_unavailable(local_store, fetched):
    result = build(local_store, quota(fetched_at=fetched))
    assert result["status"] == "unavailable"
    assert result["windows"][0]["total"] is None


@pytest.mark.parametrize("reset", [FETCHED, "2026-09-20T11:59:59+00:00"])
def test_expired_reset_requires_refresh_before_valuation(local_store, reset):
    reading = quota()
    reading["windows"][0]["resets_at"] = epoch(reset)
    row = build(local_store, reading)["windows"][0]
    assert row["status"] == "expired" and row["cycle_start_at"] is None
    assert row["total"] is None and row["full_quota_usd"] is None


def test_future_cycle_start_is_not_used(local_store):
    reading = quota()
    reading["windows"][0]["resets_at"] = epoch("2026-09-21T15:00:00+00:00")
    row = build(local_store, reading)["windows"][0]
    assert row["status"] == "unavailable" and row["cycle_start_at"] is None


def test_custom_limit_group_does_not_receive_unattributed_log_amounts(local_store):
    database, _ = local_store
    save(database, [event("current")])
    reading = quota()
    reading["windows"][0]["limit_id"] = "spark"
    row = build(local_store, reading)["windows"][0]
    assert row["status"] == "unsupported"
    assert row["total"] is None and row["usd_per_percent"] is None


def test_unknown_prices_are_ignored_and_known_subtotal_uses_full_consumed_percent(local_store):
    database, _ = local_store
    save(database, [event("known"), event("unknown", model="not-priced")])
    row = build(local_store)["windows"][0]
    assert row["status"] == "partial_pricing"
    assert row["total"]["calls"] == 2 and row["total"]["unknown_price_calls"] == 1
    assert row["total"]["api_usd_known"] == pytest.approx(0.000528)
    assert row["total"]["price_coverage_percent"] == 50
    # Ignore the unknown request's amount, without scaling the 25% quota reading
    # by the 50% request price coverage.
    assert row["used_percent"] == 25
    assert row["usd_per_percent"] == pytest.approx(0.000528 / 25)
    assert row["full_quota_usd"] == pytest.approx(0.000528 / 25 * 100)
    assert row["remaining_quota_usd"] == pytest.approx(0.000528 / 25 * 75)


def test_only_unknown_model_has_no_priced_sample_to_extrapolate(local_store):
    database, _ = local_store
    save(database, [event("unknown", model="not-priced")])
    row = build(local_store)["windows"][0]
    assert row["status"] == "partial_pricing"
    assert row["total"]["priced_calls"] == 0
    assert row["total"]["unknown_price_calls"] == 1
    assert row["total"]["api_usd_known"] == 0
    assert row["usd_per_percent"] is None
    assert row["full_quota_usd"] is None and row["remaining_quota_usd"] is None


def test_unknown_fast_multiplier_preserves_standard_estimate_but_blocks_extrapolation(local_store):
    database, pricing = local_store
    save(database, [event("fast", service_tier="priority")])
    pricing.set_override("gpt-5.6-sol", {
        "input": Decimal(4), "cached_input": Decimal("0.4"), "cache_write": None,
        "output": Decimal(20), "api_fast_multiplier": None,
    })
    row = build(local_store, price_mode="current")["windows"][0]
    assert row["status"] == "partial_pricing"
    assert row["total"]["priced_calls"] == 0
    assert row["total"]["unknown_fast_price_calls"] == 1
    assert row["total"]["standard_api_usd_known"] > 0
    assert row["usd_per_percent"] is None
    assert row["full_quota_usd"] is None and row["remaining_quota_usd"] is None


def test_known_request_and_unknown_fast_use_only_priced_amount_for_extrapolation(local_store):
    database, pricing = local_store
    save(database, [event("known"), event("fast", service_tier="priority")])
    pricing.set_override("gpt-5.6-sol", {
        "input": Decimal(4), "cached_input": Decimal("0.4"), "cache_write": None,
        "output": Decimal(20), "api_fast_multiplier": None,
    })
    row = build(local_store, price_mode="current")["windows"][0]
    assert row["status"] == "partial_pricing"
    assert row["total"]["priced_calls"] == 1 and row["total"]["unknown_fast_price_calls"] == 1
    assert row["total"]["api_usd_known"] == pytest.approx(0.000528)
    # The Standard fallback for the unpriced Fast request must not enter API USD.
    assert row["total"]["standard_api_usd_known"] == pytest.approx(0.000528 * 2)
    assert row["usd_per_percent"] == pytest.approx(0.000528 / 25)
    assert row["full_quota_usd"] == pytest.approx(0.000528 / 25 * 100)
    assert row["remaining_quota_usd"] == pytest.approx(0.000528 / 25 * 75)


def test_fully_priced_zero_dollar_sample_can_extrapolate_zero(local_store):
    database, pricing = local_store
    save(database, [event("free")])
    pricing.set_override("gpt-5.6-sol", {
        "input": Decimal(0), "cached_input": Decimal(0), "cache_write": None,
        "output": Decimal(0), "api_fast_multiplier": Decimal(2),
    })
    row = build(local_store, price_mode="current")["windows"][0]
    assert row["status"] == "ready"
    assert row["total"]["priced_calls"] == 1 and row["total"]["unknown_price_calls"] == 0
    assert row["total"]["api_usd_known"] == 0
    assert row["usd_per_percent"] == 0
    assert row["full_quota_usd"] == 0 and row["remaining_quota_usd"] == 0


def test_unknown_tier_uses_existing_standard_estimate_and_keeps_coverage(local_store):
    database, _ = local_store
    save(database, [event("current", service_tier="unknown")])
    row = build(local_store)["windows"][0]
    assert row["status"] == "ready" and row["full_quota_usd"] > 0
    assert row["total"]["unknown_tier_calls"] == 1
    assert row["total"]["tier_coverage_percent"] == 0


def test_snapshot_and_current_modes_preserve_request_price_history(local_store):
    database, pricing = local_store
    save(database, [event("current")])
    original = build(local_store)["windows"][0]
    pricing.set_override("gpt-5.6-sol", {
        "input": Decimal(100), "cached_input": Decimal(20), "cache_write": None,
        "output": Decimal(200), "api_fast_multiplier": Decimal(3),
    })
    frozen = build(local_store)["windows"][0]
    current = build(local_store, price_mode="current")["windows"][0]
    assert frozen["total"] == original["total"]
    assert frozen["full_quota_usd"] == original["full_quota_usd"]
    assert current["total"]["api_usd_known"] > frozen["total"]["api_usd_known"]


def test_no_windows_and_unavailable_quota_cannot_return_old_valuations(local_store):
    assert build(local_store, quota(windows=[]))["status"] == "unavailable"
    reading = quota(status="unavailable", message="已退出登录", _account_key="private")
    result = build(local_store, reading)
    assert result["status"] == "unavailable" and result["message"] == "已退出登录"
    assert result["windows"] == [] and "_account_key" not in result


def test_valuation_does_not_modify_shared_quota_cache(local_store):
    reading = quota()
    before = deepcopy(reading)
    build(local_store, reading)
    assert reading == before


def test_snapshot_offset_is_normalized_to_utc(local_store):
    result = build(local_store, quota(fetched_at="2026-09-20T20:00:00+08:00"), timezone="UTC")
    assert result["fetched_at"] == FETCHED
    assert result["windows"][0]["cycle_start_at"] == START


def test_invalid_price_mode_is_rejected(local_store):
    with pytest.raises(ValueError, match="price_mode"):
        build(local_store, price_mode="unsupported")
