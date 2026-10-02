from __future__ import annotations

import os
import stat
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .db import Database

CODEX_HOME_METADATA_KEY = "settings.codex_home"
SERVER_GRACEFUL_SHUTDOWN_SECONDS = 2


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
    codex_home_explicit: bool = False

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
            codex_home_explicit=self.codex_home_explicit or codex_home is not None,
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


def load_saved_settings(settings: Settings, database: Database) -> Settings:
    """Apply the saved UI selection unless this run explicitly chose a CLI directory."""
    if settings.codex_home_explicit:
        return settings
    saved_home = database.get_metadata(CODEX_HOME_METADATA_KEY)
    if not saved_home or not saved_home.strip():
        return settings
    try:
        path = Path(saved_home).expanduser().resolve()
    except (OSError, ValueError, RuntimeError):
        return settings
    # A disconnected drive stays selected on restart. Do not silently scan a
    # different default directory or create the missing source directory.
    return replace(settings, codex_home=path)


def validate_codex_home(value: str) -> Path:
    """Resolve an existing readable Codex root without creating source files."""
    value = value.strip()
    if not value:
        raise ValueError("Codex 目录不能为空。")
    try:
        path = Path(value).expanduser().resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError("Codex 目录不存在，请选择已有目录。") from exc
    except (OSError, ValueError, RuntimeError) as exc:
        raise ValueError("Codex 目录无法读取，请检查访问权限。") from exc
    try:
        is_directory = path.is_dir()
    except OSError as exc:
        raise ValueError("Codex 目录无法读取，请检查访问权限。") from exc
    if not is_directory:
        raise ValueError("Codex 路径必须是目录。")
    try:
        with os.scandir(path) as entries:
            next(entries, None)
        for name in ("sessions", "archived_sessions", "logs_2.sqlite"):
            child = path / name
            try:
                info = child.stat()
            except FileNotFoundError:
                continue
            is_directory = name != "logs_2.sqlite"
            if (is_directory and not stat.S_ISDIR(info.st_mode)) or (
                not is_directory and not stat.S_ISREG(info.st_mode)
            ):
                raise ValueError(
                    "Codex 目录结构无效：sessions 和 archived_sessions 必须是目录，"
                    "logs_2.sqlite 必须是文件。"
                )
            if is_directory:
                with os.scandir(child) as entries:
                    next(entries, None)
            else:
                with child.open("rb") as source:
                    source.read(1)
    except OSError as exc:
        raise ValueError("Codex 目录无法读取，请检查访问权限。") from exc
    return path
