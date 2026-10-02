import json
import sqlite3
from datetime import datetime
from decimal import Decimal

import pytest

from codex_token_report.db import Database
from codex_token_report.pricing_store import PricingStore
from codex_token_report.quota_value_history import QuotaValueHistory

ALICE = "a" * 64
BOB = "b" * 64
FETCHED = "2026-09-20T12:00:00+00:00"
RESET = "2026-09-20T15:00:00+00:00"


def quota(fetched=FETCHED, reset=RESET, used=25, **changes):
    result = {
        "status": "ready", "message": None, "plan_type": "pro",
        "fetched_at": fetched, "reset_records": [],
        "windows": [{
            "limit_id": "codex", "limit_name": "Codex", "slot": "primary",
            "window_minutes": 300, "used_percent": used,
            "resets_at": datetime.fromisoformat(reset).timestamp(),
        }],
    }
    result.update(changes)
    return result


def event(key="one", stamp="2026-09-20T11:00:00+00:00", **changes):
    result = {
        "event_id": key, "source_file": "fixture.jsonl", "session_id": "one",
        "source_kind": "token_usage_record", "timestamp_utc": stamp,
        "local_date": stamp[:10], "model": "gpt-5.6-sol", "pricing_model": None,
        "turn_id": None, "response_id": None, "input_tokens": 100,
        "cached_input_tokens": 20, "cache_write_input_tokens": 0,
        "output_tokens": 10, "reasoning_output_tokens": 0, "total_tokens": 110,
        "service_tier": "standard", "tier_source": "fixture",
    }
    return {**result, **changes}


def save(database, events):
    database.replace_file_events(
        source_file="fixture.jsonl", mtime_ns=1, size_bytes=1,
        parse_errors=0, scanned_at=FETCHED, events=events,
    )


@pytest.fixture
def store(tmp_path):
    database = Database(tmp_path / "usage.sqlite3")
    pricing = PricingStore(database=database)
    save(database, [event()])
    return database, pricing, QuotaValueHistory(database, pricing, "Asia/Taipei")


def override(pricing, amount):
    pricing.set_override("gpt-5.6-sol", {
        "input": Decimal(amount), "cached_input": Decimal(amount), "cache_write": None,
        "output": Decimal(amount), "api_fast_multiplier": Decimal(2),
    })


def test_previous_cycle_last_read_survives_reset_and_restart_without_becoming_100_percent(store):
    database, _, history = store
    history.observe(ALICE, quota())
    old = history.records(ALICE)["cycles"][0]
    save(database, [event(), event("new", "2026-09-20T15:30:00+00:00")])
    current = quota("2026-09-20T16:00:00+00:00", "2026-09-20T20:00:00+00:00", 10)
    history.observe(ALICE, current)

    reopened_db = Database(database.path)
    reopened = QuotaValueHistory(reopened_db, PricingStore(database=reopened_db), "UTC")
    result = reopened.records(ALICE, current_quota=current)
    assert result["total"] == 2
    assert [row["used_percent"] for row in result["cycles"]] == [10, 25]
    assert [row["is_current"] for row in result["cycles"]] == [True, False]
    previous = result["cycles"][1]
    assert previous["id"] == old["id"] and previous["fetched_at"] == FETCHED
    assert previous["total"]["api_usd_known"] == old["total"]["api_usd_known"]
    assert previous["full_quota_usd"] == old["full_quota_usd"]
    assert previous["observation_count"] == 1


def test_same_cycle_keeps_all_reads_and_lists_latest_actual_values(store):
    database, _, history = store
    history.observe(ALICE, quota())
    cycle_id = history.records(ALICE)["cycles"][0]["id"]
    save(database, [event(), event("two", "2026-09-20T12:00:30+00:00")])
    history.observe(ALICE, quota("2026-09-20T12:01:00+00:00", used=30))

    result = history.records(ALICE)
    assert result["total"] == 1 and result["cycles"][0]["id"] == cycle_id
    latest = result["cycles"][0]
    assert latest["used_percent"] == 30 and latest["observation_count"] == 2
    assert latest["total"]["calls"] == 2
    detail = history.observations(ALICE, cycle_id)
    assert detail["cycle"] == latest
    assert [row["used_percent"] for row in detail["observations"]] == [30, 25]
    assert [row["total"]["calls"] for row in detail["observations"]] == [2, 1]


