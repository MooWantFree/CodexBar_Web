from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from codex_token_report.config import Settings
from codex_token_report.db import Database
from codex_token_report.main import create_app
from codex_token_report.quota import QuotaError, QuotaService
from codex_token_report.quota_history import QuotaHistory, account_key

WEEK = 7 * 24 * 60 * 60


def stamp(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


def reading(reset: float, used: float | None, **changes) -> dict:
    quota = {
        "status": "ready", "plan_type": "prolite", "credits": None,
        "reset_credits_available": None,
        "windows": [{
            "limit_id": "codex", "limit_name": "codex", "slot": "primary",
            "used_percent": used, "window_minutes": 10080, "resets_at": reset,
        }],
    }
    quota.update(changes)
    return quota


@pytest.fixture
def history(tmp_path: Path) -> QuotaHistory:
    return QuotaHistory(Database(tmp_path / "usage.sqlite3"), "Asia/Taipei")


def test_scheduled_reset_survives_restart_and_uses_boundary_day(history: QuotaHistory) -> None:
    # UTC date differs from the date displayed in the application's timezone.
    reset = stamp("2026-09-20T16:00:00+00:00")
    assert history.observe("alice", reading(reset, 25), reset - 120) == []
    # Crossing the boundary is insufficient until the service reports a new cycle.
    assert history.observe("alice", reading(reset, 25), reset + 10) == []
    restored = QuotaHistory(history.database, "Asia/Taipei")
    events = restored.observe("alice", reading(reset + WEEK, 30), reset + 60)
    assert len(events) == 1  # May already have used more than in the previous cycle.
    assert events[0]["date"] == "2026-09-21"
    assert events[0]["reset_at"] == "2026-09-20T16:00:00+00:00"
    assert events[0]["method"] == "scheduled"
    assert restored.observe("alice", reading(reset + WEEK, 31), reset + 120) == events
    utc = QuotaHistory(history.database, "UTC")
    assert utc.observe("alice", reading(reset + WEEK, 31), reset + 180)[0]["date"] == "2026-09-20"


def test_early_reset_requires_two_spaced_consistent_reads_and_survives_restart(
    history: QuotaHistory,
) -> None:
    now = stamp("2026-09-20T16:05:00+00:00")
    old = now + 2 * 24 * 3600
    history.observe("alice", reading(old, 70), now - 300)
    assert history.observe("alice", reading(now + WEEK, 0), now + 10) == []
    assert history.observe("alice", reading(now + WEEK, 0), now + 30) == []
    restored = QuotaHistory(history.database, "Asia/Taipei")
    # Optional credits-only updates retain pending reset evidence.
    assert restored.observe("alice", reading(now + WEEK, 0, windows=[]), now + 45) == []
    events = restored.observe("alice", reading(now + WEEK, 1), now + 70)
    assert events[0]["date"] == "2026-09-21"
    assert events[0]["method"] == "early"


def test_reverted_early_read_and_simple_percentage_correction_do_not_mark(
    history: QuotaHistory,
) -> None:
    now = stamp("2026-09-20T16:05:00+00:00")
    old = now + 2 * 24 * 3600
    history.observe("alice", reading(old, 70), now - 300)
    assert history.observe("alice", reading(old, 50), now - 120) == []
    assert history.observe("alice", reading(now + WEEK, 0), now + 10) == []
    assert history.observe("alice", reading(old, 70), now + 70) == []
    assert history.observe("alice", reading(old, 70), now + 130) == []


@pytest.mark.parametrize("change", ["plan", "duration", "account", "slot"])
def test_identity_and_window_changes_establish_new_baseline(
    history: QuotaHistory, change: str,
) -> None:
    now = stamp("2026-09-20T16:05:00+00:00")
    old = now + 2 * 24 * 3600
    history.observe("alice", reading(old, 70), now - 300)
    current = reading(now + WEEK, 0)
    key = "alice"
    if change == "plan":
        current["plan_type"] = "pro"
    elif change == "duration":
        current["windows"][0]["window_minutes"] = 14400
    elif change == "slot":
        current["windows"][0]["slot"] = "secondary"
    else:
        key = "bob"
    assert history.observe(key, current, now + 10) == []
    assert history.observe(key, current, now + 70) == []


def test_zero_usage_rolling_timer_and_skipped_cycles_do_not_invent_history(
    history: QuotaHistory,
) -> None:
    now = stamp("2026-09-20T16:05:00+00:00")
    assert history.observe("unused", reading(now + WEEK, 0), now) == []
    assert history.observe("unused", reading(now + WEEK + 60, 0), now + 60) == []
    assert history.observe("unused", reading(now + WEEK * 2, 0), now + WEEK + 60) == []
    history.observe("alice", reading(now + 120, 70), now)
    assert history.observe("alice", reading(now + 120 + WEEK * 2, 0), now + WEEK + 180) == []
    assert history.observe("first", reading(now + WEEK, 10), now) == []


def test_changed_duration_cannot_reuse_a_baseline_when_it_changes_back(
    history: QuotaHistory,
) -> None:
    now = stamp("2026-09-20T16:05:00+00:00")
    history.observe("alice", reading(now + 2 * 24 * 3600, 70), now - 300)
    changed = reading(now + WEEK, 0)
    changed["windows"][0]["window_minutes"] = 14400
    assert history.observe("alice", changed, now + 10) == []
    assert history.observe("alice", reading(now + WEEK, 0), now + 70) == []
    assert history.observe("alice", reading(now + WEEK, 0), now + 130) == []


def test_missing_or_invalid_read_does_not_replace_prior_evidence(history: QuotaHistory) -> None:
    reset = stamp("2026-09-20T16:00:00+00:00")
    history.observe("alice", reading(reset, 25), reset - 300)
    assert history.observe("alice", reading(reset, None), reset - 200) == []
    assert history.observe("alice", reading(reset, -10), reset - 100) == []
    events = history.observe("alice", reading(reset + WEEK, 0), reset + 60)
    assert events[0]["date"] == "2026-09-21"


def test_multiple_windows_share_dates_without_duplicate_events(history: QuotaHistory) -> None:
    reset = stamp("2026-09-20T16:00:00+00:00")
    previous = reading(reset, 25)
    short = {**previous["windows"][0], "slot": "secondary", "window_minutes": 300}
    previous["windows"].append(short)
    history.observe("alice", previous, reset - 60)
    current = deepcopy(previous)
    current["windows"][0]["resets_at"] += WEEK
    current["windows"][1]["resets_at"] += 300 * 60
    events = history.observe("alice", current, reset + 60)
    assert len(events) == 2
    assert {event["date"] for event in events} == {"2026-09-21"}
    assert history.observe("alice", current, reset + 120) == events
    assert history.observe("bob", current, reset + 60) == []


def test_identity_is_hashed_and_missing_identity_disables_recording(tmp_path: Path) -> None:
    key = account_key({"email": "private@example.com"}, tmp_path)
    assert key and len(key) == 64 and "private" not in key
    assert account_key({"planType": "pro"}, tmp_path) is None
    assert key != account_key({"email": "someone@example.com"}, tmp_path)


def test_used_cycle_estimate_is_saved_but_does_not_bold_calendar(history: QuotaHistory):
    now = stamp("2026-09-20T16:05:30+00:00")
    reset = now + WEEK - 300
    assert history.observe("alice", reading(reset, 4), now) == []
    records = history.records("alice", now)
    assert len(records) == 1
    assert records[0]["reset_at"] == "2026-09-20T16:00:30+00:00"
    assert records[0]["confidence"] == "estimated" and records[0]["time_estimated"]
    assert records[0]["date"] == "2026-09-21"
    assert QuotaHistory(history.database, "UTC").records("alice", now)[0]["date"] == "2026-09-20"
    history.observe("alice", reading(reset + 60, 5), now + 60)
    assert len(history.records("alice", now + 60)) == 1
    assert history.records("bob", now) == []
    history.observe("unused", reading(reset, 0), now)
    assert history.records("unused", now) == []


def test_confirmation_replaces_a_nearby_estimate(history: QuotaHistory):
    reset = stamp("2026-09-20T16:00:30+00:00")
    history.observe("alice", reading(reset + 2 * 24 * 3600, 80), reset - 60)
    assert history.observe("alice", reading(reset + WEEK, 1), reset + 10) == []
    assert any(item["method"] == "estimated" and item["reset_at"] == "2026-09-20T16:00:30+00:00" for item in history.records("alice", reset + 10))
    history.observe("alice", reading(reset + WEEK + 30, 2), reset + 80)
    records = history.records("alice", reset + 80)
    recent = [item for item in records if item["date"] == "2026-09-21"]
    assert len(recent) == 1
    assert recent[0]["method"] == "early" and recent[0]["confidence"] == "confirmed"


def test_api_records_history_without_exposing_identity_and_restores_on_fetch_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(Settings(codex_home=tmp_path, data_dir=tmp_path / "data", scan_interval_minutes=0))
    service: QuotaService = app.state.quota
    now = datetime.now(UTC).timestamp()
    reset = now - 60
    key = account_key({"email": "private@example.com"}, tmp_path)
    service.history.observe(key, reading(reset, 25), reset - 60)
    response = reading(reset + WEEK, 0)
    response["_account_key"] = key
    monkeypatch.setattr(service, "_fetch", lambda: deepcopy(response))
    with TestClient(app) as client:
        result = client.get("/api/quota")
        assert result.json()["reset_events"]
        assert result.json()["reset_history_status"] == "recording"
        assert result.json()["reset_records"]
        assert result.json()["reset_history_scope"]
        assert "private@example.com" not in result.text and key not in result.text
        assert client.post("/api/quota/refresh").json()["reset_events"] == result.json()["reset_events"]
        assert client.post("/api/quota/refresh").json()["reset_history_scope"] == result.json()["reset_history_scope"]

        def fail():
            raise QuotaError("已退出登录")

        monkeypatch.setattr(service, "_fetch", fail)
        offline = client.post("/api/quota/refresh").json()
        assert offline["reset_events"] == result.json()["reset_events"]
        assert offline["history_mode"] == "offline"
        assert offline["history_label"] == "上次保存的账号"
        assert offline["reset_history_status"] == "available"
        assert offline["windows"] == [] and offline["fetched_at"] is None
        assert "private@example.com" not in str(offline) and key not in str(offline)
        monkeypatch.setattr(service, "_fetch", lambda: deepcopy(response))
        assert client.post("/api/quota/refresh").json()["reset_events"] == result.json()["reset_events"]
