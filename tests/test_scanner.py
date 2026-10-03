import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codex_token_report.db import Database
from codex_token_report.scanner import SCANNER_PARSER_VERSION, ParserState, SessionScanner


def _line(payload: dict) -> str:
    return json.dumps(payload, separators=(",", ":"))


def _priority_trace(codex_home: Path, turn_id: str) -> None:
    timestamp = int(datetime(2026, 9, 20, 1, 0, tzinfo=UTC).timestamp())
    with sqlite3.connect(codex_home / "logs_2.sqlite") as connection:
        connection.execute(
            """
            CREATE TABLE logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                feedback_log_body TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO logs(ts, feedback_log_body) VALUES (?, ?)",
            (
                timestamp,
                (
                    "thread_id=thread-1 Submission sub=Submission { "
                    f'id: "{turn_id}", service_tier: Some(Some("priority")) }}'
                ),
            ),
        )


def test_scanner_prefers_usage_records_and_maps_model(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    sessions = codex_home / "sessions" / "2026" / "09" / "20"
    sessions.mkdir(parents=True)
    rollout = sessions / "rollout.jsonl"
    lines = [
        {
            "timestamp": "2026-09-20T01:00:00Z",
            "type": "turn_context",
            "payload": {
                "turn_id": "turn-1",
                "model": "gpt-5.6-sol",
                "cwd": str(sessions),
                "workspace_roots": [str(codex_home)],
            },
        },
        {
            "timestamp": "2026-09-20T01:00:01Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "last_token_usage": {
                        "input_tokens": 100,
                        "cached_input_tokens": 80,
                        "output_tokens": 10,
                        "total_tokens": 110,
                    }
                },
            },
        },
        {
            "timestamp": "2026-09-20T01:00:01Z",
            "ordinal": 3,
            "type": "token_usage_record",
            "payload": {
                "turn_id": "turn-1",
                "response_id": "resp-1",
                "usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 80,
                    "cache_write_input_tokens": 0,
                    "output_tokens": 10,
                    "reasoning_output_tokens": 2,
                    "total_tokens": 110,
                },
            },
        },
    ]
    rollout.write_text("\n".join(_line(item) for item in lines), encoding="utf-8")
    _priority_trace(codex_home, "turn-1")

    database = Database(tmp_path / "data" / "usage.sqlite3")
    scanner = SessionScanner(codex_home=codex_home, database=database, timezone="Asia/Taipei")
    result = scanner.scan()
    events = database.fetch_events()

    assert result.stored_events == 1
    assert len(events) == 1
    assert events[0]["model"] == "gpt-5.6-sol"
    assert events[0]["source_kind"] == "token_usage_record"
    assert events[0]["local_date"] == "2026-09-20"
    assert events[0]["service_tier"] == "priority"
    assert events[0]["tier_source"] == "logs_2_request"
    assert events[0]["project_path"] == str(codex_home.resolve())
    assert events[0]["working_directory"] == str(sessions.resolve())
    assert result.tier_counts["priority"] == 1


def test_scanner_skips_unchanged_file(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "empty.jsonl").write_text("", encoding="utf-8")
    database = Database(tmp_path / "data" / "usage.sqlite3")
    scanner = SessionScanner(codex_home=codex_home, database=database, timezone="Asia/Taipei")

    first = scanner.scan()
    second = scanner.scan()

    assert first.scanned_files == 1
    assert second.scanned_files == 0
    assert second.unchanged_files == 1


def test_scanner_keeps_events_after_source_file_disappears(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    rollout = sessions / "rollout.jsonl"
    rollout.write_text(
        _line(
            {
                "timestamp": "2026-09-20T01:00:01Z",
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "turn_id": "turn-1",
                    "info": {
                        "last_token_usage": {
                            "input_tokens": 100,
                            "cached_input_tokens": 20,
                            "output_tokens": 10,
                        }
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    database = Database(tmp_path / "data" / "usage.sqlite3")
    scanner = SessionScanner(codex_home=codex_home, database=database, timezone="Asia/Taipei")

    scanner.scan()
    rollout.unlink()
    scanner.scan()

    assert len(database.fetch_events()) == 1


def test_parser_upgrade_keeps_history_for_missing_source(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    (codex_home / "sessions").mkdir(parents=True)
    database = Database(tmp_path / "data" / "usage.sqlite3")
    database.replace_file_events(
        source_file="gone.jsonl",
        mtime_ns=1,
        size_bytes=1,
        events=[
            {
                "event_id": "old-event",
                "source_file": "gone.jsonl",
                "source_kind": "token_usage_record",
                "timestamp_utc": "2026-09-20T01:00:00+00:00",
                "local_date": "2026-09-20",
                "model": "gpt-5.6-sol",
                "turn_id": None,
                "response_id": "old-response",
                "input_tokens": 100,
                "cached_input_tokens": 0,
                "cache_write_input_tokens": 0,
                "output_tokens": 10,
                "reasoning_output_tokens": 0,
                "total_tokens": 110,
                "service_tier": "unknown",
                "tier_source": None,
                "pricing_model": "gpt-5.6-sol",
            }
        ],
        parse_errors=0,
        scanned_at="2026-09-20T01:00:00+00:00",
    )

    SessionScanner(codex_home=codex_home, database=database, timezone="UTC").scan()

    assert [event["event_id"] for event in database.fetch_events()] == ["old-event"]


def test_scanner_excludes_copied_subagent_history(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    rollout = sessions / "subagent.jsonl"
    rows = [
        {
            "timestamp": "2026-09-20T01:00:00Z",
            "ordinal": 0,
            "type": "session_meta",
            "payload": {
                "session_id": "parent-session",
                "id": "child-session",
                "source": {"subagent": {"other": "reviewer"}},
                "subagent_history_start_ordinal": 5,
            },
        },
        {
            "timestamp": "2026-09-20T01:00:01Z",
            "ordinal": 3,
            "type": "token_usage_record",
            "payload": {
                "response_id": "copied-response",
                "usage": {"input_tokens": 100, "output_tokens": 10},
            },
        },
        {
            "timestamp": "2026-09-20T01:00:02Z",
            "ordinal": 6,
            "type": "token_usage_record",
            "payload": {
                "response_id": "owned-response",
                "usage": {"input_tokens": 20, "output_tokens": 2},
            },
        },
    ]
    rollout.write_text("\n".join(_line(row) for row in rows), encoding="utf-8")
    database = Database(tmp_path / "data" / "usage.sqlite3")
    scanner = SessionScanner(codex_home=codex_home, database=database, timezone="UTC")

    result = scanner.scan()
    events = database.fetch_events()

    assert result.skipped_copied_events == 1
    assert result.stored_events == 1
    assert [event["response_id"] for event in events] == ["owned-response"]
    assert events[0]["session_id"] == "child-session"
    assert events[0]["is_subagent"] == 1


def test_scanner_deduplicates_session_moved_to_archive(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    sessions = codex_home / "sessions"
    archive = codex_home / "archived_sessions"
    sessions.mkdir(parents=True)
    archive.mkdir()
    rollout = sessions / "rollout-stable-session.jsonl"
    rows = [
        {
            "timestamp": "2026-09-20T01:00:00Z",
            "ordinal": 0,
            "type": "session_meta",
            "payload": {"id": "stable-session", "source": "subagent",
                        "subagent_history_start_ordinal": 0},
        },
        {
            "timestamp": "2026-09-20T01:00:01Z",
            "ordinal": 1,
            "type": "token_usage_record",
            "payload": {
                "response_id": "response-1",
                "usage": {"input_tokens": 100, "output_tokens": 10},
            },
        },
    ]
    rollout.write_text("\n".join(_line(row) for row in rows), encoding="utf-8")
    database = Database(tmp_path / "data" / "usage.sqlite3")
    scanner = SessionScanner(codex_home=codex_home, database=database, timezone="UTC")
    scanner.scan()
    legacy_copy = database.fetch_events()[0]
    legacy_copy.update(
        event_id="legacy-copied-prefix",
        response_id="copied-parent-response",
        ordinal=-1,
    )
    state = database.get_file_state(str(rollout.resolve()))
    assert state is not None
    database.append_file_events(
        source_file=str(rollout.resolve()),
        session_id="stable-session",
        mtime_ns=int(state["mtime_ns"]),
        size_bytes=int(state["size_bytes"]),
        events=[legacy_copy],
        parse_errors=0,
        scanned_at="2026-09-20T01:00:00+00:00",
        parser_mode=str(state["parser_mode"]),
        parser_state_json=state["parser_state_json"],
        append_safe=bool(state["append_safe"]),
    )

    archived_rollout = archive / rollout.name
    rollout.replace(archived_rollout)
    database.set_metadata("scanner_parser_version", "older-parser")
    scanner = SessionScanner(codex_home=codex_home, database=database, timezone="UTC")
    scanner.scan()

    events = database.fetch_events()
    assert len(events) == 1
    assert events[0]["source_file"] == str(archived_rollout.resolve())
    with database.connect() as connection:
        state_count = connection.execute("SELECT COUNT(*) FROM file_state").fetchone()[0]
        # Cutoff exclusions preserve legacy source facts for recovery/audit.
        assert connection.execute("SELECT COUNT(*) FROM usage_events").fetchone()[0] == 2
        assert connection.execute(
            "SELECT reason FROM usage_event_exclusions WHERE event_id = ? AND active = 1",
            ("legacy-copied-prefix",),
        ).fetchone()[0] == "copied_subagent_history"
    assert state_count == 1


def test_scanner_incrementally_reads_appended_lines(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    rollout = sessions / "rollout.jsonl"
    initial_rows = [
        {
            "timestamp": "2026-09-20T01:00:00Z",
            "ordinal": 0,
            "type": "session_meta",
            "payload": {"id": "incremental-session"},
        },
        {
            "timestamp": "2026-09-20T01:00:01Z",
            "ordinal": 1,
            "type": "token_usage_record",
            "payload": {
                "response_id": "response-1",
                "usage": {"input_tokens": 100, "output_tokens": 10},
            },
        },
    ]
    rollout.write_text(
        "\n".join(_line(row) for row in initial_rows) + "\n", encoding="utf-8"
    )
    database = Database(tmp_path / "data" / "usage.sqlite3")
    scanner = SessionScanner(codex_home=codex_home, database=database, timezone="UTC")
    scanner.scan()

    appended = {
        "timestamp": "2026-09-20T01:00:02Z",
        "ordinal": 2,
        "type": "token_usage_record",
        "payload": {
            "response_id": "response-2",
            "usage": {"input_tokens": 20, "output_tokens": 2},
        },
    }
    with rollout.open("a", encoding="utf-8") as stream:
        stream.write(_line(appended) + "\n")

    result = scanner.scan()

    assert result.incremental_files == 1
    assert result.stored_events == 1
    assert len(database.fetch_events()) == 2


def test_scanner_rebuilds_when_usage_records_replace_fallback(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    rollout = sessions / "rollout.jsonl"
    fallback = {
        "timestamp": "2026-09-20T01:00:01Z",
        "ordinal": 1,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "last_token_usage": {"input_tokens": 100, "output_tokens": 10}
            },
        },
    }
    rollout.write_text(_line(fallback) + "\n", encoding="utf-8")
    database = Database(tmp_path / "data" / "usage.sqlite3")
    scanner = SessionScanner(codex_home=codex_home, database=database, timezone="UTC")
    scanner.scan()

    record = {
        "timestamp": "2026-09-20T01:00:02Z",
        "ordinal": 2,
        "type": "token_usage_record",
        "payload": {
            "response_id": "response-1",
            "usage": {"input_tokens": 20, "output_tokens": 2},
        },
    }
    with rollout.open("a", encoding="utf-8") as stream:
        stream.write(_line(record) + "\n")

    result = scanner.scan()
    events = database.fetch_events()

    assert result.incremental_files == 0
    assert len(events) == 1
    assert events[0]["source_kind"] == "token_usage_record"
    assert events[0]["input_tokens"] == 20
    assert database.storage_stats()["events"] == 1
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM usage_events").fetchone()[0] == 2


def test_scanner_rebuilds_when_existing_prefix_changes(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    rollout = sessions / "rollout.jsonl"

    def record(response_id: str, ordinal: int, input_tokens: int) -> dict:
        return {
            "timestamp": f"2026-09-20T01:00:0{ordinal}Z",
            "ordinal": ordinal,
            "type": "token_usage_record",
            "payload": {
                "response_id": response_id,
                "usage": {"input_tokens": input_tokens, "output_tokens": 1},
            },
        }

    rollout.write_text(_line(record("old", 1, 100)) + "\n", encoding="utf-8")
    database = Database(tmp_path / "data" / "usage.sqlite3")
    scanner = SessionScanner(codex_home=codex_home, database=database, timezone="UTC")
    scanner.scan()

    rewritten = [record("new", 1, 20), record("appended", 2, 30)]
    rollout.write_text(
        "\n".join(_line(row) for row in rewritten) + "\n", encoding="utf-8"
    )
    result = scanner.scan()
    events = database.fetch_events()

    assert result.incremental_files == 0
    assert {event["response_id"] for event in events} == {"old", "new", "appended"}
    assert sum(event["input_tokens"] for event in events) == 150


def _metadata_scanner(
    tmp_path: Path, metadata: dict, *, usage: bool = False
) -> tuple[SessionScanner, Database, Path]:
    codex_home = tmp_path / ".codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    rollout = sessions / "rollout.jsonl"
    rows = [{"type": "session_meta", "payload": metadata}]
    if usage:
        rows.append(_usage_row("response-1", 1))
    rollout.write_text("\n".join(_line(row) for row in rows) + "\n", encoding="utf-8")
    database = Database(tmp_path / "data" / "usage.sqlite3")
    scanner = SessionScanner(codex_home=codex_home, database=database, timezone="UTC")
    return scanner, database, rollout


def _usage_row(response_id: str, ordinal: int) -> dict:
    return {
        "timestamp": f"2026-09-20T01:00:0{ordinal}Z",
        "ordinal": ordinal,
        "type": "token_usage_record",
        "payload": {
            "response_id": response_id,
            "usage": {"input_tokens": 100, "output_tokens": 10},
        },
    }


@pytest.mark.parametrize(
    ("copy_count", "same_filename"),
    [(2, False), (3, False), (2, True)],
    ids=["two-session-files", "three-session-files", "session-and-archive-copies"],
)
def test_scanner_keeps_cache_for_existing_session_copies(
    tmp_path: Path, copy_count: int, same_filename: bool
) -> None:
    scanner, database, initial = _metadata_scanner(
        tmp_path, {"id": "shared-session"}, usage=True,
    )
    rollout = initial.with_name("rollout-shared-session.jsonl")
    initial.replace(rollout)
    paths = [rollout]
    for index in range(1, copy_count):
        if same_filename:
            directory = scanner.codex_home / "archived_sessions"
            directory.mkdir()
            copy = directory / rollout.name
        else:
            copy = rollout.with_name(f"rollout-{index}-shared-session.jsonl")
        copy.write_bytes(rollout.read_bytes())
        paths.append(copy)

    first = scanner.scan()
    assert first.scanned_files == copy_count
    assert len(database.fetch_events()) == 1
    for path in paths:
        stat = path.stat()
        assert database.file_is_current(str(path.resolve()), stat.st_mtime_ns, stat.st_size)

    second = scanner.scan()
    assert second.scanned_files == 0
    assert second.unchanged_files == copy_count
    assert second.stored_events == 0

    with rollout.open("a", encoding="utf-8") as stream:
        stream.write(_line(_usage_row("response-2", 2)) + "\n")
    appended = scanner.scan()
    assert appended.scanned_files == 1
    assert appended.incremental_files == 1
    assert appended.unchanged_files == copy_count - 1
    assert appended.stored_events == 1
    events = database.fetch_events()
    assert {event["response_id"] for event in events} == {"response-1", "response-2"}
    assert sum(event["total_tokens"] for event in events) == 220
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM file_state").fetchone()[0] == copy_count

    final = scanner.scan()
    assert final.scanned_files == 0
    assert final.unchanged_files == copy_count


@pytest.mark.parametrize(
    ("metadata", "parent", "is_subagent"),
    [
        (
            {"source": {"subagent": {"thread_spawn": {"parent_thread_id": "parent"}}}},
            "parent",
            True,
        ),
        (
            {
                "source": json.dumps(
                    {"subagent": {"thread_spawn": {"parent_thread_id": "parent"}}}
                )
            },
            "parent",
            True,
        ),
        ({"parent_thread_id": " parent "}, "parent", True),
        ({"source": "cli", "forked_from_id": "parent"}, None, False),
        ({"source": "subagent", "forked_from_id": "parent"}, None, True),
        ({"source": "cli", "parent_thread_id": "CHILD"}, None, False),
        ({"source": "cli", "parent_thread_id": ["parent"]}, None, False),
        ({"source": {"unrelated": {"parent_thread_id": "parent"}}}, None, False),
    ],
)
def test_scanner_imports_explicit_parent_metadata_without_usage(
    tmp_path: Path, metadata: dict, parent: str | None, is_subagent: bool
) -> None:
    scanner, database, _ = _metadata_scanner(tmp_path, {"id": "child", **metadata})

    scanner.scan()

    assert database.fetch_events() == []
    assert database.session_metadata() == {
        "child": {"parent_session_id": parent, "is_subagent": is_subagent}
    }


def test_scanner_relationship_survives_incremental_scan_and_source_removal(tmp_path: Path) -> None:
    scanner, database, rollout = _metadata_scanner(
        tmp_path,
        {"id": "child", "parent_thread_id": "parent"},
        usage=True,
    )
    scanner.scan()
    with rollout.open("a", encoding="utf-8") as stream:
        stream.write(_line(_usage_row("response-2", 2)) + "\n")

    result = scanner.scan()
    file_state = database.get_file_state(str(rollout.resolve()))
    assert file_state is not None
    parser_state = ParserState.from_json(file_state["parser_state_json"])
    assert parser_state is not None
    assert parser_state.parent_session_id == "parent"
    assert result.incremental_files == 1
    assert len(database.fetch_events()) == 2
    assert all(event["is_subagent"] for event in database.fetch_events())

    rollout.unlink()
    scanner.scan()
    assert Database(database.path).session_metadata()["child"] == {
        "parent_session_id": "parent",
        "is_subagent": True,
    }


def test_scanner_persists_ancestors_without_usage(tmp_path: Path) -> None:
    scanner, database, rollout = _metadata_scanner(tmp_path, {"id": "root"})
    (rollout.parent / "middle.jsonl").write_text(
        _line({"type": "session_meta", "payload": {"id": "middle", "parent_thread_id": "root"}}),
        encoding="utf-8",
    )
    (rollout.parent / "leaf.jsonl").write_text(
        _line({"type": "session_meta", "payload": {"id": "leaf", "parent_thread_id": "middle"}})
        + "\n" + _line(_usage_row("response-1", 1)),
        encoding="utf-8",
    )

    scanner.scan()

    assert database.session_metadata() == {
        "root": {"parent_session_id": None, "is_subagent": False},
        "middle": {"parent_session_id": "root", "is_subagent": True},
        "leaf": {"parent_session_id": "middle", "is_subagent": True},
    }
    assert {event["session_id"] for event in database.fetch_events()} == {"leaf"}


def test_state_database_backfills_deleted_agent_sources_and_titles(tmp_path: Path) -> None:
    scanner, database, _ = _metadata_scanner(tmp_path, {"id": "parent"})
    state_path = scanner.codex_home / "state_5.sqlite"
    with closing(sqlite3.connect(state_path)) as source, source:
        source.execute("CREATE TABLE threads(id TEXT, title TEXT, source TEXT)")
        source.executemany(
            "INSERT INTO threads VALUES (?, ?, ?)",
            [
                ("parent", "主会话", "cli"),
                (
                    "deleted-child", "历史子代理",
                    json.dumps({"subagent": {"thread_spawn": {"parent_thread_id": "parent"}}}),
                ),
                ("broken-source", "保留标题", '{"subagent":'),
            ],
        )

    scanner.scan()

    assert database.session_metadata()["deleted-child"] == {
        "parent_session_id": "parent", "is_subagent": True,
    }
    assert database.session_titles() == {
        "parent": "主会话", "deleted-child": "历史子代理", "broken-source": "保留标题",
    }
    state_path.unlink()
    scanner.scan()
    assert Database(database.path).session_metadata()["deleted-child"]["parent_session_id"] == "parent"


def test_state_database_without_source_keeps_importing_titles(tmp_path: Path) -> None:
    scanner, database, _ = _metadata_scanner(tmp_path, {"id": "parent"})
    with closing(sqlite3.connect(scanner.codex_home / "state_4.sqlite")) as source, source:
        source.execute("CREATE TABLE threads(id TEXT, title TEXT)")
        source.execute("INSERT INTO threads VALUES ('parent', '旧版标题')")

    scanner.scan()

    assert database.session_titles() == {"parent": "旧版标题"}


def test_relationship_parser_upgrade_rescans_current_files_and_keeps_prices(tmp_path: Path) -> None:
    scanner, database, rollout = _metadata_scanner(
        tmp_path, {"id": "child", "parent_thread_id": "parent"}, usage=True,
    )
    database.record_price_revision({"test-price": "1"}, "2026-09-19T00:00:00+00:00")
    scanner.scan()
    original_events = database.fetch_events()
    original_prices = database.price_snapshot_data([original_events[0]["event_id"]])
    with database.connect() as connection:
        connection.execute("DELETE FROM session_metadata")
    database.set_metadata("scanner_parser_version", "3")
    assert database.file_is_current(
        str(rollout.resolve()), rollout.stat().st_mtime_ns, rollout.stat().st_size
    )

    upgraded = SessionScanner(codex_home=scanner.codex_home, database=database, timezone="UTC")
    result = upgraded.scan()

    assert result.scanned_files == 1
    assert database.get_metadata("scanner_parser_version") == SCANNER_PARSER_VERSION
    assert database.session_metadata()["child"]["parent_session_id"] == "parent"
    assert database.fetch_events() == original_events
    assert database.price_snapshot_data([original_events[0]["event_id"]]) == original_prices


@pytest.mark.parametrize("mutation", ["empty", "tail", "malformed", "deleted"])
def test_saved_conversation_usage_and_prices_survive_source_loss_and_restart(
    tmp_path: Path, mutation: str
) -> None:
    scanner, database, rollout = _metadata_scanner(
        tmp_path, {"id": "child", "parent_thread_id": "parent"}, usage=True,
    )
    rows = [
        {"type": "session_meta", "payload": {"id": "child", "parent_thread_id": "parent"}},
        {"type": "turn_context", "payload": {"model": "gpt-5.6-sol"}},
        _usage_row("response-1", 1), _usage_row("response-2", 2),
    ]
    rollout.write_text("\n".join(_line(row) for row in rows) + "\n", encoding="utf-8")
    (scanner.codex_home / "session_index.jsonl").write_text(
        _line({"id": "child", "thread_name": "保存会话历史"}), encoding="utf-8",
    )
    database.record_price_revision({"test-price": "1"}, "2026-09-19T00:00:00+00:00")
    scanner.scan()
    originals = database.fetch_events()
    prices = database.price_snapshot_data([event["event_id"] for event in originals])
    if mutation == "deleted":
        rollout.unlink()
    elif mutation == "tail":
        rollout.write_text(_line(rows[-1]) + "\n", encoding="utf-8")
    else:
        rollout.write_text("" if mutation == "empty" else "{broken\n", encoding="utf-8")
    (scanner.codex_home / "session_index.jsonl").unlink()
    scanner.scan()
    database.set_metadata("scanner_parser_version", "older-parser")
    reopened = Database(database.path)
    SessionScanner(codex_home=scanner.codex_home, database=reopened, timezone="UTC").scan()

    saved = reopened.fetch_events()
    assert {row["response_id"] for row in saved} == {"response-1", "response-2"}
    assert sum(row["total_tokens"] for row in saved) == 220
    assert all(row["session_id"] == "child" and row["model"] == "gpt-5.6-sol" for row in saved)
    assert reopened.price_snapshot_data([event["event_id"] for event in saved]) == prices
    assert reopened.session_titles()["child"] == "保存会话历史"
    assert reopened.session_metadata()["child"]["parent_session_id"] == "parent"


def test_archived_headerless_tail_retains_session_and_missing_calls(tmp_path: Path) -> None:
    scanner, database, rollout = _metadata_scanner(tmp_path, {"id": "retained-session"}, usage=True)
    renamed = rollout.with_name("rollout-retained-session.jsonl")
    rollout.replace(renamed)
    with renamed.open("a", encoding="utf-8") as stream:
        stream.write(_line(_usage_row("response-2", 2)) + "\n")
    database.record_price_revision({"test-price": "1"}, "2026-09-19T00:00:00+00:00")
    scanner.scan()
    originals = database.fetch_events()
    prices = database.price_snapshot_data([event["event_id"] for event in originals])
    archive = scanner.codex_home / "archived_sessions"
    archive.mkdir()
    archived = archive / renamed.name
    renamed.replace(archived)
    archived.write_text(_line(_usage_row("response-2", 2)) + "\n", encoding="utf-8")
    database.set_metadata("scanner_parser_version", "older-parser")
    SessionScanner(codex_home=scanner.codex_home, database=database, timezone="UTC").scan()

    saved = database.fetch_events()
    assert len(saved) == 2
    assert all(event["session_id"] == "retained-session" for event in saved)
    assert all(event["source_file"] == str(archived.resolve()) for event in saved)
    assert database.price_snapshot_data([event["event_id"] for event in saved]) == prices


def test_response_correction_updates_call_without_repricing_it(tmp_path: Path) -> None:
    scanner, database, rollout = _metadata_scanner(tmp_path, {"id": "stable"}, usage=True)
    database.record_price_revision({"test-price": "1"}, "2026-09-19T00:00:00+00:00")
    scanner.scan()
    original = database.fetch_events()[0]
    prices = database.price_snapshot_data([original["event_id"]])
    corrected = _usage_row("response-1", 1)
    corrected["payload"]["usage"] = {"input_tokens": 40, "output_tokens": 2}
    rollout.write_text(_line(corrected) + "\n", encoding="utf-8")
    database.record_price_revision({"test-price": "9"}, "2026-09-20T00:00:00+00:00")
    scanner.scan()

    assert len(database.fetch_events()) == 1
    corrected_event = database.fetch_events()[0]
    assert corrected_event["event_id"] == original["event_id"]
    assert corrected_event["total_tokens"] == 42
    assert database.price_snapshot_data([original["event_id"]]) == prices


def test_fallback_deduplicates_headerless_tail_with_shifted_line_numbers(tmp_path: Path) -> None:
    scanner, database, rollout = _metadata_scanner(tmp_path, {"id": "stable"})
    fallback = {
        "timestamp": "2026-09-20T01:00:01Z", "type": "event_msg",
        "payload": {"type": "token_count", "info": {
            "last_token_usage": {"input_tokens": 100, "output_tokens": 10},
        }},
    }
    with rollout.open("a", encoding="utf-8") as stream:
        stream.write(_line(fallback) + "\n")
    scanner.scan()
    original = database.fetch_events()[0]
    rollout.write_text(_line(fallback) + "\n", encoding="utf-8")
    scanner.scan()

    assert len(database.fetch_events()) == 1
    assert database.fetch_events()[0]["event_id"] == original["event_id"]
