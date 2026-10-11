import sqlite3
from pathlib import Path
from typing import Any

import pytest

from codex_token_report.db import Database


@pytest.fixture
def alias_database(tmp_path: Path) -> Database:
    return Database(tmp_path / "usage.sqlite3")


@pytest.fixture
def alias_event() -> dict[str, Any]:
    return {
        "event_id": "incoming-event",
        "source_file": "sessions/rollout.jsonl",
        "session_id": "session-1",
        "ordinal": 30,
        "is_subagent": 0,
        "source_kind": "token_usage_record",
        "timestamp_utc": "2026-09-20T01:00:00+00:00",
        "local_date": "2026-09-20",
        "model": "gpt-5.6-sol",
        "turn_id": "turn-1",
        "response_id": "response-1",
        "input_tokens": 100,
        "cached_input_tokens": 20,
        "cache_write_input_tokens": 0,
        "output_tokens": 10,
        "reasoning_output_tokens": 2,
        "total_tokens": 110,
        "service_tier": "unknown",
        "tier_source": None,
        "pricing_model": "gpt-5.6-sol",
    }


def _merge_alias(
    database: Database,
    stored_events: list[dict[str, Any]],
    incoming_event: dict[str, Any],
) -> str:
    with database.connect() as connection:
        Database._insert_events(connection, Database._event_list(stored_events))
        Database._merge_event_aliases(
            connection,
            session_id=incoming_event["session_id"],
            source_file=incoming_event["source_file"],
            event_list=[incoming_event],
        )
    return str(incoming_event["event_id"])


def test_event_alias_matches_response_without_fallback_fields(
    alias_database: Database, alias_event: dict[str, Any]
) -> None:
    stored = {
        **alias_event,
        "event_id": "original-event",
        "source_file": "archive/old-rollout.jsonl",
        "ordinal": None,
        "timestamp_utc": "2026-09-19T00:00:00+00:00",
        "turn_id": "old-turn",
        "model": "old-model",
        "input_tokens": 1,
        "output_tokens": 2,
        "total_tokens": 3,
    }

    assert _merge_alias(alias_database, [stored], alias_event) == "original-event"


@pytest.mark.parametrize("response_id", ["response-1", None])
def test_event_alias_matches_fallback_after_ordinal_and_source_move(
    alias_database: Database, alias_event: dict[str, Any], response_id: str | None
) -> None:
    stored = {
        **alias_event,
        "event_id": "original-fallback",
        "source_file": "archive/old-rollout.jsonl",
        "ordinal": 10,
        "source_kind": "token_count_fallback",
        "response_id": None,
    }
    alias_event["response_id"] = response_id

    assert _merge_alias(alias_database, [stored], alias_event) == "original-fallback"


@pytest.mark.parametrize("response_id", ["response-1", None])
def test_event_alias_does_not_merge_explicitly_different_sessions(
    alias_database: Database, alias_event: dict[str, Any], response_id: str | None
) -> None:
    alias_event["response_id"] = response_id
    stored = {**alias_event, "event_id": "other-session-event", "session_id": "session-2"}

    assert _merge_alias(alias_database, [stored], alias_event) == "incoming-event"


def test_event_alias_keeps_response_and_fallback_matches_ambiguous(
    alias_database: Database, alias_event: dict[str, Any]
) -> None:
    stored = [
        {**alias_event, "event_id": "response-match"},
        {
            **alias_event,
            "event_id": "fallback-match",
            "response_id": None,
            "source_kind": "token_count_fallback",
        },
    ]

    assert _merge_alias(alias_database, stored, alias_event) == "incoming-event"


@pytest.mark.parametrize("response_id", ["response-1", None])
def test_event_alias_keeps_multiple_matches_in_one_branch_ambiguous(
    alias_database: Database, alias_event: dict[str, Any], response_id: str | None
) -> None:
    stored = [
        {
            **alias_event,
            "event_id": f"stored-{ordinal}",
            "ordinal": ordinal,
            "response_id": response_id,
        }
        for ordinal in (10, 20, 25)
    ]

    assert _merge_alias(alias_database, stored, alias_event) == "incoming-event"


@pytest.mark.parametrize("incoming_session", ["session-1", None])
@pytest.mark.parametrize(
    ("response_id", "stored_source", "expected_id"),
    [
        ("response-1", "archive/old-rollout.jsonl", "historical-event"),
        (None, "sessions/rollout.jsonl", "historical-event"),
        (None, "archive/old-rollout.jsonl", "incoming-event"),
    ],
)
def test_event_alias_preserves_null_session_history_rules(
    alias_database: Database,
    alias_event: dict[str, Any],
    incoming_session: str | None,
    response_id: str | None,
    stored_source: str,
    expected_id: str,
) -> None:
    stored = {
        **alias_event,
        "event_id": "historical-event",
        "session_id": None,
        "source_file": stored_source,
        "response_id": response_id,
        "ordinal": 10,
    }
    alias_event["session_id"] = incoming_session

    assert _merge_alias(alias_database, [stored], alias_event) == expected_id


