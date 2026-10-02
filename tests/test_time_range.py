import csv
import io
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from codex_token_report.config import Settings
from codex_token_report.main import _report_range, create_app


@pytest.fixture
def client(tmp_path: Path):
    app = create_app(Settings(codex_home=tmp_path, data_dir=tmp_path / "data", scan_interval_minutes=0))
    timestamps = [
        "2026-09-19T15:59:59.999999+00:00",
        "2026-09-19T16:00:00+00:00",
        "2026-09-20T00:59:59.999999+00:00",
        "2026-09-20T01:00:00+00:00",
        "2026-09-20T01:30:00+00:00",
        "2026-09-20T01:30:59.999999+00:00",
        "2026-09-20T01:31:00+00:00",
        "2026-09-20T15:59:59.999999+00:00",
        "2026-09-20T16:00:00+00:00",
    ]
    app.state.database.replace_file_events(
        source_file="test-clock.jsonl", mtime_ns=1, size_bytes=1, parse_errors=0,
        scanned_at=timestamps[-1],
        events=[{
            "event_id": f"event-{index}", "source_file": "test-clock.jsonl",
            "source_kind": "token_usage_record", "timestamp_utc": timestamp,
            "local_date": datetime.fromisoformat(timestamp).astimezone(ZoneInfo("Asia/Taipei")).date().isoformat(),
            "model": "gpt-5.6-sol", "input_tokens": 10, "cached_input_tokens": 0,
            "cache_write_input_tokens": 0, "output_tokens": 2, "reasoning_output_tokens": 0,
            "total_tokens": 12, "project_key": "e:/code/clock", "project_path": "E:/Code/clock",
            "turn_id": None, "response_id": None, "service_tier": "standard",
            "tier_source": "test", "pricing_model": "gpt-5.6-sol",
            "workspace_root": "E:/Code/clock", "working_directory": "E:/Code/clock",
        } for index, timestamp in enumerate(timestamps)],
    )
    with TestClient(app) as test_client:
        yield test_client


def test_default_times_preserve_whole_day_including_fractional_last_second(client: TestClient):
    result = client.get("/api/summary", params={"start": "2026-09-20", "end": "2026-09-20"})
    assert result.status_code == 200
    assert result.json()["total"]["calls"] == 7
    assert result.json()["range"]["start_time"] == "00:00"
    assert result.json()["range"]["end_time"] == "23:59"


def test_minute_range_filters_summary_projects_project_daily_and_csv(client: TestClient):
    params = {"start": "2026-09-20", "end": "2026-09-20", "start_time": "09:00", "end_time": "09:30"}
    summary = client.get("/api/summary", params=params).json()
    assert summary["total"]["calls"] == 3
    assert summary["total"]["total_tokens"] == 36
    assert summary["range"] == {**params, "price_mode": "snapshot"}
    projects = client.get("/api/projects", params=params).json()
    assert projects["projects"][0]["total_tokens"] == 36
    daily = client.get("/api/projects/daily", params={**params, "project": "e:/code/clock"}).json()
    assert daily["total"]["total_tokens"] == 36
    assert daily["range"] == {**params, "price_mode": "snapshot"}
    exported = client.get("/api/export.csv", params=params)
    rows = list(csv.DictReader(io.StringIO(exported.text.lstrip("\ufeff"))))
    assert len(rows) == 1 and rows[0]["calls"] == "3"
    assert "0900" in exported.headers["content-disposition"]


def test_same_minute_cross_day_and_open_ended_ranges(client: TestClient):
    same_minute = client.get("/api/summary", params={
        "start": "2026-09-20", "end": "2026-09-20", "start_time": "09:30", "end_time": "09:30",
    })
    assert same_minute.json()["total"]["calls"] == 2
    cross_day = client.get("/api/summary", params={
        "start": "2026-09-19", "end": "2026-09-20", "start_time": "23:59", "end_time": "00:00",
    })
    assert cross_day.json()["total"]["calls"] == 2
    assert client.get("/api/summary").json()["total"]["calls"] == 9
    assert client.get("/api/summary", params={"end": "2026-09-20", "end_time": "00:00"}).json()["total"]["calls"] == 2


def test_reset_pair_keeps_seconds_and_excludes_next_cycle_boundary(client: TestClient):
    params = {
        "start": "2026-09-20", "end": "2026-09-20", "start_time": "09:00", "end_time": "09:30",
        "start_at": "2026-09-20T01:00:30+00:00", "end_at": "2026-09-20T01:30:59.999999+00:00",
    }
    result = client.get("/api/summary", params=params).json()
    assert result["total"]["calls"] == 1
    assert result["range"]["start_at"] == params["start_at"]
    assert result["range"]["end_at"] == params["end_at"]
    assert result["range"]["end_exclusive"]
    projects = client.get("/api/projects", params=params).json()
    assert projects["projects"][0]["total_tokens"] == 12
    daily = client.get("/api/projects/daily", params={**params, "project": "e:/code/clock"}).json()
    assert daily["total"]["calls"] == 1
    exported = client.get("/api/export.csv", params=params)
    assert next(csv.DictReader(io.StringIO(exported.text.lstrip("\ufeff"))))["calls"] == "1"


@pytest.mark.parametrize("overrides", [
    {"start_at": "invalid"}, {"start_at": "2026-09-20T01:00:30"},
    {"start_at": "2026-09-20T02:00:30+00:00"}, {"end_at": ""},
    {"end_at": "2026-09-20T01:00:00+00:00", "end_time": "09:00"},
])
def test_invalid_exact_reset_ranges_are_rejected(client: TestClient, overrides: dict):
    params = {
        "start": "2026-09-20", "end": "2026-09-20", "start_time": "09:00", "end_time": "09:30",
        "start_at": "2026-09-20T01:00:30+00:00", "end_at": "2026-09-20T01:30:30+00:00",
        **overrides,
    }
    assert client.get("/api/summary", params=params).status_code == 400


@pytest.mark.parametrize("extra", [
    {"start_time": "24:00"}, {"end_time": "23:60"}, {"start_time": "9:00"},
    {"start_time": "09:00:00"}, {"start_time": "12:00", "end_time": "11:59"},
    {"start": "2026-09-21"},
])
def test_invalid_and_reversed_ranges_return_400_everywhere(client: TestClient, extra: dict):
    params = {"start": "2026-09-20", "end": "2026-09-20", **extra}
    for route in ("/api/summary", "/api/projects", "/api/projects/daily", "/api/export.csv"):
        assert client.get(route, params={**params, "project": "e:/code/clock"}).status_code == 400


def test_clock_boundaries_use_configured_timezone_and_reject_dst_gap():
    selected = _report_range("2026-09-20", "2026-09-20", "09:00", "09:30", "Asia/Taipei")
    assert selected.start_at == "2026-09-20T01:00:00+00:00"
    assert selected.end_before == "2026-09-20T01:31:00+00:00"
    utc = _report_range("2026-09-20", "2026-09-20", "09:00", "09:30", "UTC")
    assert utc.start_at == "2026-09-20T09:00:00+00:00"
    with pytest.raises(HTTPException, match="不存在"):
        _report_range("2026-03-08", "2026-03-08", "02:30", "03:30", "America/New_York")
