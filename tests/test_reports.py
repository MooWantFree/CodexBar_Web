import pytest

from codex_token_report.pricing import PriceCatalog
from codex_token_report.reports import (
    build_project_daily_report,
    build_projects_report,
    build_report,
    build_sessions_report,
    request_rows,
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


def session_label_event(key, **fields):
    return {
        "event_id": key, "session_id": "root-session", "timestamp_utc": "2026-10-01T01:00:00Z",
        "model": None, "project_key": None, "project_path": None,
        "input_tokens": 10, "cached_input_tokens": 0, "cache_write_input_tokens": 0,
        "output_tokens": 1, "reasoning_output_tokens": 0, "service_tier": "standard", **fields,
    }


def test_session_label_metadata_distinguishes_unknown_fallbacks_from_literal_names():
    events = [
        session_label_event("missing-labels"),
        session_label_event("literal-labels", model="未知模型", project_key="literal-project",
                            project_path="E:/Code/未知项目"),
        session_label_event("duplicate-literal", model="未知模型", project_key="literal-project",
                            project_path="E:/Code/未知项目"),
    ]
    row = build_sessions_report(events, PriceCatalog.load_default(), {})[0]
    # Retain the former display-string arrays even when two distinct identities
    # have the same label. The additive entries give the UI enough provenance
    # to translate only an application's generated fallback.
    assert row["models"] == ["未知模型"]
    assert row["projects"] == ["未知项目"]
    assert row["model_entries"] == [
        {"key": "unknown", "display_name": "未知模型"},
        {"key": "未知模型", "display_name": "未知模型"},
    ]
    assert row["project_entries"] == [
        {"key": "literal-project", "display_name": "未知项目", "path": "E:/Code/未知项目"},
        {"key": "unknown", "display_name": "未知项目", "path": None},
    ]
    assert row["members"][0]["model_entries"] == row["model_entries"]
    assert row["members"][0]["project_entries"] == row["project_entries"]
    assert row["calls"] == 3


def test_session_entries_aggregate_children_without_assigning_labels_to_empty_parents():
    event = session_label_event("child-labels", session_id="child", model="gpt-6-astra",
                                project_key="child-project", project_path="E:/Code/child")
    row = build_sessions_report(
        [event], PriceCatalog.load_default(), {}, {"child": {"parent_session_id": "root"}},
    )[0]
    assert row["key"] == "root"
    assert row["model_entries"] == [{"key": "gpt-6-astra", "display_name": "GPT-6 Astra"}]
    assert row["project_entries"] == [{"key": "child-project", "display_name": "child",
                                       "path": "E:/Code/child"}]
    assert row["members"][0]["model_entries"] == []
    assert row["members"][0]["project_entries"] == []
    assert row["members"][1]["model_entries"] == row["model_entries"]


def test_generated_session_title_metadata_preserves_identical_real_titles():
    event = session_label_event("title")
    generated = build_sessions_report([event], PriceCatalog.load_default(), {})[0]
    literal = build_sessions_report(
        [event], PriceCatalog.load_default(), {"root-session": "会话 root-session"},
    )[0]
    assert generated["title"] == literal["title"] == "会话 root-session"
    assert generated["title_generated"] is True
    assert generated["members"][0]["title_generated"] is True
    assert literal["title_generated"] is False
    assert literal["members"][0]["title_generated"] is False


def test_request_model_metadata_preserves_raw_id_and_existing_display_name():
    events = [session_label_event("unknown-model"),
              session_label_event("literal-model", model="未知模型")]
    rows = {row["key"]: row for row in request_rows(events, PriceCatalog.load_default())}
    assert rows["unknown-model"]["model_id"] == "unknown"
    assert rows["literal-model"]["model_id"] == "未知模型"
    assert rows["unknown-model"]["model"] == rows["literal-model"]["model"] == "未知模型"