def test_reset_jitter_within_tolerance_stays_in_one_cycle(store):
    _, _, history = store
    history.observe(ALICE, quota())
    first = history.records(ALICE)["cycles"][0]
    history.observe(ALICE, quota("2026-09-20T12:02:00+00:00", "2026-09-20T15:01:30+00:00", 26))
    result = history.records(ALICE)
    assert result["total"] == 1 and result["cycles"][0]["id"] == first["id"]
    assert result["cycles"][0]["observation_count"] == 2
    assert result["cycles"][0]["resets_at"] == "2026-09-20T15:01:30+00:00"


def test_confirmed_start_correction_is_saved_without_rewriting_earlier_estimate(store):
    _, _, history = store
    history.observe(ALICE, quota())
    current = quota("2026-09-20T12:02:00+00:00", used=26, reset_records=[{
        "limit_id": "codex", "window_minutes": 300,
        "reset_at": "2026-09-20T09:59:30+00:00", "confidence": "confirmed",
        "time_estimated": False, "method": "scheduled",
    }])
    history.observe(ALICE, current)
    latest = history.records(ALICE)["cycles"][0]
    assert latest["cycle_start_at"] == "2026-09-20T09:59:30+00:00"
    assert latest["time_estimated"] is False and latest["cycle_start_estimated"] is False
    detail = history.observations(ALICE, latest["id"])
    assert detail["observations"][1]["cycle_start_at"] == "2026-09-20T10:00:00+00:00"
    assert detail["observations"][1]["time_estimated"] is True


def test_early_reset_before_old_future_reset_starts_a_distinct_cycle(store):
    _, _, history = store
    history.observe(ALICE, quota())
    current = quota("2026-09-20T12:05:00+00:00", "2026-09-20T17:00:00+00:00", 1)
    history.observe(ALICE, current)
    result = history.records(ALICE, current_quota=current)
    assert result["total"] == 2
    assert [row["used_percent"] for row in result["cycles"]] == [1, 25]
    assert [row["is_current"] for row in result["cycles"]] == [True, False]


def test_account_isolation_and_public_ids_never_expose_private_identity(store):
    database, _, history = store
    reading = quota(email="private@example.com", access_token="private-token")
    reading["windows"][0]["token"] = "private-token"
    history.observe(ALICE, reading)
    history.observe(BOB, quota(used=50))
    alice = history.records(ALICE)
    bob = history.records(BOB)
    assert alice["total"] == bob["total"] == 1
    assert alice["cycles"][0]["used_percent"] == 25
    assert bob["cycles"][0]["used_percent"] == 50
    cycle_id = alice["cycles"][0]["id"]
    assert isinstance(cycle_id, int)
    assert history.observations(BOB, cycle_id) is None
    assert history.observations(ALICE, 999999) is None
    public = json.dumps(alice)
    assert ALICE not in public and BOB not in public
    with database.connect() as connection:
        payloads = " ".join(row[0] for row in connection.execute(
            "SELECT payload_json FROM quota_value_observations",
        ))
    assert "private@example.com" not in payloads and "private-token" not in payloads


@pytest.mark.parametrize("field,value", [
    ("slot", "secondary"), ("window_minutes", 360), ("limit_id", "spark"),
    ("plan_type", "prolite"), ("plan_type", None),
])
def test_slots_durations_groups_and_plans_never_mix_cycles(store, field, value):
    _, _, history = store
    history.observe(ALICE, quota())
    changed = quota("2026-09-20T12:01:00+00:00", used=30)
    if field == "plan_type":
        changed[field] = value
    else:
        changed["windows"][0][field] = value
    history.observe(ALICE, changed)
    result = history.records(ALICE, current_quota=changed)
    assert result["total"] == 2
    assert [row["observation_count"] for row in result["cycles"]] == [1, 1]
    assert [row["is_current"] for row in result["cycles"]] == [True, False]
    if field == "limit_id":
        assert result["cycles"][0]["status"] == "unsupported"
        assert result["cycles"][0]["total"] is None


def test_repeated_read_cannot_overwrite_prices_usage_or_last_scan(store):
    database, pricing, history = store
    original_scan = {"finished_at": FETCHED, "stored_events": 1}
    database.set_metadata("last_scan", json.dumps(original_scan))
    history.observe(ALICE, quota())
    originals = {mode: history.records(ALICE, price_mode=mode)
                 for mode in ("snapshot", "current")}
    override(pricing, 100)
    save(database, [event(), event("late-import", "2026-09-20T11:30:00+00:00")])
    database.set_metadata("last_scan", json.dumps({"stored_events": 2}))
    history.observe(ALICE, quota(used=50))
    for mode in ("snapshot", "current"):
        assert history.records(ALICE, price_mode=mode) == originals[mode]
        assert originals[mode]["cycles"][0]["last_scan"] == original_scan
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM quota_value_observations").fetchone()[0] == 2


