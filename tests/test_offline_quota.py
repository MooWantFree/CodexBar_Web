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
from codex_token_report.quota_history import account_key


@pytest.fixture
def saved_app(tmp_path, monkeypatch):
    settings = Settings(codex_home=tmp_path / "codex", data_dir=tmp_path / "data",
                        scan_interval_minutes=0)
    app = create_app(settings)
    observed = datetime.fromisoformat("2026-10-02T04:00:00+00:00")

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return observed.astimezone(tz or UTC)

    monkeypatch.setattr("codex_token_report.quota.datetime", Clock)
    reading = {
        "status": "ready", "plan_type": "pro", "_account_key": "account-a",
        "windows": [{"limit_id": "codex", "limit_name": "Codex", "slot": "primary",
                     "used_percent": 20, "remaining_percent": 80, "window_minutes": 300,
                     "resets_at": observed.timestamp() + 3600}],
    }
    event = {
        "event_id": "saved-request", "session_id": "saved-session", "source_file": "gone.jsonl",
        "source_kind": "token_usage_record", "timestamp_utc": "2026-10-02T02:00:00+00:00",
        "local_date": "2026-10-02", "model": "gpt-5.6-sol", "pricing_model": "gpt-5.6-sol",
        "input_tokens": 1000, "cached_input_tokens": 0, "cache_write_input_tokens": 0,
        "output_tokens": 100, "reasoning_output_tokens": 0, "total_tokens": 1100,
        "service_tier": "standard", "tier_source": "test", "turn_id": None, "response_id": None,
    }
    app.state.database.replace_file_events(
        source_file="gone.jsonl", events=[event], mtime_ns=1, size_bytes=1,
        parse_errors=0, scanned_at=observed.isoformat(),
    )
    monkeypatch.setattr(app.state.quota, "_fetch", lambda: deepcopy(reading))
    client = TestClient(app)
    client.get("/api/quota")
    return app, client, settings, reading, event


def unavailable():
    raise QuotaError("读取暂时失败", code="timeout")


def test_offline_restart_restores_history_and_frozen_dollars(saved_app, monkeypatch):
    app, client, settings, _, event = saved_app
    before = client.get("/api/quota/value").json()
    cycle = client.get("/api/quota/value/history").json()["cycles"][0]
    resets = client.get("/api/quota").json()["reset_records"]
    assert before["windows"][0]["usd_per_percent"] > 0
    app.state.pricing.set_override("gpt-5.6-sol", {
        "input": Decimal(100), "cached_input": Decimal(10), "cache_write": None,
        "output": Decimal(200), "api_fast_multiplier": Decimal(2),
    })
    # New usage and prices must never be combined with an old quota percentage.
    later = {**event, "event_id": "late-discovered-request", "input_tokens": 900000,
             "total_tokens": 900100, "timestamp_utc": "2026-10-02T03:00:00+00:00"}
    app.state.database.replace_file_events(
        source_file="gone.jsonl", events=[event, later], mtime_ns=2, size_bytes=2,
        parse_errors=0, scanned_at=before["fetched_at"],
    )
    restored = create_app(settings)
    monkeypatch.setattr(restored.state.quota, "_fetch", unavailable)
    restarted = TestClient(restored)
    offline = restarted.get("/api/quota").json()
    assert offline["status"] == "unavailable" and offline["windows"] == []
    assert offline["identity_status"] == "unavailable"
    assert offline["history_mode"] == "offline"
    assert offline["history_label"] == "上次保存的账号"
    assert offline["history_fetched_at"] == before["fetched_at"]
    assert offline["reset_records"] == resets
    frozen = restarted.get("/api/quota/value").json()
    assert frozen["saved"] and frozen["history_mode"] == "offline"
    assert frozen["fetched_at"] == before["fetched_at"]
    assert frozen["windows"][0]["total"] == before["windows"][0]["total"]
    assert frozen["windows"][0]["usd_per_percent"] == before["windows"][0]["usd_per_percent"]
    history = restarted.get("/api/quota/value/history").json()
    assert history["cycles"][0]["id"] == cycle["id"]
    assert not history["cycles"][0]["is_current"]
    assert history["cycles"][0]["observation_count"] == 1
    assert restarted.get(f"/api/quota/value/history/{cycle['id']}").status_code == 200
    assert "account-a" not in json.dumps(offline) + json.dumps(history)


def test_verified_identity_keeps_own_history_on_rate_limit_failure(saved_app, monkeypatch):
    app, client, _, _, _ = saved_app
    resets = client.get("/api/quota").json()["reset_records"]
    monkeypatch.setattr(app.state.quota, "_fetch", lambda: {
        "status": "unavailable", "message": "网络不可用", "windows": [],
        "_account_key": "account-a", "plan_type": "pro",
    })
    failed = client.post("/api/quota/refresh").json()
    assert failed["identity_status"] == "verified" and failed["history_mode"] == "verified"
    assert failed["reset_records"] == resets and failed["reset_history_status"] == "available"
    assert client.get("/api/quota/value/history").json()["total"] == 1


def test_known_new_account_never_falls_back_to_previous_account(saved_app, monkeypatch):
    app, client, _, _, _ = saved_app
    old_id = client.get("/api/quota/value/history").json()["cycles"][0]["id"]
    monkeypatch.setattr(app.state.quota, "_fetch", lambda: {
        "status": "unavailable", "message": "账号 B 的额度不可用", "windows": [],
        "_account_key": "account-b", "plan_type": "pro",
    })
    result = client.post("/api/quota/refresh").json()
    assert result["history_mode"] == "verified" and result["reset_records"] == []
    assert client.get("/api/quota/value/history").json()["total"] == 0
    assert client.get(f"/api/quota/value/history/{old_id}").status_code == 404
    assert client.get("/api/quota/value").json()["windows"] == []


