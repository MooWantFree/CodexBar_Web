from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .db import Database

_REQUEST_MARKER = "websocket request:"
_TAGS_MARKER = "tags_json="
_PARSER_VERSION = "2"
_SUBMISSION_MARKER = "Submission sub=Submission {"
_SUBMISSION_TIER = re.compile(
    r'service_tier:\s*Some\(Some\("(?P<tier>priority|fast)"\)\)', re.IGNORECASE
)
_SUBMISSION_ID = re.compile(r'\bid:\s*"(?P<value>[^"]+)"')


@dataclass(frozen=True, slots=True)
class PriorityTraceTurn:
    source_path: str
    turn_id: str
    thread_id: str | None
    pricing_model: str | None
    requested_tier: str
    trace_timestamp_utc: str | None
    source_row_id: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PriorityTraceScanResult:
    source_path: str
    available: bool
    scanned_rows: int
    discovered_priority_turns: int
    cached_priority_turns: int
    last_row_id: int
    coverage_start_utc: str | None
    coverage_end_utc: str | None
    reset: bool
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PriorityTraceScanner:
    """Incrementally extracts per-turn Fast/Priority evidence from Codex trace logs."""

    def __init__(self, *, codex_home: Path, database: Database) -> None:
        self.path = codex_home / "logs_2.sqlite"
        self.database = database

    @staticmethod
    def _utc_iso(epoch_seconds: int | None) -> str | None:
        if epoch_seconds is None:
            return None
        return datetime.fromtimestamp(epoch_seconds, tz=UTC).isoformat()

    @staticmethod
    def _source_identity(path: Path) -> str:
        stat = path.stat()
        return f"{stat.st_dev}:{stat.st_ino}"

    @staticmethod
    def _prefix_value(name: str, text: str) -> str | None:
        pattern = re.compile(
            rf"(?:^|[\s,\[({{]){re.escape(name)}=([^\s,\])}}:]+)"
        )
        match = pattern.search(text)
        return match.group(1) if match else None

    @classmethod
    def parse_priority_row(
        cls,
        *,
        source_path: str,
        row_id: int,
        timestamp: int,
        body: str,
    ) -> PriorityTraceTurn | None:
        marker_index = body.find(_REQUEST_MARKER)
        if marker_index >= 0:
            prefix = body[:marker_index]
            raw_json = body[marker_index + len(_REQUEST_MARKER) :].strip()
            try:
                request, _ = json.JSONDecoder().raw_decode(raw_json)
            except (json.JSONDecodeError, TypeError):
                return None
            if not isinstance(request, dict) or request.get("type") != "response.create":
                return None
            tier = str(request.get("service_tier") or "").lower()
            if tier not in {"priority", "fast"}:
                return None
            turn_id = (
                cls._prefix_value("turn.id", prefix)
                or cls._prefix_value("turn_id", prefix)
                or str(request.get("turn_id") or "")
            )
            if not turn_id:
                return None
            model = str(request.get("model") or "") or None
            return PriorityTraceTurn(
                source_path=source_path,
                turn_id=turn_id,
                thread_id=cls._prefix_value("thread_id", prefix),
                pricing_model=model,
                requested_tier="priority",
                trace_timestamp_utc=cls._utc_iso(timestamp),
                source_row_id=row_id,
            )

        tags_index = body.find(_TAGS_MARKER)
        if tags_index >= 0 and _SUBMISSION_MARKER not in body:
            prefix = body[:tags_index]
            try:
                tags, _ = json.JSONDecoder().raw_decode(body[tags_index + len(_TAGS_MARKER):])
            except (json.JSONDecodeError, TypeError):
                return None
            if not isinstance(tags, dict) or tags.get("service_tier") not in {"priority", "fast"}:
                return None
            turn_id = cls._prefix_value("turn.id", prefix) or cls._prefix_value("turn_id", prefix)
            if not turn_id:
                return None
            return PriorityTraceTurn(
                source_path=source_path, turn_id=turn_id,
                thread_id=cls._prefix_value("thread_id", prefix),
                pricing_model=(cls._prefix_value("model", prefix) or "").strip('"') or None,
                requested_tier="priority", trace_timestamp_utc=cls._utc_iso(timestamp),
                source_row_id=row_id,
            )

        tier_match = _SUBMISSION_TIER.search(body)
        submission_index = body.find(_SUBMISSION_MARKER)
        if tier_match is None or submission_index < 0:
            return None
        prefix = body[:submission_index]
        submission = body[submission_index + len(_SUBMISSION_MARKER) :]
        id_match = _SUBMISSION_ID.search(submission)
        if id_match is None:
            return None
        return PriorityTraceTurn(
            source_path=source_path,
            turn_id=id_match.group("value"),
            thread_id=cls._prefix_value("thread_id", prefix),
            pricing_model=None,
            requested_tier="priority",
            trace_timestamp_utc=cls._utc_iso(timestamp),
            source_row_id=row_id,
        )

    def scan(self) -> PriorityTraceScanResult:
        source_path = str(self.path.resolve())
        if not self.path.exists():
            return PriorityTraceScanResult(
                source_path=source_path,
                available=False,
                scanned_rows=0,
                discovered_priority_turns=0,
                cached_priority_turns=0,
                last_row_id=0,
                coverage_start_utc=None,
                coverage_end_utc=None,
                reset=False,
                error="logs_2.sqlite 不存在",
            )

        previous = self.database.get_trace_state(source_path)
        version_key = "priority_parser_version:" + source_path
        reparse = self.database.get_metadata(version_key) != _PARSER_VERSION
        try:
            identity = self._source_identity(self.path)
            uri = f"{self.path.resolve().as_uri()}?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=0.25) as connection:
                connection.execute("PRAGMA query_only = ON")
                bounds = connection.execute(
                    "SELECT COALESCE(MAX(id), 0), MIN(ts), MAX(ts) FROM logs"
                ).fetchone()
                max_row_id = int(bounds[0])
                reset = bool(
                    previous
                    and (
                        str(previous["source_identity"]) != identity
                        or max_row_id < int(previous["last_row_id"])
                    )
                )
                last_row_id = 0 if reset or reparse or not previous else int(previous["last_row_id"])
                rows = connection.execute(
                    """
                    SELECT id, ts, feedback_log_body
                    FROM logs
                    WHERE id > ?
                      AND feedback_log_body IS NOT NULL
                      AND feedback_log_body LIKE '%service_tier%'
                      AND (feedback_log_body LIKE '%websocket request:%'
                           OR feedback_log_body LIKE '%Submission sub=Submission {%'
                           OR feedback_log_body LIKE '%tags_json=%')
                    ORDER BY id
                    """,
                    (last_row_id,),
                ).fetchall()
        except (OSError, sqlite3.Error) as exc:
            return PriorityTraceScanResult(
                source_path=source_path,
                available=False,
                scanned_rows=0,
                discovered_priority_turns=0,
                cached_priority_turns=0,
                last_row_id=int(previous["last_row_id"]) if previous else 0,
                coverage_start_utc=previous.get("coverage_start_utc") if previous else None,
                coverage_end_utc=previous.get("coverage_end_utc") if previous else None,
                reset=False,
                error=str(exc),
            )

        turns = [
            turn
            for row_id, timestamp, body in rows
            if (
                turn := self.parse_priority_row(
                    source_path=source_path,
                    row_id=int(row_id),
                    timestamp=int(timestamp),
                    body=str(body),
                )
            )
            is not None
        ]
        # Record the database's actual current window. Historical windows are kept
        # separately, so a gap while the app was offline is never inferred as covered.
        coverage_start = self._utc_iso(int(bounds[1])) if bounds[1] is not None else None
        coverage_end = self._utc_iso(int(bounds[2])) if bounds[2] is not None else None

        self.database.save_priority_trace(
            source_path=source_path,
            source_identity=identity,
            last_row_id=max_row_id,
            coverage_start_utc=coverage_start,
            coverage_end_utc=coverage_end,
            scanned_at=datetime.now(UTC).isoformat(),
            turns=(turn.to_dict() for turn in turns),
            reset=reset,
        )
        with self.database.connect() as connection:
            cached_turns = int(
                connection.execute(
                    "SELECT COUNT(*) FROM priority_turns WHERE source_path = ?", (source_path,)
                ).fetchone()[0]
            )
        self.database.set_metadata(version_key, _PARSER_VERSION)
        return PriorityTraceScanResult(
            source_path=source_path,
            available=True,
            scanned_rows=len(rows),
            discovered_priority_turns=len(turns),
            cached_priority_turns=cached_turns,
            last_row_id=max_row_id,
            coverage_start_utc=coverage_start,
            coverage_end_utc=coverage_end,
            reset=reset,
        )
