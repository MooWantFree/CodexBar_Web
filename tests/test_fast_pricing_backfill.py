import copy
import json
from decimal import Decimal

import pytest

from codex_token_report.db import Database
from codex_token_report.models_dev import CATALOG_CACHE_KEY
from codex_token_report.pricing import FAST_PRICING_VERSION, PriceCatalog
from codex_token_report.pricing_store import PricingStore


def _snapshot(model="gpt-6-sol", *, version=2):
    return {
        "as_of": "2026-09-01",
        "currency": "USD",
        "basis_tokens": 1_000_000,
        "snapshot_source": "models_dev",
        "snapshot_overrides": [],
        "fast_pricing_version": version,
        "context": {
            "long_context_threshold": 272000,
            "long_input_multiplier": 2,
            "long_cached_input_multiplier": 2,
            "long_cache_write_multiplier": 2,
            "long_output_multiplier": 1.5,
        },
        "models": {
            model: {
                "api_usd": {"input": 2, "cached_input": 0.2, "cache_write": 2.5, "output": 10},
                "api_usd_long_context": {
                    "input": 4, "cached_input": 0.4, "cache_write": 5, "output": 15,
                },
                "context_threshold": 272000,
                "api_fast_multiplier": None,
                "codex_credits": None,
                "credit_fast_multiplier": None,
            },
        },
    }


def _calculate(catalog, *, model="gpt-6-sol", tier="priority", long_context=False):
    return catalog.calculate(
        model=model,
        input_tokens=300000 if long_context else 1000,
        cached_input_tokens=10000 if long_context else 100,
        cache_write_input_tokens=5000 if long_context else 50,
        output_tokens=1000 if long_context else 20,
        service_tier=tier,
    )


@pytest.mark.parametrize("long_context,expected_standard", [
    (False, Decimal("0.002045")),
    (True, Decimal("1.184")),
])
def test_gpt_6_sol_fast_uses_twice_standard_including_long_context(long_context, expected_standard):
    catalog = PriceCatalog(_snapshot())
    standard = _calculate(catalog, tier="standard", long_context=long_context)
    fast = _calculate(catalog, tier="fast", long_context=long_context)

    assert standard.api_usd == expected_standard
    assert fast.standard_api_usd == standard.api_usd
    assert fast.api_tier_multiplier == Decimal(2)
    assert fast.api_usd == standard.api_usd * 2
    assert fast.is_long_context is long_context


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("missing", [False, True])
def test_older_snapshots_backfill_only_missing_fast_and_preserve_payload(version, missing):
    payload = _snapshot(version=version)
    if missing:
        del payload["models"]["gpt-6-sol"]["api_fast_multiplier"]
    original = copy.deepcopy(payload)

    catalog = PriceCatalog(payload)

    assert catalog.models["gpt-6-sol"]["api_fast_multiplier"] == 2
    assert catalog.as_of == "2026-09-01"
    assert catalog.models["gpt-6-sol"]["api_usd"] == original["models"]["gpt-6-sol"]["api_usd"]
    assert catalog.models["gpt-6-sol"]["api_usd_long_context"] == original["models"]["gpt-6-sol"]["api_usd_long_context"]
    assert payload == original


@pytest.mark.parametrize("missing", [False, True])
def test_unknown_model_fast_remains_unpriced(missing):
    payload = _snapshot("future-model")
    if missing:
        del payload["models"]["future-model"]["api_fast_multiplier"]
    catalog = PriceCatalog(payload)

    fast = _calculate(catalog, model="future-model")
    assert fast.api_usd is None
    assert fast.api_tier_multiplier is None
    assert fast.standard_api_usd == Decimal("0.002045")
    assert _calculate(catalog, model="future-model", tier="standard").api_usd == fast.standard_api_usd


@pytest.mark.parametrize("multiplier", [None, 3])
def test_snapshot_manual_unknown_or_numeric_fast_override_is_preserved(multiplier):
    payload = _snapshot()
    payload["snapshot_overrides"] = ["gpt-6-sol"]
    payload["models"]["gpt-6-sol"]["api_fast_multiplier"] = multiplier

    catalog = PriceCatalog(payload)

    assert catalog.models["gpt-6-sol"]["api_fast_multiplier"] == multiplier
    fast = _calculate(catalog)
    if multiplier is None:
        assert fast.api_usd is None
    else:
        assert fast.api_usd == fast.standard_api_usd * multiplier


@pytest.mark.parametrize("multiplier", [1, 2.5, 3])
def test_version_2_saved_numeric_fast_multiplier_is_not_replaced(multiplier):
    payload = _snapshot()
    payload["models"]["gpt-6-sol"]["api_fast_multiplier"] = multiplier

    catalog = PriceCatalog(payload)

    assert catalog.models["gpt-6-sol"]["api_fast_multiplier"] == multiplier
    assert _calculate(catalog).api_tier_multiplier == Decimal(str(multiplier))


