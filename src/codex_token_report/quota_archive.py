"""Keep public account quota reads independently of the live connection."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from .db import Database


class QuotaArchive:
    def __init__(self, database: Database, codex_home: Path):
        self.database = database
        self.home_key = hashlib.sha256(
            os.path.normcase(str(codex_home.resolve())).encode(),
        ).hexdigest()
        with database.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS quota_account_reads (
                    id INTEGER PRIMARY KEY,
                    home_key TEXT NOT NULL,
                    account_key TEXT NOT NULL,
                    fetched_at REAL NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(home_key, account_key, fetched_at)
                );
                CREATE INDEX IF NOT EXISTS idx_quota_account_read_home
                ON quota_account_reads(home_key, fetched_at DESC, id DESC);
                CREATE INDEX IF NOT EXISTS idx_quota_account_read_identity
                ON quota_account_reads(home_key, account_key, fetched_at DESC, id DESC);
            """)

    def save(self, key: str, quota: dict) -> None:
        # Persist only our normalized public fields, never the RPC account or secrets.
        fields = (
            "source", "plan_type", "windows", "credits", "reset_credits_available",
            "reset_credits", "reset_credits_details_available", "fetched_at", "checked_at",
        )
        payload = {field: quota.get(field) for field in fields}
        payload.update(status="ready", message=None)
        fetched = datetime.fromisoformat(quota["fetched_at"]).timestamp()
        with self.database.connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO quota_account_reads
                (home_key, account_key, fetched_at, payload_json) VALUES (?, ?, ?, ?)""",
                (self.home_key, key, fetched, json.dumps(payload, allow_nan=False)),
            )

    def latest(self, key: str | None = None) -> tuple[str, dict] | None:
        where = "home_key = ?"
        params: tuple = (self.home_key,)
        if key:
            where += " AND account_key = ?"
            params += (key,)
        with self.database.connect() as connection:
            row = connection.execute(
                f"""SELECT account_key, payload_json FROM quota_account_reads
                WHERE {where} ORDER BY fetched_at DESC, id DESC LIMIT 1""", params,
            ).fetchone()
        if row:
            return row["account_key"], json.loads(row["payload_json"])
        # Older versions saved quota history before the directory index existed.
        # These local records are never evidence of the current login or directory.
        params = (key,) if key else ()
        identity = "AND account_key = ?" if key else ""
        with self.database.connect() as connection:
            row = connection.execute(
                f"""SELECT account_key, fetched_at AS observed_at FROM quota_value_observations
                WHERE account_key NOT IN (SELECT account_key FROM quota_account_reads)
                {identity} ORDER BY fetched_at DESC, id DESC LIMIT 1""", params,
            ).fetchone()
            if row is None:
                row = connection.execute(
                    f"""SELECT account_key, detected_at AS observed_at FROM quota_reset_events
                    WHERE account_key NOT IN (SELECT account_key FROM quota_account_reads)
                    {identity} ORDER BY detected_at DESC LIMIT 1""", params,
                ).fetchone()
        if row is None:
            return None
        return row["account_key"], {
            "legacy": True,
            "fetched_at": datetime.fromtimestamp(row["observed_at"], UTC).isoformat(),
        }
