import json
import sqlite3
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from codex_token_report.config import Settings
from codex_token_report.main import create_app
from codex_token_report.quota import QuotaError


def epoch(value):
    return datetime.fromisoformat(value).timestamp()


def reading(reset="2026-09-20T15:00:00+00:00", used=25, identity="account-a"):
    return {
        "status": "ready", "message": None, "plan_type": "pro",
        "_account_key": identity,
        "windows": [{
            "limit_id": "codex", "limit_name": "Codex", "slot": "primary",
            "used_percent": used, "remaining_percent": 100 - used,
            "window_minutes": 300, "resets_at": epoch(reset),
        }],
    }


@pytest.fixture
def history_app(tmp_path, monkeypatch):
    settings = Settings(codex_home=tmp_path / "codex", data_dir=tmp_path / "data",
                        scan_interval_minutes=0)
    app = create_app(settings)
    state = {"now": datetime.fromisoformat("2026-09-20T12:00:00+00:00"),
             "reading": reading(), "calls": 0, "error": False}

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return state["now"].astimezone(tz or UTC)

    def fetch():
        state["calls"] += 1
        if state["error"]:
            raise QuotaError("已退出登录")
        return deepcopy(state["reading"])

    monkeypatch.setattr("codex_token_report.quota.datetime", Clock)
    monkeypatch.setattr(app.state.quota, "_fetch", fetch)
    timestamps = ["2026-09-20T11:00:00+00:00", "2026-09-20T12:30:00+00:00",
                  "2026-09-20T15:30:00+00:00"]
    app.state.database.replace_file_events(
        source_file="history.jsonl", mtime_ns=1, size_bytes=1, parse_errors=0,
        scanned_at=state["now"].isoformat(),
        events=[{
            "event_id": f"event-{index}", "source_file": "history.jsonl",
            "source_kind": "token_usage_record", "timestamp_utc": timestamp,
            "local_date": "2026-09-20", "model": "gpt-5.6-sol",
            "input_tokens": 1000, "cached_input_tokens": 0, "cache_write_input_tokens": 0,
            "output_tokens": 0, "reasoning_output_tokens": 0, "total_tokens": 1000,
            "service_tier": "standard", "pricing_model": "gpt-5.6-sol",
            "turn_id": None, "response_id": None, "tier_source": "fixture",
            "project_key": None, "project_path": None, "workspace_root": None,
            "working_directory": None,
        } for index, timestamp in enumerate(timestamps)],
    )
    return app, TestClient(app), state, settings, fetch