@pytest.mark.parametrize("manual_override", [False, True])
def test_unversioned_snapshot_keeps_legacy_implicit_1x_repair(manual_override):
    payload = _snapshot()
    del payload["fast_pricing_version"]
    payload["models"]["gpt-6-sol"]["api_fast_multiplier"] = 1
    if manual_override:
        payload["snapshot_overrides"] = ["gpt-6-sol"]

    catalog = PriceCatalog(payload)

    assert catalog.models["gpt-6-sol"]["api_fast_multiplier"] == (1 if manual_override else 2)


def test_current_version_snapshot_unknown_fast_is_not_reinterpreted():
    catalog = PriceCatalog(_snapshot(version=FAST_PRICING_VERSION))
    assert catalog.models["gpt-6-sol"]["api_fast_multiplier"] is None
    assert _calculate(catalog).api_usd is None


def test_gpt_6_luna_version_3_snapshot_receives_published_fast_multiplier():
    payload = _snapshot("gpt-6-luna", version=3)
    payload["models"]["gpt-6-luna"]["api_usd"] = {
        "input": 0.1, "cached_input": 0.01, "cache_write": 0.125, "output": 0.5,
    }
    catalog = PriceCatalog(payload)
    standard = _calculate(catalog, model="gpt-6-luna", tier="standard")
    fast = _calculate(catalog, model="gpt-6-luna", tier="fast")
    assert fast.api_tier_multiplier == Decimal(2)
    assert fast.api_usd == standard.api_usd * 2


def test_current_pricing_store_exposes_gpt_6_sol_fast_2x(tmp_path, monkeypatch):
    database = Database(tmp_path / "usage.sqlite3")
    monkeypatch.setattr(database, "distinct_models", lambda: ["gpt-6-sol"])
    remote = {"openai": {"models": {"gpt-6-sol": {
        "name": "GPT-6 Sol",
        "cost": {
            "input": 2, "cache_read": 0.2, "cache_write": 2.5, "output": 10,
            "tiers": [{"input": 4, "cache_read": 0.4, "cache_write": 5, "output": 15,
                       "tier": {"type": "context", "size": 272000}}],
        },
    }}}}
    store = PricingStore(database=database, fetch_models=lambda: remote)

    assert "gpt-6-sol" in store.refresh()["updated_models"]
    row = next(row for row in store.public_state()["models"] if row["model"] == "gpt-6-sol")
    assert row["source"] == "models_dev"
    assert row["override"] is None
    assert row["official"]["api_fast_multiplier"] == 2
    assert row["effective"] == {
        "input": 2, "cached_input": 0.2, "cache_write": 2.5, "output": 10,
        "api_fast_multiplier": 2,
    }
    assert store.catalog().payload["fast_pricing_version"] == FAST_PRICING_VERSION
    fast = _calculate(store.catalog(), long_context=True)
    assert fast.api_usd == Decimal("2.368")


@pytest.mark.parametrize("override_multiplier", [None, Decimal(3)])
def test_saved_models_dev_price_without_raw_cache_exposes_fast_and_preserves_override(
    tmp_path, monkeypatch, override_multiplier,
):
    database = Database(tmp_path / "usage.sqlite3")
    monkeypatch.setattr(database, "distinct_models", lambda: ["gpt-6-sol"])
    remote = {"openai": {"models": {"gpt-6-sol": {"cost": {
        "input": 2, "cache_read": 0.2, "cache_write": 2.5, "output": 10,
    }}}}}
    store = PricingStore(database=database, fetch_models=lambda: remote)
    assert "gpt-6-sol" in store.refresh()["updated_models"]

    saved = database.get_pricing_catalog()
    old_payload = json.loads(saved["payload_json"])
    old_payload["models"]["gpt-6-sol"]["api_fast_multiplier"] = None
    saved["payload_json"] = json.dumps(old_payload)
    get_metadata = database.get_metadata
    monkeypatch.setattr(database, "get_metadata", lambda key: (
        None if key == CATALOG_CACHE_KEY else get_metadata(key)
    ))
    monkeypatch.setattr(database, "get_pricing_catalog", lambda: copy.deepcopy(saved))

    row = next(row for row in store.public_state()["models"] if row["model"] == "gpt-6-sol")
    assert row["source"] == "models_dev"
    assert row["official"] == row["effective"] == {
        "input": 2, "cached_input": 0.2, "cache_write": 2.5, "output": 10,
        "api_fast_multiplier": 2,
    }
    assert store.catalog().as_of == old_payload["as_of"]

    store.set_override("gpt-6-sol", {
        "input": Decimal(7), "cached_input": Decimal("0.7"),
        "cache_write": Decimal(8), "output": Decimal(35),
        "api_fast_multiplier": override_multiplier,
    })
    row = next(row for row in store.public_state()["models"] if row["model"] == "gpt-6-sol")
    assert row["official"]["input"] == 2
    assert row["official"]["api_fast_multiplier"] == 2
    assert row["effective"]["input"] == 7
    assert row["effective"]["api_fast_multiplier"] == override_multiplier
    assert json.loads(database.get_pricing_catalog()["payload_json"]) == old_payload