@pytest.mark.parametrize("response_id", ["response-1", None])
def test_event_alias_with_unknown_incoming_session_does_not_merge_known_session(
    alias_database: Database, alias_event: dict[str, Any], response_id: str | None
) -> None:
    stored = {**alias_event, "event_id": "known-session-event", "response_id": response_id}
    alias_event["session_id"] = None

    assert _merge_alias(alias_database, [stored], alias_event) == "incoming-event"


@pytest.mark.parametrize(
    "stored_changes",
    [
        {"ordinal": None},
        {"timestamp_utc": "2026-09-20T01:00:01+00:00"},
        {"turn_id": "different-turn"},
        {"source_kind": "different-kind"},
        {"input_tokens": 101},
        {"output_tokens": 11},
        {"total_tokens": 111},
        {"model": "different-model"},
    ],
)
def test_event_alias_fallback_requires_matching_identity_fields(
    alias_database: Database, alias_event: dict[str, Any], stored_changes: dict[str, Any]
) -> None:
    stored = {
        **alias_event,
        "event_id": "fallback-event",
        "response_id": None,
        **stored_changes,
    }

    assert _merge_alias(alias_database, [stored], alias_event) == "incoming-event"


def test_event_alias_fallback_requires_incoming_ordinal(
    alias_database: Database, alias_event: dict[str, Any]
) -> None:
    stored = {**alias_event, "event_id": "fallback-event", "response_id": None}
    alias_event["ordinal"] = None

    assert _merge_alias(alias_database, [stored], alias_event) == "incoming-event"


