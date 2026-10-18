import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime

import pytest

from codex_token_report.db import Database
from codex_token_report.scanner import SessionScanner
from codex_token_report.tiers import PriorityTraceScanner


def _row(kind, payload, *, ordinal=None):
    return {
        "timestamp": "2026-10-18T00:01:00Z", "type": kind,
        "payload": payload, **({"ordinal": ordinal} if ordinal is not None else {}),
    }


def _settings(tier, **kwargs):
    return _row("event_msg", {
        "type": "thread_settings_applied", "thread_settings": {"service_tier": tier},
    }, **kwargs)


def _start(turn, **kwargs):
    return _row("event_msg", {"type": "task_started", "turn_id": turn}, **kwargs)


def _usage(response, turn=None, **kwargs):
    return _row("token_usage_record", {
        "response_id": response, "turn_id": turn,
        "usage": {"input_tokens": 100, "cached_input_tokens": 20, "output_tokens": 10},
    }, **kwargs)


def _write(path, rows, *, append=False):
    with path.open("a" if append else "w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row) + "\n")


def _setup(tmp_path, rows):
    home = tmp_path / "codex"
    sessions = home / "sessions"
    sessions.mkdir(parents=True)
    path = sessions / "rollout.jsonl"
    _write(path, [
        _row("session_meta", {"id": "thread-1"}),
        _row("turn_context", {"model": "gpt-6.1-sol"}),
        *rows,
    ])
    database = Database(tmp_path / "data/usage.sqlite3")
    return home, path, database


def _scan(home, database):
    return SessionScanner(codex_home=home, database=database, timezone="Asia/Taipei").scan()


def _trace(home, body):
    with closing(sqlite3.connect(home / "logs_2.sqlite")) as connection, connection:
        connection.execute("CREATE TABLE logs(id INTEGER PRIMARY KEY, ts INTEGER, feedback_log_body TEXT)")
        timestamp = int(datetime(2026, 10, 18, 0, 1, tzinfo=UTC).timestamp())
        connection.execute("INSERT INTO logs VALUES (1, ?, ?)", (timestamp, body))


@pytest.mark.parametrize("tier", ["priority", "fast", " PRIORITY "])
@pytest.mark.parametrize("trace_state", ["missing", "empty", "broken"])
def test_session_settings_work_independently_of_trace(tmp_path, tier, trace_state):
    home, _, database = _setup(tmp_path, [_settings(tier), _start("turn-1"), _usage("r1")])
    if trace_state == "empty":
        with closing(sqlite3.connect(home / "logs_2.sqlite")) as connection, connection:
            connection.execute("CREATE TABLE logs(id INTEGER PRIMARY KEY, ts INTEGER, feedback_log_body TEXT)")
    elif trace_state == "broken":
        (home / "logs_2.sqlite").write_bytes(b"not a sqlite database")

    result = _scan(home, database)

    event, = database.fetch_events()
    assert (event["service_tier"], event["tier_source"], event["turn_id"]) == (
        "priority", "session_settings", "turn-1",
    )
    assert result.tier_counts["priority"] == 1
    assert _scan(home, database).scanned_files == 0
    assert database.fetch_events()[0]["service_tier"] == "priority"


def test_session_fast_survives_exclusively_locked_trace(tmp_path):
    home, _, database = _setup(tmp_path, [_settings("priority"), _start("turn-1"), _usage("r1")])
    _trace(home, 'turn.id=unrelated tags_json={"service_tier":"default"}')
    with closing(sqlite3.connect(home / "logs_2.sqlite")) as locked:
        locked.execute("BEGIN EXCLUSIVE")

        result = _scan(home, database)

        assert result.priority_trace["available"] is False
        assert "locked" in result.priority_trace["error"]
        assert database.fetch_events()[0]["service_tier"] == "priority"


def test_session_settings_survive_reopen_and_only_apply_to_following_turns(tmp_path):
    home, path, database = _setup(tmp_path, [
        _settings("priority"), _start("turn-1"), _usage("r1"),
    ])
    _scan(home, database)
    _write(path, [
        _settings("default"), _usage("late-r1", "turn-1"),
        _start("turn-2"), _usage("r2"),
        _settings("unsupported"), _start("turn-3"), _usage("r3"),
        _settings("fast"), _start("turn-4"), _usage("r4"),
        _usage("late-r2", "turn-2"),
    ], append=True)
    reopened = Database(database.path)

    result = _scan(home, reopened)

    assert result.incremental_files == 1
    assert {e["response_id"]: e["service_tier"] for e in reopened.fetch_events()} == {
        "r1": "priority", "late-r1": "priority", "r2": "standard", "r3": "unknown",
        "r4": "priority", "late-r2": "standard",
    }


@pytest.mark.parametrize(("previous", "applied", "expected"), [
    ("default", "priority", "priority"), ("priority", "default", "standard"),
    (None, "fast", "priority"), ("priority", None, "unknown"),
])
@pytest.mark.parametrize("split", [None, 2, 3])
def test_settings_after_task_start_apply_before_first_usage(
    tmp_path, previous, applied, expected, split,
):
    home, path, database = _setup(tmp_path, [])
    rows = [_settings(previous), _start("turn-1"), _settings(applied),
            _row("turn_context", {"turn_id": "turn-1", "model": "gpt-6.1-sol"}), _usage("r1")]
    if split is not None:
        _write(path, rows[:split], append=True)
        _scan(home, database)
        _write(path, rows[split:], append=True)
    else:
        _write(path, rows, append=True)

    result = _scan(home, Database(database.path))

    assert result.incremental_files == int(split is not None)
    event, = database.fetch_events()
    assert event["session_service_tier"] == expected
    assert event["service_tier"] == expected
    assert event["turn_id"] == "turn-1"


def test_context_can_establish_pending_tier_without_task_start(tmp_path):
    home, _, database = _setup(tmp_path, [
        _settings("default"),
        _row("turn_context", {"turn_id": "turn-1", "model": "gpt-6.1-sol"}),
        _settings("priority"), _usage("r1"),
    ])

    _scan(home, database)

    assert database.fetch_events()[0]["service_tier"] == "priority"


def test_quota_only_token_event_does_not_freeze_pending_tier(tmp_path):
    home, _, database = _setup(tmp_path, [
        _settings("default"), _start("turn-1"),
        _row("event_msg", {"type": "token_count", "info": None}),
        _settings("priority"), _usage("r1"),
    ])

    _scan(home, database)

    assert database.fetch_events()[0]["service_tier"] == "priority"


def test_delayed_usage_does_not_confirm_another_turns_pending_tier(tmp_path):
    home, _, database = _setup(tmp_path, [
        _settings("default"), _start("turn-1"), _usage("r1"),
        _start("turn-2"), _usage("late-r1", "turn-1"),
        _settings("priority"), _usage("r2"),
    ])

    _scan(home, database)

    assert {e["response_id"]: e["service_tier"] for e in database.fetch_events()} == {
        "r1": "standard", "late-r1": "standard", "r2": "priority",
    }


def test_completed_empty_turn_does_not_take_following_settings(tmp_path):
    home, _, database = _setup(tmp_path, [
        _settings("default"), _start("empty-turn"),
        _row("event_msg", {"type": "task_complete", "turn_id": "empty-turn"}),
        _settings("priority"), _usage("late", "empty-turn"),
        _start("next-turn"), _usage("next"),
    ])

    _scan(home, database)

    assert {e["response_id"]: e["service_tier"] for e in database.fetch_events()} == {
        "late": "standard", "next": "priority",
    }


@pytest.mark.parametrize(("native", "trace", "expected"), [
    ("priority", "default", "standard"), ("default", "priority", "priority"),
    ("priority", "priority", "priority"), (None, "fast", "priority"),
])
def test_explicit_trace_wins_conflicts_without_erasing_native_evidence(
    tmp_path, native, trace, expected,
):
    home, _, database = _setup(tmp_path, [_settings(native), _start("turn-1"), _usage("r1")])
    _trace(home, 'thread_id="thread-1" turn.id="turn-1" model="gpt-6.1-sol" '
           'tags_json= ' + json.dumps({"service_tier": trace}))

    _scan(home, database)

    event, = database.fetch_events()
    assert (event["service_tier"], event["tier_source"]) == (expected, "logs_2_request")
    assert event["session_service_tier"] == {
        "priority": "priority", "default": "standard", None: "unknown",
    }[native]
    # Both validated sources remain usable after the trace file is deleted.
    (home / "logs_2.sqlite").unlink()
    _scan(home, Database(database.path))
    assert database.fetch_events()[0]["service_tier"] == expected


def test_trace_absence_cannot_override_explicit_session_fast(tmp_path):
    home, _, database = _setup(tmp_path, [_settings("priority"), _start("turn-1"), _usage("r1")])
    _trace(home, 'turn.id=unrelated tags_json={"service_tier":"default"}')

    _scan(home, database)

    event, = database.fetch_events()
    assert (event["service_tier"], event["tier_source"]) == ("priority", "session_settings")


def test_truncated_source_retains_confirmed_native_tier(tmp_path):
    home, path, database = _setup(tmp_path, [_settings("priority"), _start("turn-1"), _usage("r1")])
    _scan(home, database)
    _write(path, [_usage("r1")])

    _scan(home, Database(database.path))

    event, = database.fetch_events()
    assert (event["service_tier"], event["tier_source"]) == ("priority", "session_settings")


def test_explicit_unknown_settings_clear_previously_known_native_tier(tmp_path):
    home, path, database = _setup(tmp_path, [_settings("priority"), _start("turn-1"), _usage("r1")])
    _scan(home, database)
    _write(path, [_settings(None), _start("turn-1"), _usage("r1")])

    _scan(home, Database(database.path))

    event, = database.fetch_events()
    assert event["session_service_tier"] == "unknown"
    assert event["service_tier"] == "unknown"


def test_copied_subagent_settings_do_not_leak_into_owned_turns(tmp_path):
    home, path, database = _setup(tmp_path, [])
    _write(path, [
        _row("session_meta", {
            "id": "child", "parent_thread_id": "parent",
            "subagent_history_start_ordinal": 4,
        }, ordinal=0),
        _settings("priority", ordinal=1), _start("parent-turn", ordinal=2),
        _usage("copied", ordinal=3), _start("child-turn", ordinal=4),
        _usage("child", ordinal=5), _settings("default", ordinal=6),
        _start("child-turn-2", ordinal=7), _usage("child-2", ordinal=8),
    ])

    _scan(home, database)

    assert {e["response_id"]: e["service_tier"] for e in database.fetch_events()} == {
        "child": "unknown", "child-2": "standard",
    }


@pytest.mark.parametrize("marker", [
    'websocket request: {"type":"response.create","service_tier":"priority"}',
    'tags_json={"service_tier":"priority"}',
])
def test_trace_parser_normalizes_quoted_span_ids(marker):
    parsed = PriorityTraceScanner.parse_priority_row(
        source_path="trace", row_id=1, timestamp=1,
        body='thread_id="thread-1" codex.turn_input{turn.id="turn-1"}:'
             'turn{turn.id=turn-1 model="gpt-6.1-sol"}: ' + marker,
    )
    assert parsed is not None
    assert (parsed.turn_id, parsed.thread_id) == ("turn-1", "thread-1")


def test_upgrade_repairs_saved_quoted_trace_without_original_logs(tmp_path):
    home, _, database = _setup(tmp_path, [_start("turn-1"), _usage("r1")])
    _scan(home, database)
    source = str((home / "logs_2.sqlite").resolve())
    with database.connect() as connection:
        connection.execute("INSERT INTO priority_turns VALUES (?, ?, ?, ?, ?, ?, ?)", (
            source, '"turn-1"', '"thread-1"', "gpt-6.1-sol", "priority", None, 1,
        ))
    reopened = Database(database.path)

    _scan(home, reopened)

    assert reopened.fetch_events()[0]["service_tier"] == "priority"
    with reopened.connect() as connection:
        row, = connection.execute("SELECT turn_id, thread_id FROM priority_turns").fetchall()
        assert tuple(row) == ("turn-1", "thread-1")


def test_parser_upgrade_reparses_unchanged_files_and_preserves_price_snapshots(tmp_path):
    home, _, database = _setup(tmp_path, [_settings("priority"), _start("turn-1"), _usage("r1")])
    _trace(home, 'turn.id="turn-1" tags_json={"service_tier":"priority"}')
    _scan(home, database)
    event_id = database.fetch_events()[0]["event_id"]
    with database.connect() as connection:
        snapshots = [tuple(r) for r in connection.execute("SELECT * FROM event_price_snapshots")]
        connection.execute("UPDATE usage_events SET session_service_tier=NULL, service_tier='standard'")
    database.set_metadata("scanner_parser_version", "5")
    database.set_metadata("priority_parser_version:" + str((home / "logs_2.sqlite").resolve()), "2")

    result = _scan(home, Database(database.path))

    assert result.scanned_files == 1
    assert result.priority_trace["discovered_priority_turns"] == 1
    event, = database.fetch_events()
    assert (event["event_id"], event["session_service_tier"], event["service_tier"]) == (
        event_id, "priority", "priority",
    )
    with database.connect() as connection:
        assert [tuple(r) for r in connection.execute("SELECT * FROM event_price_snapshots")] == snapshots
