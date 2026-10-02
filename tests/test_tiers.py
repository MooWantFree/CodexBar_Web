import json
import sqlite3
from pathlib import Path

from codex_token_report.db import Database
from codex_token_report.tiers import PriorityTraceScanner


def test_sampling_tags_detect_inherited_fast_without_submission_tier():
    body = ('session_loop{thread_id=thread-7}:turn{turn.id=turn-42 model=gpt-6.1-sol}:'
            ' model="gpt-6.1-sol" tags_json={"service_tier":"priority"}')
    parsed = PriorityTraceScanner.parse_priority_row(
        source_path="logs_2.sqlite", row_id=12, timestamp=1789876800, body=body,
    )
    assert parsed is not None
    assert parsed.turn_id == "turn-42"
    assert parsed.pricing_model == "gpt-6.1-sol"
    assert PriorityTraceScanner.parse_priority_row(
        source_path="logs_2.sqlite", row_id=13, timestamp=1789876801,
        body=body.replace('"priority"', '"default"'),
    ) is None


def test_parser_upgrade_revisits_old_rows_and_then_resumes_incrementally(tmp_path):
    source = tmp_path / "logs_2.sqlite"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE logs(id INTEGER PRIMARY KEY, ts INTEGER, feedback_log_body TEXT)")
        connection.execute("INSERT INTO logs VALUES (1, 1789876800, ?)", (
            ('turn.id=turn-42 thread_id=thread-7 model=gpt-6.1-sol '
             'tags_json={"service_tier":"priority"}'),
        ))
    database = Database(tmp_path / "usage.sqlite3")
    database.save_priority_trace(
        source_path=str(source.resolve()), source_identity=PriorityTraceScanner._source_identity(source),
        last_row_id=1, coverage_start_utc=None, coverage_end_utc=None,
        scanned_at="2026-09-20T00:00:00+00:00", turns=[], reset=False,
    )
    scanner = PriorityTraceScanner(codex_home=tmp_path, database=database)
    assert scanner.scan().discovered_priority_turns == 1
    assert scanner.scan().scanned_rows == 0


def test_parses_websocket_priority_request() -> None:
    request = {
        "type": "response.create",
        "service_tier": "priority",
        "model": "gpt-5.6-sol",
    }
    body = "turn.id=turn-42 thread_id=thread-7 websocket request: " + json.dumps(request)

    turn = PriorityTraceScanner.parse_priority_row(
        source_path="logs_2.sqlite",
        row_id=12,
        timestamp=1_789_876_800,
        body=body,
    )

    assert turn is not None
    assert turn.turn_id == "turn-42"
    assert turn.thread_id == "thread-7"
    assert turn.pricing_model == "gpt-5.6-sol"
    assert turn.requested_tier == "priority"


def test_ignores_standard_request() -> None:
    body = "turn.id=turn-42 websocket request: " + json.dumps(
        {"type": "response.create", "service_tier": "default", "model": "gpt-5.6-sol"}
    )

    turn = PriorityTraceScanner.parse_priority_row(
        source_path="logs_2.sqlite",
        row_id=12,
        timestamp=1_789_876_800,
        body=body,
    )

    assert turn is None


def test_trace_reset_preserves_turns_and_real_coverage_gaps(tmp_path: Path) -> None:
    database = Database(tmp_path / "usage.sqlite3")
    source_path = "logs_2.sqlite"
    events = []
    for index, (turn_id, timestamp) in enumerate(
        [
            ("old-priority", "2026-09-20T00:30:00+00:00"),
            ("gap-standard", "2026-09-20T03:00:00+00:00"),
            ("new-priority", "2026-09-20T05:30:00+00:00"),
        ]
    ):
        events.append(
            {
                "event_id": str(index),
                "source_file": "rollout.jsonl",
                "source_kind": "token_usage_record",
                "timestamp_utc": timestamp,
                "local_date": "2026-09-20",
                "model": "gpt-5.6-sol",
                "turn_id": turn_id,
                "response_id": f"response-{index}",
                "input_tokens": 10,
                "cached_input_tokens": 0,
                "cache_write_input_tokens": 0,
                "output_tokens": 1,
                "reasoning_output_tokens": 0,
                "total_tokens": 11,
                "service_tier": "unknown",
                "tier_source": None,
                "pricing_model": "gpt-5.6-sol",
            }
        )
    database.replace_file_events(
        source_file="rollout.jsonl",
        mtime_ns=1,
        size_bytes=1,
        events=events,
        parse_errors=0,
        scanned_at="2026-09-20T06:00:00+00:00",
    )
    database.save_priority_trace(
        source_path=source_path,
        source_identity="generation-1",
        last_row_id=100,
        coverage_start_utc="2026-09-20T00:00:00+00:00",
        coverage_end_utc="2026-09-20T01:00:00+00:00",
        scanned_at="2026-09-20T01:00:00+00:00",
        turns=[
            {
                "source_path": source_path,
                "turn_id": "old-priority",
                "thread_id": None,
                "pricing_model": "gpt-5.6-sol",
                "requested_tier": "priority",
                "trace_timestamp_utc": "2026-09-20T00:30:00+00:00",
                "source_row_id": 80,
            }
        ],
        reset=False,
    )
    database.save_priority_trace(
        source_path=source_path,
        source_identity="generation-2",
        last_row_id=20,
        coverage_start_utc="2026-09-20T05:00:00+00:00",
        coverage_end_utc="2026-09-20T06:00:00+00:00",
        scanned_at="2026-09-20T06:00:00+00:00",
        turns=[
            {
                "source_path": source_path,
                "turn_id": "new-priority",
                "thread_id": None,
                "pricing_model": "gpt-5.6-sol",
                "requested_tier": "priority",
                "trace_timestamp_utc": "2026-09-20T05:30:00+00:00",
                "source_row_id": 10,
            }
        ],
        reset=True,
    )

    database.classify_service_tiers(
        source_path=source_path,
        coverage_start_utc=None,
        coverage_end_utc=None,
    )
    tiers = {event["turn_id"]: event["service_tier"] for event in database.fetch_events()}

    assert tiers == {
        "old-priority": "priority",
        "gap-standard": "unknown",
        "new-priority": "priority",
    }
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM priority_turns").fetchone()[0] == 2
    assert database.storage_stats()["max_trace_gap_hours"] == 4.0
