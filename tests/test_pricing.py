from decimal import Decimal

from codex_token_report.pricing import PriceCatalog


def test_sol_price_uses_cached_as_subset_of_input() -> None:
    catalog = PriceCatalog.load_default()
    result = catalog.calculate(
        model="gpt-5.6-sol",
        input_tokens=1_000_000,
        cached_input_tokens=900_000,
        cache_write_input_tokens=0,
        output_tokens=10_000,
    )
    assert result.api_usd == Decimal("1.82")
    assert result.codex_credits == Decimal(24)
    assert result.is_long_context is True
    assert result.api_tier_multiplier == Decimal(1)


def test_fast_uses_distinct_api_and_credit_multipliers() -> None:
    catalog = PriceCatalog.load_default()
    result = catalog.calculate(
        model="gpt-5.6-sol",
        input_tokens=1_000_000,
        cached_input_tokens=900_000,
        cache_write_input_tokens=0,
        output_tokens=10_000,
        service_tier="priority",
    )
    assert result.standard_api_usd == Decimal("1.82")
    assert result.api_usd == Decimal("3.640")
    assert result.standard_codex_credits == Decimal(24)
    assert result.codex_credits == Decimal("60.0")
    assert result.api_tier_multiplier == Decimal("2.0")
    assert result.credit_tier_multiplier == Decimal("2.5")
    assert result.tier_known is True


def test_unknown_tier_uses_standard_floor_but_is_marked_unknown() -> None:
    catalog = PriceCatalog.load_default()
    standard = catalog.calculate(
        model="gpt-5.6-terra",
        input_tokens=100,
        cached_input_tokens=20,
        cache_write_input_tokens=0,
        output_tokens=10,
    )
    unknown = catalog.calculate(
        model="gpt-5.6-terra",
        input_tokens=100,
        cached_input_tokens=20,
        cache_write_input_tokens=0,
        output_tokens=10,
        service_tier="unknown",
    )
    assert unknown.api_usd == standard.api_usd
    assert unknown.tier_known is False


def test_unknown_model_is_not_silently_priced() -> None:
    catalog = PriceCatalog.load_default()
    result = catalog.calculate(
        model="codex-auto-review",
        input_tokens=100,
        cached_input_tokens=0,
        cache_write_input_tokens=0,
        output_tokens=10,
    )
    assert result.api_usd is None
    assert result.codex_credits is None
    assert result.model_known is False


def test_legacy_snapshot_repairs_fast_default_without_changing_standard_or_overrides():
    payload = PriceCatalog.load_default().payload
    payload.pop("fast_pricing_version")
    payload["snapshot_source"] = "openai_docs"
    payload["models"]["gpt-6.1-sol"]["api_fast_multiplier"] = 1
    args = {"model": "gpt-6.1-sol", "input_tokens": 100, "cached_input_tokens": 20,
            "cache_write_input_tokens": 0, "output_tokens": 10, "service_tier": "priority"}
    result = PriceCatalog(payload).calculate(**args)
    assert result.api_usd == result.standard_api_usd * 2
    payload["snapshot_overrides"] = ["gpt-6.1-sol"]
    manual = PriceCatalog(payload).calculate(**args)
    assert manual.api_usd == manual.standard_api_usd


def test_unknown_fast_multiplier_preserves_standard_estimate():
    payload = PriceCatalog.load_default().payload
    payload["models"]["gpt-6.1-sol"]["api_fast_multiplier"] = None
    result = PriceCatalog(payload).calculate(
        model="gpt-6.1-sol", input_tokens=100, cached_input_tokens=20,
        cache_write_input_tokens=0, output_tokens=10, service_tier="priority",
    )
    assert result.api_usd is None
    assert result.standard_api_usd == Decimal("0.000262")
    assert result.tier_known


def test_model_specific_long_context_prices_apply_at_its_threshold():
    payload = PriceCatalog.load_default().payload
    entry = payload["models"]["gpt-6.1-sol"]
    entry.update(context_threshold=200000, api_usd_long_context={
        "input": 8, "cached_input": 0.8, "cache_write": 10, "output": 60,
    })
    result = PriceCatalog(payload).calculate(
        model="gpt-6.1-sol", input_tokens=200001, cached_input_tokens=100000,
        cache_write_input_tokens=0, output_tokens=1000, service_tier="priority",
    )
    assert result.api_usd == Decimal("1.880016")
    assert result.is_long_context