def test_project_migration_preserves_events_and_requests_rescan(tmp_path: Path) -> None:
    path = tmp_path / "usage.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE usage_events (
                event_id TEXT PRIMARY KEY,
                source_file TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                timestamp_utc TEXT NOT NULL,
                local_date TEXT NOT NULL,
                model TEXT,
                turn_id TEXT,
                response_id TEXT,
                input_tokens INTEGER NOT NULL,
                cached_input_tokens INTEGER NOT NULL,
                cache_write_input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                reasoning_output_tokens INTEGER NOT NULL,
                total_tokens INTEGER NOT NULL,
                service_tier TEXT NOT NULL DEFAULT 'unknown',
                tier_source TEXT,
                pricing_model TEXT
            );
            CREATE TABLE file_state (
                source_file TEXT PRIMARY KEY,
                mtime_ns INTEGER NOT NULL,
                size_bytes INTEGER NOT NULL,
                event_count INTEGER NOT NULL,
                parse_errors INTEGER NOT NULL,
                scanned_at TEXT NOT NULL
            );
            INSERT INTO usage_events VALUES (
                'event-1', 'gone.jsonl', 'token_usage_record',
                '2026-09-20T00:00:00+00:00', '2026-09-20', 'gpt-5.6-sol',
                'turn-1', 'response-1', 10, 0, 0, 1, 0, 11,
                'unknown', NULL, 'gpt-5.6-sol'
            );
            INSERT INTO file_state VALUES ('gone.jsonl', 1, 1, 1, 0, '2026-09-20');
            """
        )

    database = Database(path)

    with database.connect() as connection:
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(usage_events)").fetchall()
        }
        event_count = connection.execute("SELECT COUNT(*) FROM usage_events").fetchone()[0]
        file_count = connection.execute("SELECT COUNT(*) FROM file_state").fetchone()[0]
    assert {"project_key", "project_path", "workspace_root", "working_directory"} <= columns
    assert event_count == 1
    assert file_count == 1
    assert not database.file_is_current("gone.jsonl", 1, 1)


def test_session_metadata_preserves_known_relationships(tmp_path: Path) -> None:
    path = tmp_path / "usage.sqlite3"
    database = Database(path)
    database.save_session_metadata(
        {
            "parent": {"parent_session_id": None, "is_subagent": False},
            "child": {"parent_session_id": "parent", "is_subagent": True},
            "unknown-child": {"parent_session_id": None, "is_subagent": True},
        }
    )
    database.save_session_metadata(
        {
            "child": {"parent_session_id": None, "is_subagent": False},
            "unknown-child": {"parent_session_id": "parent", "is_subagent": True},
        }
    )

    assert Database(path).session_metadata() == {
        "parent": {"parent_session_id": None, "is_subagent": False},
        "child": {"parent_session_id": "parent", "is_subagent": True},
        "unknown-child": {"parent_session_id": "parent", "is_subagent": True},
    }


def test_session_metadata_rejects_invalid_parent_ids(tmp_path: Path) -> None:
    database = Database(tmp_path / "usage.sqlite3")
    database.save_session_metadata(
        {
            "self": {"parent_session_id": " SELF ", "is_subagent": False},
            "empty": {"parent_session_id": " ", "is_subagent": False},
            "number": {"parent_session_id": 123, "is_subagent": False},
            "": {"parent_session_id": "parent", "is_subagent": True},
        }
    )

    assert database.session_metadata() == {
        identity: {"parent_session_id": None, "is_subagent": False}
        for identity in ("self", "empty", "number")
    }


def test_distinct_models_keeps_only_reportable_effective_models(
    alias_database: Database, alias_event: dict[str, Any]
) -> None:
    variants = [
        {"event_id": "fallback", "model": "fallback-model", "pricing_model": None},
        {"event_id": "excluded", "pricing_model": "excluded-model"},
        {"event_id": "inactive", "model": "ignored-model", "pricing_model": "priced-model"},
        {"event_id": "shared-excluded", "pricing_model": "shared-model"},
        {"event_id": "shared-visible", "pricing_model": "shared-model"},
        {"event_id": "empty", "pricing_model": ""},
        {"event_id": "unknown", "model": None, "pricing_model": None},
    ]
    with alias_database.connect() as connection:
        Database._insert_events(connection, Database._event_list([
            {**alias_event, **variant} for variant in variants
        ]))
        connection.executemany(
            "INSERT INTO usage_event_exclusions VALUES (?, 'duplicate', ?, '2026-09-20')",
            [("excluded", 1), ("inactive", 0), ("shared-excluded", 1)],
        )

    assert alias_database.distinct_models() == ["fallback-model", "priced-model", "shared-model"]
    with alias_database.connect() as connection:
        connection.execute("UPDATE usage_event_exclusions SET active = 0")
    assert alias_database.distinct_models() == [
        "excluded-model", "fallback-model", "priced-model", "shared-model",
    ]


def test_storage_stats_count_all_reportable_tiers_and_file_errors(
    alias_database: Database, alias_event: dict[str, Any]
) -> None:
    assert alias_database.storage_stats() == {
        "events": 0, "files": 0, "parse_errors": 0,
        "standard_events": 0, "priority_events": 0, "unknown_events": 0,
        "trace_coverage_intervals": 0, "max_trace_gap_hours": 0.0,
        "last_trace_coverage_end": None,
    }
    with alias_database.connect() as connection:
        Database._insert_events(connection, Database._event_list([
            {**alias_event, "event_id": key, "service_tier": tier}
            for key, tier in [
                ("standard", "standard"), ("priority", "priority"),
                ("unknown", "unknown"), ("other", "custom"), ("excluded", "priority"),
            ]
        ]))
        connection.execute(
            "INSERT INTO usage_event_exclusions VALUES ('excluded', 'duplicate', 1, '2026-09-20')"
        )
        connection.executemany(
            "INSERT INTO file_state "
            "(source_file, mtime_ns, size_bytes, event_count, parse_errors, scanned_at) "
            "VALUES (?, 1, 1, 1, ?, '2026-09-20')",
            [("first", 2), ("second", 3)],
        )
    stats = alias_database.storage_stats()
    assert {key: stats[key] for key in [
        "events", "files", "parse_errors", "standard_events",
        "priority_events", "unknown_events", "custom_events",
    ]} == {
        "events": 4, "files": 2, "parse_errors": 5,
        "standard_events": 1, "priority_events": 1, "unknown_events": 1, "custom_events": 1,
    }


def test_fetch_events_preserves_columns_order_and_exact_project_range(
    alias_database: Database, alias_event: dict[str, Any]
) -> None:
    variants = [
        ("before", "00:59:59", None), ("first", "01:00:00", ""),
        ("second", "01:15:00", None), ("excluded", "01:30:00", None),
        ("project", "01:45:00", "known-project"), ("end", "02:00:00", None),
    ]
    events = Database._event_list([
        {**alias_event, "event_id": key, "timestamp_utc": f"2026-09-20T{clock}+00:00",
         "project_key": project, "working_directory": "E:\\项目", "model": None}
        for key, clock, project in variants
    ])
    with alias_database.connect() as connection:
        Database._insert_events(connection, list(reversed(events)))
        connection.execute(
            "INSERT INTO usage_event_exclusions VALUES ('excluded', 'duplicate', 1, '2026-09-20')"
        )

    actual = alias_database.fetch_events(
        "2026-09-20", "2026-09-20", "unknown",
        start_at="2026-09-20T01:00:00+00:00", end_before="2026-09-20T02:00:00+00:00",
    )
    assert actual == events[1:3]
    assert alias_database.fetch_events("2026-09-21", "2026-09-21") == []
