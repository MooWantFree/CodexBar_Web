import copy
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from codex_token_report.db import Database
from codex_token_report.models_dev import parse_model
from codex_token_report.pricing_store import PricingStore


def _catalog():
    return {"openai": {"models": {
        "gpt-5.6-sol": {"name": "GPT-5.6 Sol", "cost": {
            "input": 8, "cache_read": 0.8, "cache_write": 10, "output": 40,
            "tiers": [{"input": 16, "cache_read": 1.6, "cache_write": 20, "output": 60,
                       "tier": {"type": "context", "size": 272000}}],
            "context_over_200k": {"input": 16, "output": 60},
        }},
        "gpt-6.1-sol": {"cost": {"input": 2, "output": 10, "cache_read": 0.1, "cache_write": 2.5}},
        "gpt-5.4": {"cost": {"input": 2.5, "cache_read": 0.25, "output": 15}},
    }}}


def _discover(database, model):
    with database.connect() as connection:
        connection.execute("""
            INSERT INTO usage_events(event_id, source_file, source_kind, timestamp_utc,
                                     local_date, model, input_tokens, cached_input_tokens,
                                     cache_write_input_tokens, output_tokens,
                                     reasoning_output_tokens, total_tokens)
            VALUES (?, 'fixture', 'token_usage_record', '2026-10-01T00:00:00+00:00',
                    '2026-10-01', ?, 10, 0, 0, 1, 0, 11)
        """, (model, model))


def test_catalog_is_provider_scoped_and_prefers_explicit_threshold():
    parsed = parse_model("gpt-5.6-sol", _catalog())
    assert parsed["api_usd"] == {"input": 8, "cached_input": 0.8, "cache_write": 10, "output": 40}
    assert parsed["context_threshold"] == 272000
    assert parsed["api_usd_long_context"]["output"] == 60
    with pytest.raises(ValueError, match="未提供"):
        parse_model("gpt-5.6-sol", {"other": _catalog()["openai"]})


@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf"), True, "bad"])
def test_invalid_rates_are_rejected(bad):
    data = _catalog()
    data["openai"]["models"]["gpt-5.6-sol"]["cost"]["input"] = bad
    with pytest.raises((ValueError, TypeError)):
        parse_model("gpt-5.6-sol", data)


def test_missing_cache_prices_are_unknown_and_zero_is_valid():
    parsed = parse_model("gpt-5.4", _catalog())
    assert parsed["api_usd"]["cache_write"] is None
    data = {"openai": {"models": {"test": {"cost": {"input": 0, "output": 0}}}}}
    assert parse_model("test", data)["api_usd"]["input"] == 0
    assert parse_model("test", data)["api_usd"]["cached_input"] is None


def test_refresh_fetches_once_preserves_overrides_and_fallbacks(tmp_path: Path):
    calls = []
    def fetch():
        calls.append(True)
        return _catalog()
    store = PricingStore(database=Database(tmp_path / "usage.sqlite3"), fetch_models=fetch)
    store.set_override("gpt-5.6-sol", {
        "input": Decimal(7), "cached_input": Decimal("0.7"), "cache_write": None,
        "output": Decimal(35), "api_fast_multiplier": Decimal(3),
    })
    result = store.refresh()
    assert len(calls) == 1
    assert "gpt-5.6-sol" in result["updated_models"]
    rows = {m["model"]: m for m in store.public_state()["models"]}
    assert rows["gpt-5.6-sol"]["official"]["input"] == 8
    assert rows["gpt-5.6-sol"]["effective"]["input"] == 7
    assert rows["gpt-5.6-sol"]["effective"]["api_fast_multiplier"] == 3
    assert rows["gpt-6.1-sol"]["effective"]["api_fast_multiplier"] == 2
    assert rows["gpt-5.5"]["official"]["input"] == 5
    assert rows["gpt-5.4"]["official"]["cache_write"] == 3.125
    assert store.public_state()["source"] == "models_dev"
    before = copy.deepcopy(store.catalog().payload)
    def offline():
        raise ValueError("offline")
    store._fetch_models_override = offline
    assert store.refresh()["failed_models"] == {"models.dev": "offline"}
    assert store.catalog().payload == before


def test_startup_cache_survives_restart_for_24_hours(tmp_path):
    path = tmp_path / "usage.sqlite3"
    calls = []
    def fetch():
        calls.append(True)
        return _catalog()
    store = PricingStore(database=Database(path), fetch_models=fetch)
    store.refresh()
    fetched = datetime.fromisoformat(store.public_state()["fetched_at"])
    reopened = PricingStore(database=Database(path), fetch_models=fetch)
    assert reopened.refresh_on_startup("Asia/Taipei", now=fetched + timedelta(hours=23)) is None
    assert len(calls) == 1
    assert reopened.refresh_on_startup("Asia/Taipei", now=fetched + timedelta(hours=25))["updated_models"]
    assert len(calls) == 2


