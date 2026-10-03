"""Read account quotas through the local Codex CLI, without handling OAuth secrets."""

from __future__ import annotations

import hashlib
import json
import math
import os
import queue
import secrets
import shutil
import sqlite3
import subprocess
import threading
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self

from .db import Database
from .quota_archive import QuotaArchive
from .quota_history import QuotaHistory, account_key

if TYPE_CHECKING:
    from .quota_value_history import QuotaValueHistory


class QuotaError(Exception):
    """A safe, user-facing quota error (never includes raw RPC output)."""

    def __init__(self, message: str, *, code: str = "unavailable"):
        super().__init__(message)
        self.code = code


def _command_for_executable(executable: str | None) -> list[str] | None:
    if not executable:
        return None
    if Path(executable).suffix.lower() not in {".cmd", ".bat", ".ps1"}:
        return [executable]
    # npm's Windows shim cannot be launched directly without a shell.
    if executable and os.name == "nt":
        script = Path(executable).parent / "node_modules/@openai/codex/bin/codex.js"
        node = shutil.which("node")
        if script.is_file() and node:
            return [node, str(script)]
    return None


def _desktop_codex_candidates() -> list[Path]:
    """The Windows desktop app extracts its CLI into versioned local directories."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData/Local"
    binary_dir = base / "OpenAI/Codex/bin"
    candidates = []
    try:
        for candidate in [binary_dir / "codex.exe", *binary_dir.glob("*/codex.exe")]:
            try:
                if candidate.is_file():
                    candidates.append((candidate.stat().st_mtime_ns, candidate))
            except OSError:
                continue
    except OSError:
        pass
    # Version directory names are hashes, so use modification time, not their names.
    return [path for _, path in sorted(candidates, key=lambda item: item[0], reverse=True)]


def _codex_command() -> list[str]:
    configured = os.environ.get("CODEX_TOKEN_REPORT_CODEX_BIN", "").strip().strip('"')
    if configured:
        executable = os.path.expandvars(str(Path(configured).expanduser()))
        executable = shutil.which(executable) or executable
        if not Path(executable).is_file():
            raise QuotaError("CODEX_TOKEN_REPORT_CODEX_BIN 指向的文件不存在，请检查路径。")
        command = _command_for_executable(executable)
        if command:
            return command
        raise QuotaError("无法使用配置的 Codex CLI，请指定 codex.exe 的路径。")
    for name in ("codex.exe", "codex"):
        command = _command_for_executable(shutil.which(name))
        if command:
            return command
    if os.name == "nt":
        candidates = _desktop_codex_candidates()
        if candidates:
            return [str(candidates[0])]
    raise QuotaError(
        "未找到 Codex CLI。请安装 CLI，或设置 CODEX_TOKEN_REPORT_CODEX_BIN。", code="cli_missing",
    )


class CodexRPC:
    def __init__(self, codex_home: Path, timeout: float = 30):
        self.codex_home = codex_home
        self.timeout = timeout
        self.messages: queue.Queue[str | None] = queue.Queue()
        self.request_id = 0

    def __enter__(self) -> Self:
        env = {**os.environ, "CODEX_HOME": str(self.codex_home)}
        self.deadline = time.monotonic() + self.timeout
        try:
            self.process = subprocess.Popen(
                [*_codex_command(), "-s", "read-only", "-a", "never", "app-server"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except OSError as exc:
            raise QuotaError("无法启动 Codex CLI，请检查可执行文件路径。") from exc
        self.reader = threading.Thread(target=self._read_lines, daemon=True)
        self.reader.start()
        try:
            self.request(
                "initialize",
                {"clientInfo": {"name": "codex_token_report", "version": "0.5.0"}},
            )
            self._send({"method": "initialized", "params": {}})
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def _read_lines(self) -> None:
        try:
            for line in self.process.stdout:
                self.messages.put(line)
        finally:
            self.messages.put(None)

    def _send(self, payload: dict) -> None:
        try:
            self.process.stdin.write(json.dumps(payload) + "\n")
            self.process.stdin.flush()
        except (OSError, ValueError) as exc:
            raise QuotaError("Codex 额度连接已中断，请稍后刷新。") from exc

    def request(self, method: str, params: dict | None = None) -> dict:
        self.request_id += 1
        self._send({"id": self.request_id, "method": method, "params": params or {}})
        while True:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise QuotaError("读取 Codex 额度超时，请稍后刷新。", code="timeout")
            try:
                line = self.messages.get(timeout=remaining)
            except queue.Empty as exc:
                raise QuotaError("读取 Codex 额度超时，请稍后刷新。", code="timeout") from exc
            if line is None:
                raise QuotaError("Codex 额度连接已中断，请检查 CLI 和登录状态。")
            try:
                message = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(message, dict) or message.get("id") != self.request_id:
                continue
            if "error" in message:
                error = message["error"]
                detail = str(error.get("message", "")).lower() if isinstance(error, dict) else ""
                auth_error = any(term in detail for term in (
                    "401", "unauthorized", "token expired", "token has expired",
                    "authentication required", "invalid access token",
                ))
                raise QuotaError(
                    "Codex 无法读取额度，请检查 ChatGPT 登录状态或稍后重试。",
                    code="authentication" if auth_error else "rpc_error",
                )
            result = message.get("result")
            if not isinstance(result, dict):
                raise QuotaError("Codex 返回的额度格式不兼容，请更新 CLI。")
            return result

    def __exit__(self, *_: object) -> None:
        # Closing stdin normally shuts down app-server; forcibly stop bounded hangs.
        with suppress(OSError):
            self.process.stdin.close()
        try:
            self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=3)
        self.reader.join(timeout=1)
        self.process.stdout.close()


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _plan(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def normalize_quota(account: dict, response: dict) -> dict:
    """Whitelist public fields and preserve missing values as unknown, not zero."""
    legacy = response.get("rateLimits")
    legacy = legacy if isinstance(legacy, dict) else {}
    buckets = response.get("rateLimitsByLimitId")
    buckets = (
        {str(key): value for key, value in buckets.items() if isinstance(value, dict)}
        if isinstance(buckets, dict)
        else {}
    )
    if not buckets and legacy:
        buckets = {legacy.get("limitId") or "codex": legacy}
    main = buckets.get("codex", legacy)
    windows = []
    for limit_id, bucket in buckets.items():
        for slot in ("primary", "secondary"):
            window = bucket.get(slot)
            if not isinstance(window, dict):
                continue
            used = _finite_number(window.get("usedPercent"))
            duration = _finite_number(window.get("windowDurationMins"))
            reset = _finite_number(window.get("resetsAt"))
            if reset is not None:
                try:
                    datetime.fromtimestamp(reset, UTC)
                except (ValueError, OSError, OverflowError):
                    reset = None
            windows.append(
                {
                    "limit_id": limit_id,
                    "limit_name": _plan(bucket.get("limitName")) or limit_id,
                    "slot": slot,
                    "used_percent": used,
                    "remaining_percent": max(0, min(100, 100 - used)) if used is not None else None,
                    "window_minutes": duration if duration is not None and duration > 0 else None,
                    "resets_at": reset,
                }
            )
    credits = main.get("credits")
    credits = credits if isinstance(credits, dict) else None
    resets = response.get("rateLimitResetCredits")
    reset_credits = []
    if isinstance(resets, dict) and isinstance(resets.get("credits"), list):
        for credit in resets["credits"]:
            if not isinstance(credit, dict) or credit.get("status") != "available":
                continue
            expires_at = _finite_number(credit.get("expiresAt"))
            expiry_known = "expiresAt" in credit and credit["expiresAt"] is None
            if expires_at is not None:
                try:
                    datetime.fromtimestamp(expires_at, UTC)
                except (ValueError, OSError, OverflowError):
                    expires_at = None
                else:
                    expiry_known = True
            reset_credits.append({
                "title": _plan(credit.get("title")),
                "expires_at": expires_at,
                "expiry_known": expiry_known,
            })
    return {
        "status": "ready",
        "message": None,
        "source": "codex-app-server",
        "plan_type": _plan(main.get("planType")) or _plan(account.get("planType")),
        "windows": windows,
        "credits": (
            {
                "balance": _finite_number(credits.get("balance")),
                "has_credits": credits.get("hasCredits")
                if isinstance(credits.get("hasCredits"), bool) else None,
                "unlimited": credits.get("unlimited")
                if isinstance(credits.get("unlimited"), bool) else None,
            }
            if credits is not None else None
        ),
        "reset_credits_available": (
            _finite_number(resets.get("availableCount")) if isinstance(resets, dict) else None
        ),
        "reset_credits": reset_credits,
        "reset_credits_details_available": isinstance(resets, dict) and isinstance(resets.get("credits"), list),
    }


class QuotaService:
    """Cache live quotas; persist only hashed identity and quota cycle evidence."""

    def __init__(
        self, codex_home: Path, cache_seconds: float = 60,
        *, database: Database | None = None, timezone: str = "Asia/Taipei",
        value_history: QuotaValueHistory | None = None,
    ):
        self.codex_home = codex_home
        self.cache_seconds = cache_seconds
        self.lock = threading.Lock()
        self.cached: dict | None = None
        self.checked = 0.0
        self.history = QuotaHistory(database, timezone) if database else None
        self.scope_salt = secrets.token_hex(16)
        self.value_history = value_history
        self.archive = QuotaArchive(database, codex_home) if database else None
        self._active_account_key: str | None = None
        self._history_account_key: str | None = None

    def _fetch(self) -> dict:
        with CodexRPC(self.codex_home) as rpc:
            auth_refreshed = False
            try:
                account = rpc.request("account/read", {"refreshToken": False}).get("account")
            except QuotaError as exc:
                if exc.code != "authentication":
                    raise
                auth_refreshed = True
                account = rpc.request("account/read", {"refreshToken": True}).get("account")
            if not isinstance(account, dict):
                raise QuotaError(
                    "Codex 尚未登录，请先在 Codex 中登录 ChatGPT 账号。", code="logged_out",
                )
            if account.get("type") in {"apiKey", "amazonBedrock"}:
                return {
                    **self._empty("unavailable", "当前使用 API Key / Bedrock，无法读取订阅额度。"),
                    "plan_type": "API Key" if account["type"] == "apiKey" else "Amazon Bedrock",
                }
            try:
                response = rpc.request("account/rateLimits/read")
            except QuotaError as exc:
                if exc.code == "authentication" and not auth_refreshed:
                    auth_refreshed = True
                    # Retry authentication once. CLI owns all credential handling.
                    try:
                        refreshed = rpc.request("account/read", {"refreshToken": True}).get("account")
                        if not isinstance(refreshed, dict) or refreshed.get("type") != "chatgpt":
                            raise QuotaError("刷新登录后无法识别 ChatGPT 账号。", code="logged_out")
                        account = refreshed
                        response = rpc.request("account/rateLimits/read")
                    except QuotaError as retry:
                        if retry.code == "logged_out":
                            raise
                        exc = retry
                    else:
                        exc = None
                if exc is not None:
                    result = self._empty("unavailable", str(exc))
                    result.update(
                        _account_key=account_key(account, self.codex_home),
                        plan_type=_plan(account.get("planType")), error_code=exc.code,
                    )
                    return result
            result = normalize_quota(account, response)
            result["_account_key"] = account_key(account, self.codex_home)
            return result

    @staticmethod
    def _empty(status: str, message: str) -> dict:
        return {
            "status": status, "message": message, "source": "codex-app-server",
            "plan_type": None, "windows": [], "credits": None,
            "reset_credits_available": None,
            "reset_credits": [],
            "reset_credits_details_available": False,
            "reset_events": [],
            "reset_records": [],
        }

    def read(self, *, force: bool = False) -> dict:
        requested = time.monotonic()
        observed_cache = self.cached
        with self.lock:
            # Simultaneous manual refreshes share the refresh that just finished.
            if self.cached is not None and (
                self.cached is not observed_cache
                or (not force and requested - self.checked < self.cache_seconds)
            ):
                return self.cached
            try:
                result = self._fetch()
            except QuotaError as exc:
                result = self._empty("unavailable", str(exc))
                result["error_code"] = exc.code
            except (OSError, ValueError, TypeError, subprocess.SubprocessError):
                result = self._empty("error", "读取额度失败，请检查 Codex CLI 后重试。")
            result["checked_at"] = datetime.now(UTC).isoformat()
            result["fetched_at"] = result["checked_at"] if result["status"] == "ready" else None
            key = result.pop("_account_key", None)
            self._active_account_key = key
            history_key = key
            saved = None
            result["archive_status"] = "disabled" if not self.archive else "available"
            if self.archive:
                try:
                    if result["status"] == "ready" and key:
                        self.archive.save(key, result)
                    if key or result["status"] != "ready":
                        saved = self.archive.latest(key)
                    if not key and saved and result["status"] != "ready":
                        history_key = saved[0]
                except (sqlite3.Error, OSError, ValueError, TypeError):
                    result["archive_status"] = "error"
            self._history_account_key = history_key
            result["history_mode"] = "verified" if key else "offline" if history_key else "unavailable"
            result["history_label"] = (
                "当前账号" if key else "上次保存的账号" if history_key else None
            )
            if not key and saved and saved[1].get("legacy"):
                result["history_label"] = "旧版本本地账号档案（日志目录归属未确认）"
            result["history_directory_verified"] = bool(saved and not saved[1].get("legacy"))
            result["history_fetched_at"] = saved[1].get("fetched_at") if saved else None
            result["identity_status"] = "verified" if key else "unavailable"
            result["reset_events"] = []
            result["reset_records"] = []
            result["reset_history_scope"] = None
            result["reset_history_status"] = "unavailable"
            result["value_history_status"] = "unavailable"
            if history_key:
                result["reset_history_status"] = "disabled"
                if self.history:
                    result["reset_history_scope"] = hashlib.sha256(
                        (self.scope_salt + history_key).encode(),
                    ).hexdigest()[:16]
                    try:
                        now = datetime.fromisoformat(result["checked_at"]).timestamp()
                        if result["status"] == "ready" and key:
                            self.history.observe(key, result, now)
                        result["reset_events"] = self.history.records(
                            history_key, now, confirmed_only=True,
                        )
                        result["reset_records"] = self.history.records(
                            history_key, now,
                        )
                        result["reset_history_status"] = (
                            "recording" if result["status"] == "ready" and key else "available"
                        )
                    except (sqlite3.Error, OSError, ValueError, TypeError):
                        # History storage failure must not hide a fresh quota.
                        result["reset_history_status"] = "error"
                result["value_history_status"] = "disabled"
                if self.value_history:
                    try:
                        if result["status"] == "ready" and key:
                            self.value_history.observe(key, result)
                        result["value_history_status"] = (
                            "recording" if result["status"] == "ready" and key else "available"
                        )
                    except (sqlite3.Error, OSError, ValueError, TypeError):
                        result["value_history_status"] = "error"
            elif result["status"] == "ready":
                result["reset_history_status"] = "identity_unavailable"
                result["value_history_status"] = "identity_unavailable"
            self.cached = result
            self.checked = time.monotonic()
            return result

    def value_records(
        self, *, price_mode: str = "snapshot", offset: int = 0, limit: int = 20,
        include_current: bool = True,
    ) -> dict:
        """Read verified account history or explicitly labelled local archives, without RPC."""
        with self.lock:
            if (
                not self.value_history or not self._history_account_key or not self.cached
            ):
                return {
                    "status": "unavailable",
                    "message": "请成功读取当前账号额度后查看历史；需要可识别的账号身份。",
                    "cycles": [], "total": 0, "offset": offset, "limit": limit,
                    "has_more": False,
                }
            return {**self.value_history.records(
                self._history_account_key, price_mode=price_mode, offset=offset, limit=limit,
                current_quota=self.cached, include_current=include_current,
            ), **self._history_context()}

    def value_observations(self, cycle_id: int, *, price_mode: str = "snapshot") -> dict | None:
        with self.lock:
            if (
                not self.value_history or not self._history_account_key or not self.cached
            ):
                return None
            result = self.value_history.observations(
                self._history_account_key, cycle_id, price_mode=price_mode,
                current_quota=self.cached,
            )
            return {**result, **self._history_context()} if result else None

    def _history_context(self) -> dict:
        return {name: (self.cached or {}).get(name) for name in (
            "history_mode", "history_label", "history_fetched_at", "history_directory_verified",
        )}

    def saved_value(self, *, price_mode: str = "snapshot") -> dict | None:
        """Return frozen observed dollars, never value new logs against an old percentage."""
        with self.lock:
            if not self.value_history or not self._history_account_key or not self.cached:
                return None
            if self.cached.get("status") == "ready":
                return None
            result = self.value_history.latest_report(self._history_account_key, price_mode=price_mode)
            return {**result, **self._history_context(), "saved": True} if result else None
