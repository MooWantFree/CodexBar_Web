"""Archive account-wide quota readings found in session logs.

A reading's session identifies its source, not the account it belongs to or the
conversation responsible for a percentage change. Only allowlisted usage
metadata is retained; message bodies, credentials and credit balances are not.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from .db import Database

SCHEMA = """
CREATE TABLE IF NOT EXISTS session_quota_observations (
    observation_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    timestamp_utc TEXT NOT NULL,
    limit_id TEXT NOT NULL,
    limit_name TEXT,
    slot TEXT NOT NULL CHECK (slot IN ('primary', 'secondary')),
    used_percent REAL NOT NULL CHECK (used_percent BETWEEN 0 AND 100),
    window_minutes REAL NOT NULL CHECK (window_minutes > 0),
    resets_at TEXT NOT NULL,
    plan_type TEXT,
    source_kind TEXT NOT NULL,
    source_file TEXT NOT NULL,
    ordinal INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_session_quota_session_time
ON session_quota_observations(session_id, timestamp_utc DESC);
CREATE INDEX IF NOT EXISTS idx_session_quota_reset
ON session_quota_observations(limit_id, slot, window_minutes, resets_at);
"""

FIELDS = (
    "observation_id", "session_id", "timestamp_utc", "limit_id", "limit_name",
    "slot", "used_percent", "window_minutes", "resets_at", "plan_type",
    "source_kind", "source_file", "ordinal",
)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        parsed = float(value)
    except (OverflowError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _timestamp(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat()
    except (ValueError, OverflowError):
        return None


def quota_candidates(
    row: dict[str, Any], *, source_file: str, line_number: int,
) -> list[dict[str, Any]]:
    """Extract quota metadata independently of whether token usage is present."""
    if row.get("type") != "event_msg":
        return []
    payload = row.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "token_count":
        return []
    limits = payload.get("rate_limits")
    if not isinstance(limits, dict):
        return []
    timestamp = _timestamp(row.get("timestamp"))
    limit_id = limits.get("limit_id")
    if timestamp is None:
        return []
    # Older logs can omit the group name. Preserve their valid windows while
    # keeping the missing identity explicit instead of guessing a quota group.
    limit_id = limit_id.strip() if isinstance(limit_id, str) and limit_id.strip() else "unknown"
    try:
        ordinal = int(row.get("ordinal", line_number))
    except (ValueError, TypeError, OverflowError):
        ordinal = line_number
    name = limits.get("limit_name")
    plan = limits.get("plan_type")
    candidates = []
    for slot in ("primary", "secondary"):
        window = limits.get(slot)
        if not isinstance(window, dict):
            continue
        used = _number(window.get("used_percent"))
        minutes = _number(window.get("window_minutes"))
        reset = _number(window.get("resets_at"))
        if (used is None or not 0 <= used <= 100 or minutes is None or minutes <= 0
                or reset is None or reset < 0):
            continue
        try:
            resets_at = datetime.fromtimestamp(reset, UTC).isoformat()
        except (ValueError, OverflowError, OSError):
            continue
        candidates.append({
            "timestamp_utc": timestamp,
            "limit_id": limit_id,
            "limit_name": name.strip() if isinstance(name, str) and name.strip() else None,
            "slot": slot,
            "used_percent": used,
            "window_minutes": minutes,
            "resets_at": resets_at,
            "plan_type": plan.strip() if isinstance(plan, str) and plan.strip() else None,
            "source_kind": "session_log",
            "source_file": source_file,
            "ordinal": ordinal,
        })
    return candidates


def finalize_quota_samples(
    candidates: Iterable[dict[str, Any]], *, session_id: str | None,
    is_subagent: bool = False, history_start_ordinal: int | None = None,
) -> list[dict[str, Any]]:
    """Assign content-based identities that survive a source move or truncation."""
    if not isinstance(session_id, str) or not session_id.strip():
        # Do not invent an account or session identity for metadata-only fragments.
        return []
    samples = {}
    for candidate in candidates:
        if (is_subagent and history_start_ordinal is not None
                and candidate["ordinal"] < history_start_ordinal):
            continue
        identity = [session_id, *(candidate[field] for field in (
            "timestamp_utc", "limit_id", "slot", "used_percent", "window_minutes",
            "resets_at", "plan_type",
        ))]
        observation_id = hashlib.sha256(
            json.dumps(identity, separators=(",", ":"), allow_nan=False).encode("utf-8")
        ).hexdigest()
        sample = {
            **candidate, "session_id": session_id, "observation_id": observation_id,
        }
        samples[observation_id] = sample
    return list(samples.values())


class SessionQuotaHistory:
    def __init__(self, database: Database):
        self.database = database
        with self.database.connect() as connection:
            connection.executescript(SCHEMA)

    def store(self, samples: Iterable[dict[str, Any]]) -> int:
        """Merge observations; absent/truncated sources never remove older samples."""
        values = [tuple(sample[field] for field in FIELDS) for sample in samples]
        if not values:
            return 0
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            before = connection.total_changes
            connection.executemany(
                f"""INSERT OR IGNORE INTO session_quota_observations
                ({', '.join(FIELDS)}) VALUES ({', '.join('?' for _ in FIELDS)})""",
                values,
            )
            return connection.total_changes - before

    def records(
        self, session_id: str | None = None, *, session_ids: Iterable[str] | None = None,
        offset: int = 0, limit: int = 100,
    ) -> dict[str, Any]:
        if (not isinstance(offset, int) or isinstance(offset, bool) or offset < 0
                or not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0):
            raise ValueError("offset must be nonnegative and limit must be positive")
        if session_id is not None and (
            not isinstance(session_id, str) or not session_id.strip()
        ):
            raise ValueError("session_id must be a nonempty string")
        if session_id is not None and session_ids is not None:
            raise ValueError("provide session_id or session_ids, not both")
        if session_ids is not None:
            if isinstance(session_ids, (str, bytes)):
                raise ValueError("session_ids must contain nonempty strings")
            identifiers = list(session_ids)
            if any(not isinstance(key, str) or not key.strip() for key in identifiers):
                raise ValueError("session_ids must contain nonempty strings")
            params = tuple(sorted(set(identifiers)))
            condition = (
                f"WHERE session_id IN ({', '.join('?' for _ in params)})"
                if params else "WHERE 0"
            )
        else:
            condition = "WHERE session_id = ?" if session_id is not None else ""
            params = (session_id,) if session_id is not None else ()
        with self.database.connect() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM session_quota_observations {condition}", params,
            ).fetchone()[0]
            rows = connection.execute(
                f"""SELECT {', '.join(FIELDS)} FROM session_quota_observations {condition}
                ORDER BY timestamp_utc DESC, observation_id LIMIT ? OFFSET ?""",
                (*params, limit, offset),
            ).fetchall()
        return {
            "status": "ready", "scope": "account_wide_observed_in_sessions",
            "samples": [dict(row) for row in rows], "total": total,
            "offset": offset, "limit": limit, "has_more": offset + len(rows) < total,
        }