def test_refresh_records_previous_cycle_percentage_and_spent_amount(history_app):
    app, client, state, settings, fetch = history_app
    assert client.get("/api/quota/value/history").json()["cycles"] == []
    first = client.get("/api/quota").json()
    assert first["value_history_status"] == "recording"
    only_current = client.get("/api/quota/value/history?include_current=false").json()
    assert only_current["status"] == "ready" and only_current["cycles"] == []
    assert only_current["total"] == 0 and not only_current["has_more"]
    state["now"] = datetime.fromisoformat("2026-09-20T13:00:00+00:00")
    state["reading"] = reading(used=50)
    assert client.post("/api/quota/refresh").status_code == 200
    state["now"] = datetime.fromisoformat("2026-09-20T16:00:00+00:00")
    state["reading"] = reading("2026-09-20T20:00:00+00:00", used=20)
    client.post("/api/quota/refresh")

    report = client.get("/api/quota/value/history").json()
    assert report["total"] == 2 and not report["has_more"]
    latest, previous = report["cycles"]
    assert latest["is_current"] and not previous["is_current"]
    assert previous["used_percent"] == 50  # Last observed value, never an invented 100%.
    assert previous["fetched_at"] == "2026-09-20T13:00:00+00:00"
    assert previous["total"]["api_usd_known"] == pytest.approx(0.008)
    assert previous["observation_count"] == 2
    details = client.get(f"/api/quota/value/history/{previous['id']}").json()
    assert [row["used_percent"] for row in details["observations"]] == [50, 25]
    assert not details["cycle"]["is_current"]
    assert [row["total"]["api_usd_known"] for row in details["observations"]] == [0.008, 0.004]
    assert state["calls"] == 3  # History and details do not refresh quota.
    assert "account-a" not in json.dumps(report)

    filtered = client.get("/api/quota/value/history?include_current=false&limit=1").json()
    assert filtered["cycles"] == [previous]
    assert filtered["total"] == 1 and not filtered["has_more"]
    next_page = client.get("/api/quota/value/history?include_current=false&offset=1&limit=1").json()
    assert next_page["cycles"] == [] and next_page["total"] == 1 and not next_page["has_more"]

    page = client.get("/api/quota/value/history?limit=1").json()
    assert page["total"] == 2 and page["has_more"]
    assert client.get("/api/quota/value/history?offset=1&limit=1").json()["cycles"][0]["id"] == previous["id"]
    assert client.get("/api/quota/value/history?limit=0").status_code == 400
    assert client.get("/api/quota/value/history?price_mode=bad").status_code == 400

    app.state.pricing.set_override("gpt-5.6-sol", {
        "input": Decimal(100), "cached_input": Decimal(10), "cache_write": None,
        "output": Decimal(200), "api_fast_multiplier": Decimal(2),
    })
    frozen = client.get("/api/quota/value/history?price_mode=current").json()["cycles"][1]
    assert frozen["total"]["api_usd_known"] == previous["total"]["api_usd_known"]

    # Reopening the application retains observations and stable cycle IDs.
    restored = create_app(settings)
    restored.state.quota._fetch = fetch
    restored_client = TestClient(restored)
    state["now"] = datetime.fromisoformat("2026-09-20T17:00:00+00:00")
    restored_client.get("/api/quota")
    old = restored_client.get(f"/api/quota/value/history/{previous['id']}").json()
    assert old["observations"] == details["observations"]


def test_failed_reads_use_labelled_archive_and_account_changes_isolate_history(history_app):
    _, client, state, _, _ = history_app
    client.get("/api/quota")
    first_id = client.get("/api/quota/value/history").json()["cycles"][0]["id"]
    client.get("/api/quota")
    assert client.get("/api/quota/value/history").json()["cycles"][0]["observation_count"] == 1
    assert state["calls"] == 1

    state["error"] = True
    client.post("/api/quota/refresh")
    offline = client.get("/api/quota/value/history").json()
    assert offline["history_mode"] == "offline"
    assert offline["history_label"] == "上次保存的账号"
    assert offline["cycles"][0]["id"] == first_id
    assert not offline["cycles"][0]["is_current"]
    assert offline["cycles"][0]["observation_count"] == 1
    assert client.get("/api/quota/value/history?include_current=false").json() == offline
    assert client.get(f"/api/quota/value/history/{first_id}").status_code == 200
    state["error"] = False
    state["reading"] = reading(identity="account-b")
    client.post("/api/quota/refresh")
    second = client.get("/api/quota/value/history").json()
    assert second["total"] == 1 and second["cycles"][0]["id"] != first_id
    assert client.get(f"/api/quota/value/history/{first_id}").status_code == 404

    state["reading"] = reading(identity=None)
    result = client.post("/api/quota/refresh").json()
    assert result["status"] == "ready" and result["value_history_status"] == "identity_unavailable"
    assert client.get("/api/quota/value/history").json()["cycles"] == []
    state["reading"] = reading()
    client.post("/api/quota/refresh")
    assert client.get(f"/api/quota/value/history/{first_id}").status_code == 200


def test_storage_failure_preserves_live_quota_and_has_safe_history_errors(history_app, monkeypatch):
    app, client, _, _, _ = history_app

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("private database error")

    monkeypatch.setattr(app.state.quota.value_history, "observe", fail)
    result = client.get("/api/quota").json()
    assert result["status"] == "ready" and result["value_history_status"] == "error"
    assert result["windows"][0]["used_percent"] == 25
    monkeypatch.setattr(app.state.quota.value_history, "records", fail)
    failed = client.get("/api/quota/value/history")
    assert failed.status_code == 503 and "private" not in failed.text
    monkeypatch.setattr(app.state.quota.value_history, "observations", fail)
    assert client.get("/api/quota/value/history/1").status_code == 503
