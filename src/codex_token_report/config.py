from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path


def _default_codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".codex"


def _default_data_dir() -> Path:
    configured = os.environ.get("CODEX_TOKEN_REPORT_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "CodexTokenReport"
    return Path.home() / ".local" / "share" / "codex-token-report"


@dataclass(frozen=True, slots=True)
class Settings:
    codex_home: Path
    data_dir: Path
    timezone: str = "Asia/Taipei"
    host: str = "127.0.0.1"
    port: int = 8765
    scan_interval_minutes: int = 60

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            codex_home=_default_codex_home().resolve(),
            data_dir=_default_data_dir().resolve(),
            timezone=os.environ.get("CODEX_TOKEN_REPORT_TIMEZONE", "Asia/Taipei"),
            host=os.environ.get("CODEX_TOKEN_REPORT_HOST", "127.0.0.1"),
            port=int(os.environ.get("CODEX_TOKEN_REPORT_PORT", "8765")),
            scan_interval_minutes=max(
                0, int(os.environ.get("CODEX_TOKEN_REPORT_SCAN_INTERVAL_MINUTES", "60"))
            ),
        )

    @property
    def database_path(self) -> Path:
        return self.data_dir / "usage.sqlite3"

    def with_overrides(
        self,
        *,
        codex_home: Path | None = None,
        data_dir: Path | None = None,
        timezone: str | None = None,
        host: str | None = None,
        port: int | None = None,
        scan_interval_minutes: int | None = None,
    ) -> Settings:
        return replace(
            self,
            codex_home=(codex_home.expanduser().resolve() if codex_home else self.codex_home),
            data_dir=(data_dir.expanduser().resolve() if data_dir else self.data_dir),
            timezone=timezone or self.timezone,
            host=host or self.host,
            port=port if port is not None else self.port,
            scan_interval_minutes=(
                max(0, scan_interval_minutes)
                if scan_interval_minutes is not None
                else self.scan_interval_minutes
            ),
        )