def test_both_price_modes_are_frozen_at_the_time_of_each_read(store):
    _, pricing, history = store
    override(pricing, 100)
    history.observe(ALICE, quota())
    snapshot = history.records(ALICE)["cycles"][0]
    current = history.records(ALICE, price_mode="current")["cycles"][0]
    assert snapshot["id"] == current["id"]
    assert snapshot["price_mode"] == "snapshot" and current["price_mode"] == "current"
    assert current["total"]["api_usd_known"] > snapshot["total"]["api_usd_known"]
    override(pricing, 200)
    assert history.records(ALICE, price_mode="current")["cycles"][0] == current
    history.observe(ALICE, quota("2026-09-20T12:01:00+00:00", used=30))
    detail = history.observations(ALICE, current["id"], price_mode="current")
    assert detail["observations"][0]["total"]["api_usd_known"] > current["total"]["api_usd_known"]
    assert detail["observations"][1] == {**current, "observation_count": 2}


def test_latest_missing_amount_is_kept_instead_of_reusing_earlier_known_amount(store):
    database, _, history = store
    history.observe(ALICE, quota())
    cycle_id = history.records(ALICE)["cycles"][0]["id"]
    save(database, [])
    history.observe(ALICE, quota("2026-09-20T17:01:00+00:00",
                                 "2026-09-20T20:00:00+00:00", used=30))
    latest = history.records(ALICE)["cycles"][0]
    assert latest["used_percent"] == 30 and latest["total"] is None
    assert latest["status"] == "missing_usage" and latest["usd_per_percent"] is None
    detail = history.observations(ALICE, cycle_id)
    assert detail["observations"][0]["total"]["api_usd_known"] > 0


def test_partial_pricing_values_and_unknown_sample_are_preserved(store):
    database, _, history = store
    save(database, [event(), event("unknown", model="not-priced")])
    history.observe(ALICE, quota())
    first = history.records(ALICE)["cycles"][0]
    assert first["status"] == "partial_pricing"
    assert first["total"]["unknown_price_calls"] == 1 and first["usd_per_percent"] > 0
    save(database, [event("only-unknown", "2026-09-20T16:00:00+00:00", model="not-priced")])
    history.observe(ALICE, quota("2026-09-20T17:01:00+00:00",
                                 "2026-09-20T20:00:00+00:00", used=30))
    latest = history.records(ALICE)["cycles"][0]
    assert latest["status"] == "partial_pricing" and latest["usd_per_percent"] is None
    assert latest["total"]["priced_calls"] == 0


def test_fractional_read_timestamps_sort_numerically_and_equal_instants_are_idempotent(store):
    _, _, history = store
    history.observe(ALICE, quota("2026-09-20T12:00:00.1+00:00", used=25))
    history.observe(ALICE, quota("2026-09-20T12:00:00.100000+00:00", used=30))
    history.observe(ALICE, quota("2026-09-20T12:00:00.100001+00:00", used=40))
    latest = history.records(ALICE)["cycles"][0]
    assert latest["used_percent"] == 40 and latest["observation_count"] == 2
    values = history.observations(ALICE, latest["id"])["observations"]
    assert [row["used_percent"] for row in values] == [40, 25]
    assert values[1]["fetched_at"] == "2026-09-20T12:00:00.100000+00:00"


def test_cycle_pagination_sorts_by_snapshot_time_instead_of_insert_order(store):
    _, _, history = store
    for day in (22, 20, 21):
        history.observe(ALICE, quota(
            f"2026-09-{day}T12:00:00+00:00", f"2026-09-{day}T15:00:00+00:00",
        ))
    first = history.records(ALICE, limit=2)
    assert first["status"] == "ready" and first["total"] == 3
    assert [row["fetched_at"][8:10] for row in first["cycles"]] == ["22", "21"]
    assert first["offset"] == 0 and first["limit"] == 2 and first["has_more"]
    second = history.records(ALICE, offset=2, limit=2)
    assert second["cycles"][0]["fetched_at"][8:10] == "20" and not second["has_more"]
    assert history.records(ALICE, offset=10)["cycles"] == []


