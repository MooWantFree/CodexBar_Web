import pytest

from codex_token_report.pricing import PriceCatalog
from codex_token_report.reports import (
    build_project_daily_report,
    build_projects_report,
    build_report,
)


def test_report_splits_fast_calls_and_surcharge() -> None:
    event = {
        "local_date": "2026-09-20",
        "model": "gpt-5.6-terra",
        "pricing_model": "gpt-5.6-terra",
        "service_tier": "priority",
        "input_tokens": 100,
        "cached_input_tokens": 20,
        "cache_write_input_tokens": 0,
        "output_tokens": 10,
        "reasoning_output_tokens": 2,
    }

    report = build_report(
        [event], PriceCatalog.load_default(), start="2026-09-20", end="2026-09-20"
    )
    total = report["total"]

    assert total["fast_calls"] == 1
    assert total["standard_calls"] == 0
    assert total["unknown_tier_calls"] == 0
    assert total["tier_coverage_percent"] == 100
    assert total["standard_api_usd_known"] == pytest.approx(0.000284)
    assert total["api_usd_known"] == pytest.approx(0.000568)
    assert total["fast_surcharge_usd"] == pytest.approx(0.000284)
    assert report["daily"][0]["models"][0]["model"] == "gpt-5.6-terra"
    assert sum(item["total_tokens"] for item in report["daily"][0]["models"]) == total[
        "total_tokens"
    ]


def test_fast_missing_multiplier_is_counted_as_unknown_not_free():
    catalog = PriceCatalog.load_default()
    catalog.models["gpt-6.1-sol"]["api_fast_multiplier"] = None
    event = {"local_date": "2026-10-01", "model": "gpt-6.1-sol",
             "service_tier": "priority", "input_tokens": 100, "cached_input_tokens": 20,
             "cache_write_input_tokens": 0, "output_tokens": 10, "reasoning_output_tokens": 0}
    total = build_report([event], catalog, start=None, end=None)["total"]
    assert total["fast_calls"] == 1
    assert total["unknown_fast_price_calls"] == 1
    assert total["unknown_price_calls"] == 1
    assert total["standard_api_usd_known"] == pytest.approx(0.000262)


def test_project_reports_match_total_and_preserve_model_breakdown() -> None:
    first = {
        "local_date": "2026-09-20",
        "model": "gpt-5.6-sol",
        "pricing_model": "gpt-5.6-sol",
        "project_key": "e:/code/alpha",
        "project_path": "E:\\Code\\alpha",
        "service_tier": "standard",
        "input_tokens": 100,
        "cached_input_tokens": 40,
        "cache_write_input_tokens": 0,
        "output_tokens": 10,
        "reasoning_output_tokens": 2,
    }
    second = {
        **first,
        "local_date": "2026-09-21",
        "model": "gpt-6-astra",
        "pricing_model": "gpt-6-astra",
        "input_tokens": 200,
        "output_tokens": 20,
    }
    catalog = PriceCatalog.load_default()

    projects = build_projects_report(
        [first, second], catalog, start="2026-09-20", end="2026-09-21"
    )
    daily = build_project_daily_report(
        [first, second],
        catalog,
        project_key="e:/code/alpha",
        project_path="E:\\Code\\alpha",
        start="2026-09-20",
        end="2026-09-21",
    )

    assert projects["projects"][0]["display_name"] == "alpha"
    assert projects["projects"][0]["total_tokens"] == 330
    assert len(projects["projects"][0]["models"]) == 2
    assert sum(row["total_tokens"] for row in daily["daily"]) == 330
    assert daily["project"]["display_name"] == "alpha"
