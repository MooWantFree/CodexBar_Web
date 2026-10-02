from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS usage_events (
    event_id TEXT PRIMARY KEY,
    source_file TEXT NOT NULL,
    session_id TEXT,
    ordinal INTEGER,
    is_subagent INTEGER NOT NULL DEFAULT 0,
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
    pricing_model TEXT,
    project_key TEXT,
    project_path TEXT,
    workspace_root TEXT,
    working_directory TEXT
);

CREATE INDEX IF NOT EXISTS idx_usage_date ON usage_events(local_date);
CREATE INDEX IF NOT EXISTS idx_usage_model ON usage_events(model);
CREATE INDEX IF NOT EXISTS idx_usage_source_file ON usage_events(source_file);
CREATE INDEX IF NOT EXISTS idx_usage_turn_id ON usage_events(turn_id);
CREATE INDEX IF NOT EXISTS idx_usage_timestamp ON usage_events(timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_usage_response_id ON usage_events(response_id);
CREATE INDEX IF NOT EXISTS idx_usage_fallback_identity ON usage_events(
    response_id, timestamp_utc, source_kind, input_tokens, output_tokens, total_tokens
);
CREATE TABLE IF NOT EXISTS usage_event_exclusions (
    event_id TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    detected_at TEXT NOT NULL
);
CREATE VIEW IF NOT EXISTS reportable_usage_events AS
SELECT * FROM usage_events WHERE NOT EXISTS (
    SELECT 1 FROM usage_event_exclusions x
    WHERE x.event_id = usage_events.event_id AND x.active = 1
);
CREATE TABLE IF NOT EXISTS file_state (
    source_file TEXT PRIMARY KEY,
    session_id TEXT,
    mtime_ns INTEGER NOT NULL,
    size_bytes INTEGER NOT NULL,
    event_count INTEGER NOT NULL,
    parse_errors INTEGER NOT NULL,
    scanned_at TEXT NOT NULL,
    parser_mode TEXT NOT NULL DEFAULT 'none',
    parser_state_json TEXT,
    append_safe INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS priority_turns (
    source_path TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    thread_id TEXT,
    pricing_model TEXT,
    requested_tier TEXT NOT NULL,
    trace_timestamp_utc TEXT,
    source_row_id INTEGER NOT NULL,
    PRIMARY KEY (source_path, turn_id)
);

CREATE TABLE IF NOT EXISTS trace_state (
    source_path TEXT PRIMARY KEY,
    source_identity TEXT NOT NULL,
    last_row_id INTEGER NOT NULL,
    coverage_start_utc TEXT,
    coverage_end_utc TEXT,
    scanned_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trace_coverage (
    source_path TEXT NOT NULL,
    source_identity TEXT NOT NULL,
    coverage_start_utc TEXT NOT NULL,
    coverage_end_utc TEXT NOT NULL,
    scanned_at TEXT NOT NULL,
    PRIMARY KEY (source_path, source_identity, coverage_start_utc, coverage_end_utc)
);

CREATE INDEX IF NOT EXISTS idx_trace_coverage_range
ON trace_coverage(source_path, coverage_start_utc, coverage_end_utc);

CREATE TABLE IF NOT EXISTS pricing_catalog (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    payload_json TEXT NOT NULL,
    source TEXT NOT NULL,
    fetched_at TEXT,
    refresh_attempted_at TEXT,
    refresh_error TEXT
);

CREATE TABLE IF NOT EXISTS pricing_overrides (
    model TEXT PRIMARY KEY,
    input_usd TEXT NOT NULL,
    cached_input_usd TEXT NOT NULL,
    cache_write_usd TEXT,
    output_usd TEXT NOT NULL,
    api_fast_multiplier TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS price_revisions (
    id INTEGER PRIMARY KEY,
    observed_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS event_price_snapshots (
    event_id TEXT PRIMARY KEY,
    revision_id INTEGER NOT NULL REFERENCES price_revisions(id),
    captured_at TEXT NOT NULL,
    inferred INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_price_revision_time ON price_revisions(observed_at);
CREATE TABLE IF NOT EXISTS session_titles (
    session_id TEXT PRIMARY KEY,
    title TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS session_metadata (
    session_id TEXT PRIMARY KEY,
    parent_session_id TEXT,
    is_subagent INTEGER NOT NULL DEFAULT 0,
    CHECK (parent_session_id IS NULL OR parent_session_id != session_id)
);
CREATE INDEX IF NOT EXISTS idx_session_metadata_parent
ON session_metadata(parent_session_id);

CREATE TABLE IF NOT EXISTS quota_snapshot_state (
    account_key TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quota_reset_events (
    account_key TEXT NOT NULL,
    limit_id TEXT NOT NULL,
    limit_name TEXT NOT NULL,
    window_minutes REAL NOT NULL,
    reset_at REAL NOT NULL,
    detected_at REAL NOT NULL,
    method TEXT NOT NULL,
    PRIMARY KEY (account_key, limit_id, window_minutes, reset_at)
);

CREATE TABLE IF NOT EXISTS quota_value_cycles (
    id INTEGER PRIMARY KEY,
    account_key TEXT NOT NULL,
    plan_type TEXT NOT NULL,
    limit_id TEXT NOT NULL,
    slot TEXT NOT NULL,
    window_minutes REAL NOT NULL,
    cycle_start_at REAL NOT NULL,
    resets_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_quota_value_cycle_scope
ON quota_value_cycles(account_key, plan_type, limit_id, slot, window_minutes, resets_at);

CREATE TABLE IF NOT EXISTS quota_value_observations (
    id INTEGER PRIMARY KEY,
    cycle_id INTEGER NOT NULL REFERENCES quota_value_cycles(id),
    account_key TEXT NOT NULL,
    fetched_at REAL NOT NULL,
    price_mode TEXT NOT NULL CHECK (price_mode IN ('snapshot', 'current')),
    payload_json TEXT NOT NULL,
    UNIQUE (cycle_id, fetched_at, price_mode)
);
CREATE INDEX IF NOT EXISTS idx_quota_value_observation_time
ON quota_value_observations(account_key, fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_quota_value_observation_cycle
ON quota_value_observations(cycle_id, price_mode, fetched_at DESC, id DESC);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            self._migrate_usage_events(connection)
            self._migrate_file_state(connection)
            self._migrate_trace_coverage(connection)

    @staticmethod
    def _migrate_usage_events(connection: sqlite3.Connection) -> None:
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(usage_events)").fetchall()
        }
        additions = {
            "session_id": "TEXT",
            "ordinal": "INTEGER",
            "is_subagent": "INTEGER NOT NULL DEFAULT 0",
            "service_tier": "TEXT NOT NULL DEFAULT 'unknown'",
            "tier_source": "TEXT",
            "pricing_model": "TEXT",
            "project_key": "TEXT",
            "project_path": "TEXT",
            "workspace_root": "TEXT",
            "working_directory": "TEXT",
        }
        project_columns = {
            "project_key",
            "project_path",
            "workspace_root",
            "working_directory",
        }
        requires_project_backfill = any(name not in columns for name in project_columns)
        for name, declaration in additions.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE usage_events ADD COLUMN {name} {declaration}")
        if requires_project_backfill:
            # Invalidate offsets without forgetting identities when a source has
            # subsequently been truncated and no longer contains session_meta.
            connection.execute("UPDATE file_state SET mtime_ns = -1")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_usage_project ON usage_events(project_key)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_usage_session_id ON usage_events(session_id)"
        )

    @staticmethod
    def _migrate_file_state(connection: sqlite3.Connection) -> None:
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(file_state)").fetchall()
        }
        additions = {
            "session_id": "TEXT",
            "parser_mode": "TEXT NOT NULL DEFAULT 'none'",
            "parser_state_json": "TEXT",
            "append_safe": "INTEGER NOT NULL DEFAULT 0",
        }
        for name, declaration in additions.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE file_state ADD COLUMN {name} {declaration}")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_file_state_session_id ON file_state(session_id)"
        )

    @staticmethod
    def _migrate_trace_coverage(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO trace_coverage (
                source_path, source_identity, coverage_start_utc, coverage_end_utc, scanned_at
            )
            SELECT source_path, source_identity, coverage_start_utc, coverage_end_utc, scanned_at
            FROM trace_state
            WHERE coverage_start_utc IS NOT NULL AND coverage_end_utc IS NOT NULL
            """
        )

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def file_is_current(self, source_file: str, mtime_ns: int, size_bytes: int) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT mtime_ns, size_bytes FROM file_state WHERE source_file = ?",
                (source_file,),
            ).fetchone()
        return bool(
            row
            and row["mtime_ns"] == mtime_ns
            and row["size_bytes"] == size_bytes
        )

    def get_file_state(self, source_file: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM file_state WHERE source_file = ?", (source_file,)
            ).fetchone()
        return dict(row) if row else None

    def get_moved_file_state(self, source_file: str) -> dict[str, Any] | None:
        """Recover confirmed ownership for a headerless archived rollout."""
        filename = Path(source_file).name
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM file_state WHERE session_id IS NOT NULL AND source_file != ?",
                (source_file,),
            ).fetchall()
        matches = [
            row for row in rows
            if Path(str(row["source_file"])).name == filename
            and str(row["session_id"]).casefold() in filename.casefold()
        ]
        return dict(matches[0]) if len(matches) == 1 else None

    def prepare_scanner_version(self, version: str) -> bool:
        """Force existing sources to reparse while retaining unavailable history."""
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'scanner_parser_version'"
            ).fetchone()
            if row and str(row["value"]) == version:
                return False
            connection.execute("UPDATE file_state SET mtime_ns = -1, append_safe = 0")
            connection.execute(
                """
                INSERT INTO metadata(key, value) VALUES ('scanner_parser_version', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (version,),
            )
        return True

    @staticmethod
    def _event_list(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        defaults = {
            "session_id": None,
            "ordinal": None,
            "is_subagent": 0,
            "project_key": None,
            "project_path": None,
            "workspace_root": None,
            "working_directory": None,
        }
        return [{**defaults, **event} for event in events]

    @staticmethod
    def _merge_session_aliases(
        connection: sqlite3.Connection, *, session_id: str | None, source_file: str
    ) -> None:
        if not session_id:
            return
        aliases = connection.execute(
            """
            SELECT source_file FROM file_state
            WHERE session_id = ? AND source_file != ?
            """,
            (session_id, source_file),
        ).fetchall()
        alias_paths = [str(row["source_file"]) for row in aliases]
        connection.executemany(
            """UPDATE usage_events SET source_file = ? WHERE source_file = ?
            AND (session_id = ? OR session_id IS NULL)""",
            [(source_file, path, session_id) for path in alias_paths],
        )
        connection.executemany(
            "DELETE FROM file_state WHERE source_file = ?",
            [(path,) for path in alias_paths],
        )

    @staticmethod
    def _merge_filename_aliases(
        connection: sqlite3.Connection, *, session_id: str | None, source_file: str
    ) -> None:
        if not session_id:
            return
        filename = Path(source_file).name
        if session_id.casefold() not in filename.casefold():
            return
        rows = connection.execute(
            """
            SELECT source_file FROM usage_events WHERE source_file != ?
            UNION
            SELECT source_file FROM file_state WHERE source_file != ?
            """,
            (source_file, source_file),
        ).fetchall()
        aliases = [
            str(row["source_file"])
            for row in rows
            if Path(str(row["source_file"])).name == filename
        ]
        connection.executemany(
            "UPDATE usage_events SET source_file = ? WHERE source_file = ?",
            [(source_file, path) for path in aliases],
        )
        connection.executemany(
            "DELETE FROM file_state WHERE source_file = ?", [(path,) for path in aliases]
        )

    @staticmethod
    def _merge_event_aliases(
        connection: sqlite3.Connection,
        *,
        session_id: str | None,
        source_file: str,
        event_list: list[dict[str, Any]],
    ) -> None:
        # Keep the first stored ID and price reference across metadata imports,
        # archive moves and fallback line-number changes. Explicitly different
        # sessions may have inherited the same response and stay separate.
        for event in event_list:
            parameters = {"session_id": session_id, "source_file": source_file, **event}
            existing = connection.execute(
                "SELECT * FROM usage_events WHERE event_id = :event_id", parameters
            ).fetchone()
            if existing is None:
                matches = connection.execute(
                    """
                    SELECT * FROM usage_events
                    WHERE (session_id = :session_id OR session_id IS NULL)
                      AND (
                        (:response_id IS NOT NULL AND response_id = :response_id)
                        OR (
                          response_id IS NULL
                          AND :ordinal IS NOT NULL AND ordinal IS NOT NULL
                          AND (session_id = :session_id OR source_file = :source_file)
                          AND timestamp_utc = :timestamp_utc
                          AND turn_id IS :turn_id
                          AND (source_kind = :source_kind OR
                               source_kind = 'token_count_fallback')
                          AND input_tokens = :input_tokens
                          AND output_tokens = :output_tokens
                          AND total_tokens = :total_tokens
                          AND (:model IS NULL OR model IS NULL OR model = :model)
                        )
                      )
                    """,
                    parameters,
                ).fetchall()
                if len(matches) == 1:
                    existing = matches[0]
            if existing is not None:
                event["event_id"] = str(existing["event_id"])

    @staticmethod
    def _mark_superseded_events(
        connection: sqlite3.Connection,
        *,
        source_file: str,
        session_id: str | None,
        event_list: list[dict[str, Any]],
        superseded_events: Iterable[dict[str, Any]],
        copied_history_before_ordinal: int | None,
        scanned_at: str,
    ) -> None:
        # Exclusions affect totals only; original usage and price snapshots are
        # retained, and a later confirmed import can reactivate the request.
        accepted = {event["event_id"] for event in event_list}
        superseded = Database._event_list(superseded_events)
        Database._merge_event_aliases(
            connection, source_file=source_file, session_id=session_id, event_list=superseded
        )
        upsert = """INSERT INTO usage_event_exclusions(event_id, reason, active, detected_at)
            VALUES (?, ?, 1, ?) ON CONFLICT(event_id) DO UPDATE SET
            reason=excluded.reason, active=1, detected_at=excluded.detected_at"""
        connection.executemany(
            upsert,
            [(event["event_id"], "superseded_fallback", scanned_at)
             for event in superseded if event["event_id"] not in accepted],
        )
        if session_id and copied_history_before_ordinal is not None:
            connection.execute(
                """INSERT INTO usage_event_exclusions(event_id, reason, active, detected_at)
                SELECT event_id, 'copied_subagent_history', 1, ? FROM usage_events
                WHERE ordinal < ? AND
                    (session_id = ? OR (session_id IS NULL AND source_file = ?))
                ON CONFLICT(event_id) DO UPDATE SET
                    reason=excluded.reason, active=1, detected_at=excluded.detected_at""",
                (scanned_at, copied_history_before_ordinal, session_id, source_file),
            )

    @staticmethod
    def _insert_events(
        connection: sqlite3.Connection,
        event_list: list[dict[str, Any]],
    ) -> None:
        connection.executemany(
            """
            INSERT INTO usage_events (
                event_id, source_file, session_id, ordinal, is_subagent,
                source_kind, timestamp_utc, local_date,
                model, turn_id, response_id, input_tokens, cached_input_tokens,
                cache_write_input_tokens, output_tokens, reasoning_output_tokens, total_tokens,
                service_tier, tier_source, pricing_model, project_key, project_path,
                workspace_root, working_directory
            ) VALUES (
                :event_id, :source_file, :session_id, :ordinal, :is_subagent,
                :source_kind, :timestamp_utc, :local_date,
                :model, :turn_id, :response_id, :input_tokens, :cached_input_tokens,
                :cache_write_input_tokens, :output_tokens, :reasoning_output_tokens,
                :total_tokens, :service_tier, :tier_source, :pricing_model, :project_key,
                :project_path, :workspace_root, :working_directory
            )
            ON CONFLICT(event_id) DO UPDATE SET
                source_file=excluded.source_file,
                session_id=COALESCE(excluded.session_id, usage_events.session_id),
                ordinal=excluded.ordinal,
                is_subagent=MAX(excluded.is_subagent, usage_events.is_subagent),
                source_kind=excluded.source_kind,
                timestamp_utc=excluded.timestamp_utc,
                local_date=excluded.local_date,
                model=COALESCE(excluded.model, usage_events.model),
                turn_id=COALESCE(excluded.turn_id, usage_events.turn_id),
                response_id=COALESCE(excluded.response_id, usage_events.response_id),
                input_tokens=excluded.input_tokens,
                cached_input_tokens=excluded.cached_input_tokens,
                cache_write_input_tokens=excluded.cache_write_input_tokens,
                output_tokens=excluded.output_tokens,
                reasoning_output_tokens=excluded.reasoning_output_tokens,
                total_tokens=excluded.total_tokens,
                service_tier=CASE WHEN excluded.service_tier = 'unknown'
                    THEN usage_events.service_tier ELSE excluded.service_tier END,
                tier_source=COALESCE(excluded.tier_source, usage_events.tier_source),
                pricing_model=CASE WHEN excluded.service_tier = 'unknown'
                    AND usage_events.service_tier = 'priority'
                    THEN COALESCE(usage_events.pricing_model, excluded.pricing_model)
                    ELSE COALESCE(excluded.pricing_model, usage_events.pricing_model) END,
                project_key=COALESCE(excluded.project_key, usage_events.project_key),
                project_path=COALESCE(excluded.project_path, usage_events.project_path),
                workspace_root=COALESCE(excluded.workspace_root, usage_events.workspace_root),
                working_directory=COALESCE(
                    excluded.working_directory, usage_events.working_directory)
            """,
            event_list,
        )
        connection.executemany(
            """UPDATE usage_event_exclusions SET active = 0 WHERE event_id = ?
            AND (? != 'token_count_fallback' OR reason != 'superseded_fallback')""",
            [(event["event_id"], event["source_kind"]) for event in event_list],
        )

    @staticmethod
    def _save_file_state(
        connection: sqlite3.Connection,
        *,
        source_file: str,
        session_id: str | None,
        mtime_ns: int,
        size_bytes: int,
        event_count: int,
        parse_errors: int,
        scanned_at: str,
        parser_mode: str,
        parser_state_json: str | None,
        append_safe: bool,
    ) -> None:
        connection.execute(
            """
            INSERT INTO file_state (
                source_file, session_id, mtime_ns, size_bytes, event_count,
                parse_errors, scanned_at, parser_mode, parser_state_json, append_safe
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_file) DO UPDATE SET
                session_id=excluded.session_id,
                mtime_ns=excluded.mtime_ns,
                size_bytes=excluded.size_bytes,
                event_count=excluded.event_count,
                parse_errors=excluded.parse_errors,
                scanned_at=excluded.scanned_at,
                parser_mode=excluded.parser_mode,
                parser_state_json=excluded.parser_state_json,
                append_safe=excluded.append_safe
            """,
            (
                source_file,
                session_id,
                mtime_ns,
                size_bytes,
                event_count,
                parse_errors,
                scanned_at,
                parser_mode,
                parser_state_json,
                int(append_safe),
            ),
        )

    def replace_file_events(
        self,
        *,
        source_file: str,
        mtime_ns: int,
        size_bytes: int,
        events: Iterable[dict[str, Any]],
        parse_errors: int,
        scanned_at: str,
        session_id: str | None = None,
        parser_mode: str = "none",
        parser_state_json: str | None = None,
        append_safe: bool = False,
        superseded_events: Iterable[dict[str, Any]] = (),
        copied_history_before_ordinal: int | None = None,
    ) -> int:
        """Merge a full parse without treating absent log rows as deleted usage."""
        event_list = self._event_list(events)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._merge_filename_aliases(
                connection, session_id=session_id, source_file=source_file
            )
            self._merge_session_aliases(
                connection, session_id=session_id, source_file=source_file
            )
            self._merge_event_aliases(
                connection,
                session_id=session_id,
                source_file=source_file,
                event_list=event_list,
            )
            self._insert_events(connection, event_list)
            self._mark_superseded_events(
                connection, source_file=source_file, session_id=session_id,
                event_list=event_list, superseded_events=superseded_events,
                copied_history_before_ordinal=copied_history_before_ordinal,
                scanned_at=scanned_at,
            )
            self._save_file_state(
                connection,
                source_file=source_file,
                session_id=session_id,
                mtime_ns=mtime_ns,
                size_bytes=size_bytes,
                event_count=len(event_list),
                parse_errors=parse_errors,
                scanned_at=scanned_at,
                parser_mode=parser_mode,
                parser_state_json=parser_state_json,
                append_safe=append_safe,
            )
        return len(event_list)

    def append_file_events(
        self,
        *,
        source_file: str,
        session_id: str | None,
        mtime_ns: int,
        size_bytes: int,
        events: Iterable[dict[str, Any]],
        parse_errors: int,
        scanned_at: str,
        parser_mode: str,
        parser_state_json: str | None,
        append_safe: bool,
        superseded_events: Iterable[dict[str, Any]] = (),
        copied_history_before_ordinal: int | None = None,
    ) -> int:
        event_list = self._event_list(events)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._merge_filename_aliases(
                connection, session_id=session_id, source_file=source_file
            )
            self._merge_session_aliases(
                connection, session_id=session_id, source_file=source_file
            )
            self._merge_event_aliases(
                connection,
                session_id=session_id,
                source_file=source_file,
                event_list=event_list,
            )
            self._insert_events(connection, event_list)
            self._mark_superseded_events(
                connection, source_file=source_file, session_id=session_id,
                event_list=event_list, superseded_events=superseded_events,
                copied_history_before_ordinal=copied_history_before_ordinal,
                scanned_at=scanned_at,
            )
            event_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM usage_events WHERE source_file = ?", (source_file,)
                ).fetchone()[0]
            )
            self._save_file_state(
                connection,
                source_file=source_file,
                session_id=session_id,
                mtime_ns=mtime_ns,
                size_bytes=size_bytes,
                event_count=event_count,
                parse_errors=parse_errors,
                scanned_at=scanned_at,
                parser_mode=parser_mode,
                parser_state_json=parser_state_json,
                append_safe=append_safe,
            )
        return len(event_list)

    def set_metadata(self, key: str, value: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO metadata(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, value),
            )

    def get_metadata(self, key: str) -> str | None:
        with self.connect() as connection:
            row = connection.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else None

    def claim_pricing_refresh(self, now: datetime) -> bool:
        """Coordinate catalog retries across processes sharing this database."""
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'models_dev_last_attempt'"
            ).fetchone()
            if row:
                elapsed = (now - datetime.fromisoformat(row["value"])).total_seconds()
                if 0 <= elapsed < 15 * 60:
                    return False
            connection.execute(
                "INSERT INTO metadata(key, value) VALUES ('models_dev_last_attempt', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (now.isoformat(),),
            )
        return True

    def claim_daily_pricing_refresh(self, day: str, timezone: str) -> bool:
        with self.connect() as connection:
            result = connection.execute(
                """
                INSERT INTO metadata(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                WHERE metadata.value != excluded.value
                """,
                (f"pricing_startup_refresh_day:{timezone}", day),
            )
        return result.rowcount > 0

    def get_trace_state(self, source_path: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM trace_state WHERE source_path = ?", (source_path,)
            ).fetchone()
        return dict(row) if row else None

    def save_priority_trace(
        self,
        *,
        source_path: str,
        source_identity: str,
        last_row_id: int,
        coverage_start_utc: str | None,
        coverage_end_utc: str | None,
        scanned_at: str,
        turns: Iterable[dict[str, Any]],
        reset: bool,
    ) -> None:
        turn_list = list(turns)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            upsert = """
                INSERT INTO priority_turns (
                    source_path, turn_id, thread_id, pricing_model, requested_tier,
                    trace_timestamp_utc, source_row_id
                ) VALUES (
                    :source_path, :turn_id, :thread_id, :pricing_model, :requested_tier,
                    :trace_timestamp_utc, :source_row_id
                )
                ON CONFLICT(source_path, turn_id) DO UPDATE SET
                    thread_id=excluded.thread_id,
                    pricing_model=COALESCE(excluded.pricing_model, priority_turns.pricing_model),
                    requested_tier=excluded.requested_tier,
                    trace_timestamp_utc=excluded.trace_timestamp_utc,
                    source_row_id=excluded.source_row_id
            """
            if not reset:
                upsert += " WHERE excluded.source_row_id >= priority_turns.source_row_id"
            connection.executemany(upsert, turn_list)
            if coverage_start_utc and coverage_end_utc:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO trace_coverage (
                        source_path, source_identity, coverage_start_utc,
                        coverage_end_utc, scanned_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        source_path,
                        source_identity,
                        coverage_start_utc,
                        coverage_end_utc,
                        scanned_at,
                    ),
                )
            connection.execute(
                """
                INSERT INTO trace_state (
                    source_path, source_identity, last_row_id, coverage_start_utc,
                    coverage_end_utc, scanned_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_path) DO UPDATE SET
                    source_identity=excluded.source_identity,
                    last_row_id=excluded.last_row_id,
                    coverage_start_utc=excluded.coverage_start_utc,
                    coverage_end_utc=excluded.coverage_end_utc,
                    scanned_at=excluded.scanned_at
                """,
                (
                    source_path,
                    source_identity,
                    last_row_id,
                    coverage_start_utc,
                    coverage_end_utc,
                    scanned_at,
                ),
            )

    def classify_service_tiers(
        self,
        *,
        source_path: str,
        coverage_start_utc: str | None,
        coverage_end_utc: str | None,
    ) -> dict[str, int]:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE usage_events
                SET service_tier = 'unknown', tier_source = NULL, pricing_model = model
                """
            )
            connection.execute(
                """
                UPDATE usage_events
                SET service_tier = 'standard', tier_source = 'logs_2_absence'
                WHERE turn_id IS NOT NULL AND turn_id != ''
                  AND EXISTS (
                      SELECT 1
                      FROM trace_coverage AS coverage
                      WHERE coverage.source_path = ?
                        AND usage_events.timestamp_utc >= coverage.coverage_start_utc
                        AND usage_events.timestamp_utc <= coverage.coverage_end_utc
                  )
                """,
                (source_path,),
            )
            turns = connection.execute(
                """
                SELECT turn_id, pricing_model
                FROM priority_turns
                WHERE source_path = ?
                """,
                (source_path,),
            ).fetchall()
            connection.executemany(
                """
                UPDATE usage_events
                SET service_tier = 'priority', tier_source = 'logs_2_request',
                    pricing_model = COALESCE(?, model)
                WHERE turn_id = ?
                """,
                [(row["pricing_model"], row["turn_id"]) for row in turns],
            )
            rows = connection.execute(
                """
                SELECT service_tier, COUNT(*) AS count
                FROM reportable_usage_events
                GROUP BY service_tier
                """
            ).fetchall()
        counts = {"standard": 0, "priority": 0, "unknown": 0}
        counts.update({str(row["service_tier"]): int(row["count"]) for row in rows})
        return counts

    def fetch_events(
        self,
        start: str | None = None,
        end: str | None = None,
        project_key: str | None = None,
        *, start_at: str | None = None, end_before: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = [
            ("NOT EXISTS (SELECT 1 FROM usage_event_exclusions x "
             "WHERE x.event_id = usage_events.event_id AND x.active = 1)")
        ]
        values: list[str] = []
        if start:
            clauses.append("local_date >= ?")
            values.append(start)
        if end:
            clauses.append("local_date <= ?")
            values.append(end)
        if start_at:
            clauses.append("timestamp_utc >= ?")
            values.append(start_at)
        if end_before:
            clauses.append("timestamp_utc < ?")
            values.append(end_before)
        if project_key == "unknown":
            clauses.append("(project_key IS NULL OR project_key = '')")
        elif project_key:
            clauses.append("project_key = ?")
            values.append(project_key)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT * FROM usage_events {where} ORDER BY timestamp_utc"
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(query, values).fetchall()]

    def project_identity(self, project_key: str) -> dict[str, str | None] | None:
        if project_key == "unknown":
            where = "project_key IS NULL OR project_key = ''"
            values: tuple[str, ...] = ()
        else:
            where = "project_key = ?"
            values = (project_key,)
        with self.connect() as connection:
            row = connection.execute(
                f"""
                SELECT project_key, project_path
                FROM usage_events
                WHERE {where}
                LIMIT 1
                """,
                values,
            ).fetchone()
        return dict(row) if row else None

    def record_price_revision(self, payload: dict, observed_at: str) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            latest = connection.execute(
                "SELECT payload_json FROM price_revisions ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if not latest or latest["payload_json"] != encoded:
                connection.execute(
                    "INSERT INTO price_revisions(observed_at, payload_json) VALUES (?, ?)",
                    (observed_at, encoded),
                )

    def capture_price_snapshots(self) -> None:
        """Pin each request to our last observed price at its timestamp, once only.

        Older imports use the earliest available price and are explicitly inferred.
        Snapshots survive source reparsing, archiving, deletion and price changes.
        """
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT OR IGNORE INTO event_price_snapshots
                (event_id, revision_id, captured_at, inferred)
                SELECT e.event_id,
                    COALESCE((SELECT id FROM price_revisions
                        WHERE julianday(observed_at) <= julianday(e.timestamp_utc)
                        ORDER BY id DESC LIMIT 1),
                        (SELECT id FROM price_revisions ORDER BY id LIMIT 1)),
                    ?, CASE WHEN julianday(e.timestamp_utc) <
                        (SELECT julianday(observed_at) FROM price_revisions ORDER BY id LIMIT 1)
                        THEN 1 ELSE 0 END
                FROM usage_events e LEFT JOIN event_price_snapshots s USING(event_id)
                WHERE s.event_id IS NULL AND EXISTS(SELECT 1 FROM price_revisions)""",
                (datetime.now(UTC).isoformat(),),
            )

    def price_snapshot_data(self, event_ids: list[str]) -> tuple[dict, dict]:
        # Query the bounded selection in chunks to stay below SQLite's variable limit.
        snapshots, revisions = {}, {}
        with self.connect() as connection:
            for offset in range(0, len(event_ids), 500):
                chunk = event_ids[offset:offset + 500]
                marks = ",".join("?" for _ in chunk)
                for row in connection.execute(
                    f"SELECT * FROM event_price_snapshots WHERE event_id IN ({marks})", chunk,
                ):
                    snapshots[row["event_id"]] = dict(row)
            for revision in {row["revision_id"] for row in snapshots.values()}:
                row = connection.execute(
                    "SELECT * FROM price_revisions WHERE id = ?", (revision,),
                ).fetchone()
                revisions[revision] = dict(row)
        return snapshots, revisions

    def save_session_titles(self, titles: dict[str, str]) -> None:
        with self.connect() as connection:
            connection.executemany(
                """INSERT INTO session_titles VALUES (?, ?) ON CONFLICT(session_id)
                DO UPDATE SET title = excluded.title""", titles.items(),
            )

    def session_titles(self) -> dict[str, str]:
        with self.connect() as connection:
            return dict(connection.execute("SELECT session_id, title FROM session_titles"))

    def save_session_metadata(self, metadata: dict[str, dict[str, Any]]) -> None:
        rows = []
        for session_id, values in metadata.items():
            if not isinstance(session_id, str) or not session_id.strip():
                continue
            session_id = session_id.strip()
            parent = values.get("parent_session_id")
            parent = parent.strip() if isinstance(parent, str) else None
            if not parent or parent.casefold() == session_id.casefold():
                parent = None
            rows.append((session_id, parent, int(bool(values.get("is_subagent") or parent))))
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO session_metadata(session_id, parent_session_id, is_subagent)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    parent_session_id=COALESCE(
                        session_metadata.parent_session_id, excluded.parent_session_id
                    ),
                    is_subagent=MAX(session_metadata.is_subagent, excluded.is_subagent)
                """,
                rows,
            )

    def session_metadata(self) -> dict[str, dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM session_metadata").fetchall()
        return {
            str(row["session_id"]): {
                "parent_session_id": row["parent_session_id"],
                "is_subagent": bool(row["is_subagent"]),
            }
            for row in rows
        }

    def date_bounds(self) -> tuple[str | None, str | None]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT MIN(local_date) AS min_date, MAX(local_date) AS max_date "
                "FROM reportable_usage_events"
            ).fetchone()
        return row["min_date"], row["max_date"]

    def distinct_models(self) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT COALESCE(pricing_model, model) AS model
                FROM reportable_usage_events
                WHERE COALESCE(pricing_model, model) IS NOT NULL
                  AND COALESCE(pricing_model, model) != ''
                ORDER BY model
                """
            ).fetchall()
        return [str(row["model"]) for row in rows]

    def initialize_pricing_catalog(
        self, *, payload_json: str, source: str, fetched_at: str | None
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO pricing_catalog (
                    singleton, payload_json, source, fetched_at
                ) VALUES (1, ?, ?, ?)
                """,
                (payload_json, source, fetched_at),
            )

    def get_pricing_catalog(self) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM pricing_catalog WHERE singleton = 1"
            ).fetchone()
        if row is None:
            raise RuntimeError("pricing catalog is not initialized")
        return dict(row)

    def save_pricing_catalog(
        self,
        *,
        payload_json: str,
        source: str,
        fetched_at: str | None,
        refresh_attempted_at: str,
        refresh_error: str | None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE pricing_catalog
                SET payload_json = ?, source = ?, fetched_at = ?,
                    refresh_attempted_at = ?, refresh_error = ?
                WHERE singleton = 1
                """,
                (payload_json, source, fetched_at, refresh_attempted_at, refresh_error),
            )

    def get_pricing_overrides(self) -> dict[str, dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM pricing_overrides ORDER BY model").fetchall()
        return {str(row["model"]): dict(row) for row in rows}

    def set_pricing_override(self, *, model: str, values: dict[str, str | None]) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO pricing_overrides (
                    model, input_usd, cached_input_usd, cache_write_usd,
                    output_usd, api_fast_multiplier, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(model) DO UPDATE SET
                    input_usd=excluded.input_usd,
                    cached_input_usd=excluded.cached_input_usd,
                    cache_write_usd=excluded.cache_write_usd,
                    output_usd=excluded.output_usd,
                    api_fast_multiplier=excluded.api_fast_multiplier,
                    updated_at=excluded.updated_at
                """,
                (
                    model,
                    values["input_usd"],
                    values["cached_input_usd"],
                    values["cache_write_usd"],
                    values["output_usd"],
                    values["api_fast_multiplier"],
                    values["updated_at"],
                ),
            )

    def delete_pricing_override(self, model: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute("DELETE FROM pricing_overrides WHERE model = ?", (model,))
        return bool(cursor.rowcount)

    def _trace_coverage_stats(self, connection: sqlite3.Connection) -> dict[str, Any]:
        rows = connection.execute(
            """
            SELECT coverage_start_utc, coverage_end_utc
            FROM trace_coverage
            ORDER BY coverage_start_utc, coverage_end_utc
            """
        ).fetchall()
        if not rows:
            return {
                "trace_coverage_intervals": 0,
                "max_trace_gap_hours": 0.0,
                "last_trace_coverage_end": None,
            }
        merged_end = datetime.fromisoformat(str(rows[0]["coverage_end_utc"]))
        max_gap_seconds = 0.0
        for row in rows[1:]:
            start = datetime.fromisoformat(str(row["coverage_start_utc"]))
            end = datetime.fromisoformat(str(row["coverage_end_utc"]))
            if start > merged_end:
                max_gap_seconds = max(max_gap_seconds, (start - merged_end).total_seconds())
            merged_end = max(merged_end, end)
        return {
            "trace_coverage_intervals": len(rows),
            "max_trace_gap_hours": round(max_gap_seconds / 3600, 2),
            "last_trace_coverage_end": merged_end.isoformat(),
        }

    def storage_stats(self) -> dict[str, Any]:
        with self.connect() as connection:
            events = connection.execute("SELECT COUNT(*) FROM reportable_usage_events").fetchone()[0]
            files = connection.execute("SELECT COUNT(*) FROM file_state").fetchone()[0]
            errors = connection.execute(
                "SELECT COALESCE(SUM(parse_errors), 0) FROM file_state"
            ).fetchone()[0]
            tier_rows = connection.execute(
                "SELECT service_tier, COUNT(*) FROM reportable_usage_events GROUP BY service_tier"
            ).fetchall()
            coverage_stats = self._trace_coverage_stats(connection)
        result = {"events": int(events), "files": int(files), "parse_errors": int(errors)}
        result.update({f"{row[0]}_events": int(row[1]) for row in tier_rows})
        for tier in ("standard", "priority", "unknown"):
            result.setdefault(f"{tier}_events", 0)
        result.update(coverage_stats)
        return result