def test_zero_percent_rolling_timer_creates_no_false_history_or_current_badge(store):
    _, _, history = store
    history.observe(ALICE, quota())
    old = history.records(ALICE)["cycles"][0]
    unused = quota("2026-09-20T16:00:00+00:00", "2026-09-20T21:00:00+00:00", 0)
    history.observe(ALICE, unused)
    assert history.records(ALICE)["total"] == 1
    result = history.records(ALICE, current_quota=unused)
    assert result["cycles"][0]["is_current"] is False
    assert history.observations(ALICE, old["id"], current_quota=unused)["cycle"]["is_current"] is False


def test_unused_rolling_window_never_creates_a_cycle_on_first_read(store):
    _, _, history = store
    history.observe(ALICE, quota(used=0))
    assert history.records(ALICE)["total"] == 0


def test_zero_usage_with_known_boundary_can_be_saved_without_extrapolation(store):
    _, _, history = store
    reading = quota(used=0, reset_records=[{
        "limit_id": "codex", "window_minutes": 300,
        "reset_at": "2026-09-20T10:00:00+00:00", "confidence": "confirmed",
        "time_estimated": False,
    }])
    history.observe(ALICE, reading)
    row = history.records(ALICE)["cycles"][0]
    assert row["used_percent"] == 0 and row["usd_per_percent"] is None
    assert row["time_estimated"] is False and row["status"] == "no_usage"


def test_multiple_windows_in_one_read_keep_separate_cycles(store):
    _, _, history = store
    reading = quota()
    reading["windows"].append({**reading["windows"][0], "slot": "secondary", "used_percent": 50})
    history.observe(ALICE, reading)
    result = history.records(ALICE, current_quota=reading)
    assert result["total"] == 2
    assert {row["slot"] for row in result["cycles"]} == {"primary", "secondary"}
    assert all(row["is_current"] and row["observation_count"] == 1 for row in result["cycles"])


def test_history_reads_do_not_call_pricing_scan_or_report_builder(store, monkeypatch):
    database, pricing, history = store
    history.observe(ALICE, quota())
    cycle_id = history.records(ALICE)["cycles"][0]["id"]

    def fail(*args, **kwargs):
        raise AssertionError("history reads must not recalculate")

    monkeypatch.setattr(pricing, "prepare_events", fail)
    monkeypatch.setattr(pricing, "catalog", fail)
    monkeypatch.setattr(database, "fetch_events", fail)
    monkeypatch.setattr("codex_token_report.quota_value_history.build_quota_value_report", fail)
    assert history.records(ALICE)["total"] == 1
    assert history.observations(ALICE, cycle_id)["cycle"]["used_percent"] == 25


@pytest.mark.parametrize("key", [None, "", "   ", 123, False])
def test_missing_identity_does_not_persist_or_expose_any_history(store, key):
    _, _, history = store
    history.observe(key, quota())
    assert history.records(key)["cycles"] == []
    assert history.observations(key, 1) is None
    assert history.records(ALICE)["total"] == 0


@pytest.mark.parametrize("reading", [
    None, [], {}, quota(status="unavailable"), quota(fetched=None),
    quota(fetched="invalid"), quota(fetched="2026-09-20T12:00:00"),
    quota(fetched=float("nan")), quota(windows=[]), quota(used=None),
    quota(used=-1), quota(used=101), quota(used=float("inf")),
])
def test_invalid_or_unavailable_readings_do_not_create_history(store, reading):
    _, _, history = store
    history.observe(ALICE, reading)
    assert history.records(ALICE)["total"] == 0


def test_malformed_scan_metadata_does_not_prevent_persistence(store):
    database, _, history = store
    database.set_metadata("last_scan", "invalid JSON")
    history.observe(ALICE, quota())
    assert history.records(ALICE)["cycles"][0]["last_scan"] is None


def test_additive_schema_initialization_preserves_existing_database_metadata(tmp_path):
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO metadata VALUES ('existing', 'keep');
        """)
    database = Database(path)
    assert database.get_metadata("existing") == "keep"
    with database.connect() as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"quota_value_cycles", "quota_value_observations"} <= tables
    reopened = Database(path)
    assert reopened.get_metadata("existing") == "keep"


@pytest.mark.parametrize("options", [{"price_mode": "invalid"}, {"offset": -1}, {"limit": 0}])
def test_invalid_history_query_parameters_are_rejected(store, options):
    _, _, history = store
    with pytest.raises(ValueError):
        history.records(ALICE, **options)


@pytest.mark.parametrize("cycle_id", [None, 0, -1, True, "1"])
def test_invalid_detail_ids_cannot_match_a_cycle(store, cycle_id):
    _, _, history = store
    history.observe(ALICE, quota())
    assert history.observations(ALICE, cycle_id) is None