def test_failed_startup_can_be_retried_manually(tmp_path):
    def offline():
        raise ValueError("offline")
    store = PricingStore(database=Database(tmp_path / "usage.sqlite3"), fetch_models=offline)
    before = store.catalog().payload
    now = datetime.fromisoformat("2026-10-01T00:00:00+00:00")
    assert store.refresh_on_startup("Asia/Taipei", now=now)["failed_models"]
    assert store.catalog().payload == before
    assert store.refresh_on_startup("Asia/Taipei", now=now) is None
    store._fetch_models_override = _catalog
    assert store.refresh()["updated_models"]


def test_failed_automatic_refresh_retries_after_15_minutes_not_next_day(tmp_path):
    calls = []
    def offline():
        calls.append(True)
        raise ValueError("offline")
    store = PricingStore(database=Database(tmp_path / "usage.sqlite3"), fetch_models=offline)
    now = datetime.fromisoformat("2026-10-01T00:00:00+00:00")
    assert store.refresh_on_startup("Asia/Taipei", now=now)["failed_models"]
    assert store.refresh_on_startup("Asia/Taipei", now=now + timedelta(minutes=14)) is None
    assert store.refresh_on_startup("Asia/Taipei", now=now + timedelta(minutes=16))["failed_models"]
    assert len(calls) == 2


def test_unused_model_is_available_from_complete_cache_without_network(tmp_path):
    data = _catalog()
    data["openai"]["models"]["new-model"] = {"cost": {"input": 3, "output": 9}}
    database = Database(tmp_path / "usage.sqlite3")
    store = PricingStore(database=database, fetch_models=lambda: data)
    store.refresh()
    assert "new-model" not in store.catalog().models
    _discover(database, "new-model")
    reopened = PricingStore(database=Database(database.path))
    assert reopened.catalog().models["new-model"]["api_usd"]["input"] == 3
    fetched = datetime.fromisoformat(store.public_state()["fetched_at"])
    assert reopened.refresh_on_startup("Asia/Taipei", now=fetched + timedelta(hours=1)) is None


def test_missing_model_refreshes_before_24_hours_subject_to_retry_cooldown(tmp_path):
    database = Database(tmp_path / "usage.sqlite3")
    data = _catalog()
    store = PricingStore(database=database, fetch_models=lambda: data)
    now = datetime.fromisoformat("2026-10-01T00:00:00+00:00")
    store.refresh(now=now)
    _discover(database, "new-model")
    assert store.refresh_on_startup("Asia/Taipei", now=now + timedelta(minutes=14)) is None
    data["openai"]["models"]["new-model"] = {"cost": {"input": 3, "output": 9}}
    result = store.refresh_on_startup("Asia/Taipei", now=now + timedelta(minutes=16))
    assert "new-model" in result["updated_models"]
    assert store.catalog().models["new-model"]["api_usd"]["input"] == 3


def test_removed_models_remain_in_cache_and_empty_responses_do_not_replace_it(tmp_path):
    data = _catalog()
    store = PricingStore(database=Database(tmp_path / "usage.sqlite3"), fetch_models=lambda: data)
    store.refresh()
    data = {"openai": {"models": {"gpt-6.1-sol": {
        "cost": {"input": 4, "output": 20, "cache_read": 0.2},
    }}}}
    store.refresh()
    assert store.catalog().models["gpt-5.6-sol"]["api_usd"]["input"] == 8
    before = copy.deepcopy(store.catalog().payload)
    data = {"openai": {"models": {}}}
    assert store.refresh()["failed_models"]
    assert store.catalog().payload == before


def test_missing_cache_rate_uses_builtin_instead_of_previous_remote_price(tmp_path):
    data = _catalog()
    data["openai"]["models"]["gpt-5.4"]["cost"]["cache_write"] = 99
    store = PricingStore(database=Database(tmp_path / "usage.sqlite3"), fetch_models=lambda: data)
    store.refresh()
    del data["openai"]["models"]["gpt-5.4"]["cost"]["cache_write"]
    store.refresh()
    assert store.catalog().models["gpt-5.4"]["api_usd"]["cache_write"] == 3.125


def test_multiple_instances_share_retry_cooldown(tmp_path):
    calls = []
    def fetch():
        calls.append(True)
        return _catalog()
    path = tmp_path / "usage.sqlite3"
    first = PricingStore(database=Database(path), fetch_models=fetch)
    second = PricingStore(database=Database(path), fetch_models=fetch)
    now = datetime.fromisoformat("2026-10-01T00:00:00+00:00")
    assert first.refresh_on_startup("Asia/Taipei", now=now)["updated_models"]
    assert second.refresh_on_startup("Asia/Taipei", now=now) is None
    assert len(calls) == 1


def test_override_can_leave_fast_multiplier_unknown(tmp_path):
    store = PricingStore(database=Database(tmp_path / "usage.sqlite3"))
    store.set_override("new-model", {
        "input": Decimal(1), "cached_input": Decimal(0), "cache_write": None,
        "output": Decimal(2), "api_fast_multiplier": None,
    })
    assert store.public_state()["models"][-1]["effective"]["api_fast_multiplier"] is None
    assert store.catalog().calculate(model="new-model", input_tokens=10, cached_input_tokens=0,
                                     cache_write_input_tokens=0, output_tokens=2,
                                     service_tier="priority").api_usd is None