def test_offline_archive_is_scoped_to_log_directory(saved_app, monkeypatch):
    _, _, settings, _, _ = saved_app
    other = create_app(Settings(codex_home=settings.codex_home / "different",
                                data_dir=settings.data_dir, scan_interval_minutes=0))
    monkeypatch.setattr(other.state.quota, "_fetch", unavailable)
    client = TestClient(other)
    result = client.get("/api/quota").json()
    assert result["history_mode"] == "unavailable"
    assert result["reset_records"] == []
    assert client.get("/api/quota/value/history").json()["cycles"] == []


def test_all_public_quota_reads_are_saved_even_without_valued_cycle(saved_app, monkeypatch):
    app, client, _, reading, _ = saved_app
    zero = deepcopy(reading)
    zero["windows"][0]["used_percent"] = 0
    zero["windows"][0]["remaining_percent"] = 100
    # A new read timestamp is required; duplicate reads at an identical time are idempotent.
    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromisoformat("2026-10-02T04:01:00+00:00").astimezone(tz or UTC)
    monkeypatch.setattr("codex_token_report.quota.datetime", Later)
    monkeypatch.setattr(app.state.quota, "_fetch", lambda: deepcopy(zero))
    client.post("/api/quota/refresh")
    client.post("/api/quota/refresh")
    with app.state.database.connect() as connection:
        rows = connection.execute("SELECT payload_json FROM quota_account_reads ORDER BY id").fetchall()
    assert len(rows) == 2
    assert json.loads(rows[1]["payload_json"])["windows"][0]["used_percent"] == 0
    assert all("_account_key" not in row["payload_json"] for row in rows)


def test_cli_refreshes_authentication_once_and_preserves_identified_account(tmp_path, monkeypatch):
    calls = []
    account = {"type": "chatgpt", "email": "private@example.com", "planType": "pro"}

    class RPC:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def request(self, method, params=None):
            calls.append((method, params))
            if method == "account/read":
                return {"account": account}
            if sum(method == "account/rateLimits/read" for method, _ in calls) == 1:
                raise QuotaError("需要重新认证", code="authentication")
            raise QuotaError("网络错误", code="rpc_error")

    monkeypatch.setattr("codex_token_report.quota.CodexRPC", lambda _: RPC())
    app = create_app(Settings(codex_home=tmp_path, data_dir=tmp_path / "data"))
    result = app.state.quota.read()
    assert result["status"] == "unavailable" and result["history_mode"] == "verified"
    assert calls == [("account/read", {"refreshToken": False}),
                     ("account/rateLimits/read", None), ("account/read", {"refreshToken": True}),
                     ("account/rateLimits/read", None)]
    assert app.state.quota._active_account_key == account_key(account, tmp_path)
    assert "private@example.com" not in json.dumps(result)


def test_one_refresh_budget_is_shared_by_account_and_quota_requests(tmp_path, monkeypatch):
    calls = []

    class RPC:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def request(self, method, params=None):
            calls.append((method, params))
            if method == "account/read" and params.get("refreshToken"):
                return {"account": {"type": "chatgpt", "email": "private@example.com"}}
            raise QuotaError("需要认证", code="authentication")

    monkeypatch.setattr("codex_token_report.quota.CodexRPC", lambda _: RPC())
    app = create_app(Settings(codex_home=tmp_path, data_dir=tmp_path / "data"))
    result = app.state.quota.read()
    assert result["history_mode"] == "verified" and result["status"] == "unavailable"
    assert calls == [("account/read", {"refreshToken": False}),
                     ("account/read", {"refreshToken": True}), ("account/rateLimits/read", None)]


def test_archive_write_failure_preserves_live_quota_and_saved_history(saved_app, monkeypatch):
    app, client, _, _, _ = saved_app
    existing = client.get("/api/quota/value/history").json()["cycles"]

    def fail(*_):
        raise sqlite3.OperationalError("private storage diagnostic")

    monkeypatch.setattr(app.state.quota.archive, "save", fail)
    result = client.post("/api/quota/refresh").json()
    assert result["status"] == "ready" and result["archive_status"] == "error"
    assert result["windows"][0]["used_percent"] == 20
    assert client.get("/api/quota/value/history").json()["cycles"] == existing
    assert "private storage diagnostic" not in json.dumps(result)


def test_legacy_history_without_directory_index_remains_visible_offline(saved_app, monkeypatch):
    app, client, settings, _, _ = saved_app
    before = client.get("/api/quota/value/history").json()["cycles"][0]
    # Recreate the old-version schema state without discarding any archived reads.
    with app.state.database.connect() as connection:
        connection.execute("ALTER TABLE quota_account_reads RENAME TO test_newer_quota_reads")
    restored = create_app(settings)
    monkeypatch.setattr(restored.state.quota, "_fetch", unavailable)
    restarted = TestClient(restored)
    result = restarted.get("/api/quota").json()
    assert result["history_mode"] == "offline" and result["identity_status"] == "unavailable"
    assert result["history_directory_verified"] is False
    assert "旧版本" in result["history_label"] and "归属未确认" in result["history_label"]
    history = restarted.get("/api/quota/value/history").json()
    assert history["cycles"][0]["id"] == before["id"]
    assert history["cycles"][0]["total"] == before["total"]
    assert not history["cycles"][0]["is_current"]
    assert restarted.get("/api/quota/value").json()["saved"]
