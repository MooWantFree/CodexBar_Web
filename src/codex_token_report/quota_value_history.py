"""Keep immutable, account-scoped snapshots of observed quota dollar values."""

from __future__ import annotations

import json
from datetime import timedelta

from .db import Database
from .pricing_store import PricingStore
from .quota_history import BOUNDARY_TOLERANCE
from .quota_value import _number, _recorded_start, _utc_time, build_quota_value_report


class QuotaValueHistory:
    def __init__(self, database: Database, pricing: PricingStore, timezone: str):
        self.database = database
        self.pricing = pricing
        self.timezone = timezone

    @staticmethod
    def _key(account_key: str) -> str | None:
        return account_key.strip() if isinstance(account_key, str) and account_key.strip() else None

    @staticmethod
    def _plan(quota: dict) -> str:
        plan = quota.get("plan_type")
        return plan.strip() if isinstance(plan, str) else ""

    @staticmethod
    def _mode(price_mode: str) -> None:
        if price_mode not in {"snapshot", "current"}:
            raise ValueError("price_mode must be snapshot or current")

    @staticmethod
    def _find_cycle(connection, key: str, plan: str, window: dict, start: float, reset: float):
        return connection.execute(
            """SELECT id FROM quota_value_cycles
            WHERE account_key = ? AND plan_type = ? AND limit_id = ? AND slot = ?
              AND window_minutes = ? AND ABS(resets_at - ?) <= ?
              AND ABS(cycle_start_at - ?) <= ?
            ORDER BY ABS(resets_at - ?), ABS(cycle_start_at - ?), id DESC LIMIT 1""",
            (key, plan, window["limit_id"], window["slot"], window["window_minutes"],
             reset, BOUNDARY_TOLERANCE, start, BOUNDARY_TOLERANCE, reset, start),
        ).fetchone()

    def observe(self, account_key: str, quota: dict) -> None:
        key = self._key(account_key)
        if key is None or not isinstance(quota, dict) or quota.get("status") != "ready":
            return
        fetched = _utc_time(quota.get("fetched_at"))
        if fetched is None:
            return
        epoch = fetched.timestamp()
        with self.database.connect() as connection:
            existing = connection.execute(
                "SELECT 1 FROM quota_value_observations WHERE account_key = ? AND fetched_at = ?",
                (key, epoch),
            ).fetchone()
        if existing:
            return
        last_scan = self.database.get_metadata("last_scan")
        try:
            last_scan = json.loads(last_scan) if last_scan else None
        except (TypeError, ValueError):
            last_scan = None
        # Pricing capture writes to the database, so calculate outside our write
        # transaction. Persist both modes together and check again for races.
        reports = [build_quota_value_report(
            quota, self.database, self.pricing, price_mode=mode, timezone=self.timezone,
        ) for mode in ("snapshot", "current")]
        plan = self._plan(quota)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute(
                "SELECT 1 FROM quota_value_observations WHERE account_key = ? AND fetched_at = ?",
                (key, epoch),
            ).fetchone():
                return
            for report in reports:
                if report["status"] != "ready":
                    continue
                for window in report["windows"]:
                    start = _utc_time(window.get("cycle_start_at"))
                    reset = _utc_time(window.get("resets_at"))
                    if start is None or reset is None or any(
                        not isinstance(window.get(field), str) or not window[field].strip()
                        for field in ("limit_id", "slot")
                    ):
                        continue
                    cycle = self._find_cycle(
                        connection, key, plan, window, start.timestamp(), reset.timestamp(),
                    )
                    if cycle:
                        cycle_id = cycle["id"]
                    else:
                        cycle_id = connection.execute(
                            """INSERT INTO quota_value_cycles
                            (account_key, plan_type, limit_id, slot, window_minutes,
                             cycle_start_at, resets_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            (key, plan, window["limit_id"], window["slot"], window["window_minutes"],
                             start.timestamp(), reset.timestamp()),
                        ).lastrowid
                    payload = {
                        **window, "plan_type": plan or None,
                        "fetched_at": fetched.isoformat(), "price_mode": report["price_mode"],
                        "time_estimated": window["cycle_start_estimated"],
                        "last_scan": last_scan,
                    }
                    connection.execute(
                        """INSERT OR IGNORE INTO quota_value_observations
                        (cycle_id, account_key, fetched_at, price_mode, payload_json)
                        VALUES (?, ?, ?, ?, ?)""",
                        (cycle_id, key, epoch, report["price_mode"],
                         json.dumps(payload, ensure_ascii=False, allow_nan=False)),
                    )

    def _current_ids(self, connection, key: str, current_quota: dict | None) -> set[int]:
        if current_quota is None:
            return {row["cycle_id"] for row in connection.execute(
                """SELECT DISTINCT cycle_id FROM quota_value_observations
                WHERE account_key = ? AND fetched_at = (
                    SELECT MAX(fetched_at) FROM quota_value_observations WHERE account_key = ?
                )""", (key, key),
            )}
        if not isinstance(current_quota, dict) or current_quota.get("status") != "ready":
            return set()
        fetched = _utc_time(current_quota.get("fetched_at"))
        windows = current_quota.get("windows")
        if fetched is None or not isinstance(windows, list):
            return set()
        records = current_quota.get("reset_records")
        records = records if isinstance(records, list) else []
        current = set()
        for source in windows:
            if not isinstance(source, dict) or any(
                not isinstance(source.get(field), str) or not source[field].strip()
                for field in ("limit_id", "slot")
            ):
                continue
            reset = _utc_time(source.get("resets_at"))
            duration = _number(source.get("window_minutes"))
            if reset is None or reset <= fetched or duration is None or duration <= 0:
                continue
            try:
                inferred = reset - timedelta(minutes=duration)
            except OverflowError:
                continue
            window = {**source, "window_minutes": duration}
            start, _ = _recorded_start(window, inferred, records, fetched)
            start = start or inferred
            if not 0 <= start.timestamp() <= fetched.timestamp():
                continue
            cycle = self._find_cycle(
                connection, key, self._plan(current_quota), window,
                start.timestamp(), reset.timestamp(),
            )
            if cycle:
                current.add(cycle["id"])
        return current

    @staticmethod
    def _public(row, current: set[int], observation_count: int | None = None) -> dict:
        return {
            **json.loads(row["payload_json"]), "id": row["cycle_id"],
            "observation_count": observation_count if observation_count is not None
            else row["observation_count"],
            "is_current": row["cycle_id"] in current,
        }

    def records(
        self, account_key: str, *, price_mode: str = "snapshot",
        offset: int = 0, limit: int = 20, current_quota: dict | None = None,
        include_current: bool = True,
    ) -> dict:
        self._mode(price_mode)
        if (not isinstance(offset, int) or isinstance(offset, bool) or offset < 0
                or not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0):
            raise ValueError("offset must be nonnegative and limit must be positive")
        result = {"status": "ready", "cycles": [], "total": 0,
                  "offset": offset, "limit": limit, "has_more": False}
        key = self._key(account_key)
        if key is None:
            return result
        with self.database.connect() as connection:
            current = self._current_ids(connection, key, current_quota)
            excluded = tuple(sorted(current)) if not include_current else ()
            exclude_sql = (
                f" AND c.id NOT IN ({','.join('?' for _ in excluded)})" if excluded else ""
            )
            total = connection.execute(
                f"""SELECT COUNT(DISTINCT c.id) FROM quota_value_cycles c
                JOIN quota_value_observations o ON o.cycle_id = c.id AND o.account_key = c.account_key
                WHERE c.account_key = ? AND o.price_mode = ?{exclude_sql}""",
                (key, price_mode, *excluded),
            ).fetchone()[0]
            rows = connection.execute(
                f"""SELECT c.id AS cycle_id, o.payload_json,
                    (SELECT COUNT(*) FROM quota_value_observations n
                     WHERE n.cycle_id = c.id AND n.account_key = c.account_key
                       AND n.price_mode = ?) AS observation_count
                FROM quota_value_cycles c JOIN quota_value_observations o ON o.id = (
                    SELECT n.id FROM quota_value_observations n
                    WHERE n.cycle_id = c.id AND n.account_key = c.account_key AND n.price_mode = ?
                    ORDER BY n.fetched_at DESC, n.id DESC LIMIT 1
                ) WHERE c.account_key = ?{exclude_sql}
                ORDER BY o.fetched_at DESC, c.id DESC LIMIT ? OFFSET ?""",
                (price_mode, price_mode, key, *excluded, limit, offset),
            ).fetchall()
        result.update(cycles=[self._public(row, current) for row in rows], total=total,
                      has_more=offset + len(rows) < total)
        return result

    def observations(
        self, account_key: str, cycle_id: int, *, price_mode: str = "snapshot",
        current_quota: dict | None = None,
    ) -> dict | None:
        self._mode(price_mode)
        key = self._key(account_key)
        if key is None or not isinstance(cycle_id, int) or isinstance(cycle_id, bool) or cycle_id <= 0:
            return None
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT c.id AS cycle_id, o.payload_json FROM quota_value_cycles c
                JOIN quota_value_observations o ON o.cycle_id = c.id AND o.account_key = c.account_key
                WHERE c.account_key = ? AND c.id = ? AND o.price_mode = ?
                ORDER BY o.fetched_at DESC, o.id DESC""", (key, cycle_id, price_mode),
            ).fetchall()
            if not rows:
                return None
            current = self._current_ids(connection, key, current_quota)
        values = [self._public(row, current, len(rows)) for row in rows]
        return {"status": "ready", "cycle": values[0], "observations": values}

    def latest_report(self, account_key: str, *, price_mode: str = "snapshot") -> dict | None:
        """Restore one saved read without recalculating its amounts or current cycle."""
        self._mode(price_mode)
        key = self._key(account_key)
        if key is None:
            return None
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT payload_json FROM quota_value_observations
                WHERE account_key = ? AND price_mode = ? AND fetched_at = (
                    SELECT MAX(fetched_at) FROM quota_value_observations
                    WHERE account_key = ? AND price_mode = ?
                ) ORDER BY cycle_id""", (key, price_mode, key, price_mode),
            ).fetchall()
        windows = [json.loads(row["payload_json"]) for row in rows]
        if not windows:
            return None
        return {
            "status": "ready", "message": "显示最后一次保存的换算，金额与百分比保持当次读数。",
            "plan_type": windows[0].get("plan_type"),
            "fetched_at": windows[0].get("fetched_at"), "price_mode": price_mode,
            "windows": windows,
        }
