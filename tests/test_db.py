import sqlite3
from pathlib import Path

from codex_token_report.db import Database


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
