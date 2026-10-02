from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from codex_token_report.config import Settings
from codex_token_report.main import create_app


@pytest.fixture
def app(tmp_path, monkeypatch):
    application = create_app(Settings(
        codex_home=tmp_path, data_dir=tmp_path / "data", scan_interval_minutes=0,
    ))

    def unexpected_read(*args, **kwargs):
        pytest.fail("Quota value requests must reuse the last explicit quota read")

    monkeypatch.setattr(application.state.quota, "read", unexpected_read)
    return application


def test_menu_and_empty_snapshot_do_not_fetch_quota(app):
    client = TestClient(app)
    page = client.get("/quota-value")
    assert page.status_code == 200
    assert 'href="/quota-value" data-route="quota-value"' in page.text
    assert 'id="quotaValueWindows"' in page.text
    result = client.get("/api/quota/value").json()
    assert result["status"] == "unavailable"
    assert result["windows"] == []
    assert client.get("/api/quota/value?price_mode=invalid").status_code == 400


def test_cached_period_ignores_calendar_range_and_supports_price_modes(app):
    observed = "2026-10-02T04:00:00+00:00"
    app.state.quota.cached = {
        "status": "ready", "plan_type": "pro", "fetched_at": observed,
        "windows": [{
            "limit_id": "codex", "limit_name": "Codex", "slot": "primary",
            "used_percent": 20, "remaining_percent": 80, "window_minutes": 300,
            "resets_at": datetime(2026, 10, 2, 5, tzinfo=UTC).timestamp(),
        }],
    }
    timestamps = ["2026-10-01T23:59:59+00:00", "2026-10-02T00:00:00+00:00", observed]
    app.state.database.replace_file_events(
        source_file="quota-api.jsonl", mtime_ns=1, size_bytes=1, parse_errors=0,
        scanned_at=observed,
        events=[{
            "event_id": f"event-{index}", "source_file": "quota-api.jsonl",
            "source_kind": "token_usage_record", "timestamp_utc": timestamp,
            "local_date": "2026-10-02", "model": "gpt-5.6-sol",
            "input_tokens": 1000000, "cached_input_tokens": 0,
            "cache_write_input_tokens": 0, "output_tokens": 0,
            "reasoning_output_tokens": 0, "total_tokens": 1000000,
            "service_tier": "standard", "pricing_model": "gpt-5.6-sol",
            "turn_id": None, "response_id": None, "tier_source": "test",
            "project_key": None, "project_path": None,
            "workspace_root": None, "working_directory": None,
        } for index, timestamp in enumerate(timestamps)],
    )
    client = TestClient(app)
    saved = client.get("/api/quota/value", params={"start": "2000-01-01"}).json()
    assert saved["fetched_at"] == observed
    assert saved["price_mode"] == "snapshot"
    assert saved["windows"][0]["total"]["calls"] == 1
    original = saved["windows"][0]["total"]["api_usd_known"]
    app.state.pricing.set_override("gpt-5.6-sol", {
        "input": Decimal(8), "cached_input": Decimal(0), "cache_write": None,
        "output": Decimal(40), "api_fast_multiplier": Decimal(2),
    })
    current = client.get("/api/quota/value?price_mode=current").json()
    window = current["windows"][0]
    assert window["total"]["api_usd_known"] == 16  # Includes the long-context input multiplier.
    assert window["usd_per_percent"] == 0.8
    assert window["full_quota_usd"] == 80
    assert window["remaining_quota_usd"] == 64
    assert client.get("/api/quota/value").json()["windows"][0]["total"]["api_usd_known"] == original

    # A failed refresh clears the cache; the page must not reuse the old dollars.
    app.state.quota.cached = {"status": "error", "message": "读取失败", "windows": []}
    failed = client.get("/api/quota/value").json()
    assert failed["status"] == "error"
    assert failed["windows"] == []
