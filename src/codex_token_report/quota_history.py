"""Confirm quota cycle changes from account-scoped observations stored locally."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .db import Database

BOUNDARY_TOLERANCE = 120
CONFIRM_AFTER = 60
CANDIDATE_TTL = 15 * 60


def account_key(account: dict, codex_home: Path) -> str | None:
    # RPC exposes identity, never tokens. Keep only a hash in our database.
    email = account.get("email")
    identifier = account.get("accountId") or account.get("id")
    if not identifier and not (isinstance(email, str) and email.strip()):
        return None
    identity = [
        str(codex_home.resolve()), identifier,
        email.strip().lower() if isinstance(email, str) else None,
    ]
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


def _usable(window: dict, now: float) -> bool:
    used = window.get("used_percent")
    reset = window.get("resets_at")
    minutes = window.get("window_minutes")
    return (
        used is not None and 0 <= used <= 100
        and minutes is not None and minutes > 0
        and reset is not None and now < reset <= now + minutes * 60 + BOUNDARY_TOLERANCE
    )


def _transition(previous: dict, current: dict, now: float) -> tuple[float | None, dict | None]:
    """Return a confirmed boundary or an early-reset candidate awaiting another read."""
    baseline = previous["baseline"]
    pending = previous.get("pending")
    before = baseline["resets_at"]
    after = current["resets_at"]
    duration = current["window_minutes"] * 60
    start = after - duration
    if now <= baseline["observed_at"] or after <= before + BOUNDARY_TOLERANCE:
        return None, None

    # The service moved to the following scheduled cycle. Usage may already have
    # increased again, so a percentage drop is not required at a known boundary.
    if (
        baseline["observed_at"] < before <= now
        and abs(start - before) <= BOUNDARY_TOLERANCE
        and (baseline["used_percent"] > 0 or current["used_percent"] > 0)
    ):
        return before, None

    # An earlier reset needs a usage drop, a new full-length cycle starting
    # between observations, and two consistent reads at least a minute apart.
    # Mere percentage corrections or an unused rolling timer do not count.
    if (
        now < before
        and baseline["used_percent"] - current["used_percent"] >= 1
        and baseline["observed_at"] < start <= now
    ):
        if pending and (
            0 <= now - pending["observed_at"] <= CANDIDATE_TTL
            and abs(after - pending["resets_at"]) <= BOUNDARY_TOLERANCE
            and current["used_percent"] >= pending["used_percent"]
        ):
            if now - pending["observed_at"] >= CONFIRM_AFTER:
                return pending["reset_at"], None
            return None, pending
        return None, {**current, "reset_at": start, "observed_at": now}
    return None, None


class QuotaHistory:
    def __init__(self, database: Database, timezone: str):
        self.database = database
        self.timezone = ZoneInfo(timezone)

    @staticmethod
    def _store_reset(connection, key: str, window: dict, reset: float, now: float, method: str):
        if method == "estimated":
            nearby = connection.execute(
                """SELECT 1 FROM quota_reset_events WHERE account_key = ? AND limit_id = ?
                AND window_minutes = ? AND ABS(reset_at - ?) <= ?""",
                (key, window["limit_id"], window["window_minutes"], reset, BOUNDARY_TOLERANCE),
            ).fetchone()
            if nearby:
                return
        else:
            # Replace a nearby estimate with the observed boundary, avoiding two
            # entries for the same reset when timestamps differ slightly.
            connection.execute(
                """DELETE FROM quota_reset_events WHERE account_key = ? AND limit_id = ?
                AND window_minutes = ? AND method = 'estimated' AND ABS(reset_at - ?) <= ?""",
                (key, window["limit_id"], window["window_minutes"], reset, BOUNDARY_TOLERANCE),
            )
        connection.execute(
            """INSERT INTO quota_reset_events
            (account_key, limit_id, limit_name, window_minutes, reset_at, detected_at, method)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_key, limit_id, window_minutes, reset_at) DO UPDATE SET
                method = excluded.method, detected_at = excluded.detected_at
            WHERE quota_reset_events.method = 'estimated' AND excluded.method != 'estimated'""",
            (key, window["limit_id"], window["limit_name"], window["window_minutes"], reset, now, method),
        )

    def observe(self, key: str, quota: dict, now: float) -> list[dict]:
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload_json FROM quota_snapshot_state WHERE account_key = ?", (key,)
            ).fetchone()
            state = json.loads(row["payload_json"]) if row else {}
            previous = state.get("windows", {}) if state.get("plan_type") == quota["plan_type"] else {}
            # A partial/credits-only response does not erase earlier evidence.
            windows = previous.copy()
            for window in quota["windows"]:
                if not _usable(window, now):
                    continue
                # A slot, duration, or plan change starts a new baseline.
                lane = json.dumps([window["limit_id"], window["slot"], window["window_minutes"]])
                for stored_lane, stored in list(windows.items()):
                    baseline = stored["baseline"]
                    if (
                        baseline["limit_id"] == window["limit_id"]
                        and baseline["slot"] == window["slot"]
                        and baseline["window_minutes"] != window["window_minutes"]
                    ):
                        del windows[stored_lane]
                old = previous.get(lane)
                current = {**window, "observed_at": now}
                reset, pending = _transition(old, current, now) if old else (None, None)
                if reset is not None:
                    self._store_reset(
                        connection, key, window, reset, now,
                        "scheduled" if reset == old["baseline"]["resets_at"] else "early",
                    )
                # A used window gives an estimate for the current cycle only.
                # Never extrapolate older missing cycles or unused rolling timers.
                inferred = current["resets_at"] - current["window_minutes"] * 60
                if current["used_percent"] > 0 and 0 <= inferred <= now:
                    self._store_reset(connection, key, window, inferred, now, "estimated")
                windows[lane] = {
                    "baseline": old["baseline"] if pending else current,
                    "pending": pending,
                }
            connection.execute(
                """INSERT INTO quota_snapshot_state(account_key, payload_json) VALUES (?, ?)
                ON CONFLICT(account_key) DO UPDATE SET payload_json = excluded.payload_json""",
                (key, json.dumps({"plan_type": quota["plan_type"], "windows": windows})),
            )
        return self.records(key, now, confirmed_only=True)

    def records(self, key: str, now: float, *, confirmed_only: bool = False) -> list[dict]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT limit_id, limit_name, window_minutes, reset_at, detected_at, method
                FROM quota_reset_events WHERE account_key = ? AND reset_at <= ?
                AND (? = 0 OR method != 'estimated')
                ORDER BY reset_at DESC, limit_id, window_minutes""", (key, now, confirmed_only),
            ).fetchall()
        return [
            {
                **dict(row),
                "confidence": "estimated" if row["method"] == "estimated" else "confirmed",
                "time_estimated": row["method"] in {"estimated", "early"},
                "date": datetime.fromtimestamp(row["reset_at"], self.timezone).date().isoformat(),
                "reset_at": datetime.fromtimestamp(row["reset_at"], UTC).isoformat(),
                "detected_at": datetime.fromtimestamp(row["detected_at"], UTC).isoformat(),
            }
            for row in rows
        ]
