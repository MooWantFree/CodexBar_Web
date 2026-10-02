import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from codex_token_report.config import Settings
from codex_token_report.main import create_app
from codex_token_report.quota import (
    CodexRPC,
    QuotaError,
    QuotaService,
    _codex_command,
    _desktop_codex_candidates,
    normalize_quota,
)


def test_desktop_cli_discovery_skips_empty_versions_and_sorts_by_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    binary_dir = tmp_path / "OpenAI/Codex/bin"
    old = binary_dir / "zz-old/codex.exe"
    newest = binary_dir / "aa-new/codex.exe"
    for executable in (old, newest):
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"test")
    (binary_dir / "empty-version").mkdir()
    os.utime(old, (10, 10))
    os.utime(newest, (20, 20))
    assert _desktop_codex_candidates() == [newest, old]


@pytest.mark.skipif(os.name != "nt", reason="Windows desktop installation")
def test_cli_resolves_without_path_and_detects_desktop_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CODEX_TOKEN_REPORT_CODEX_BIN", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr("codex_token_report.quota.shutil.which", lambda _: None)
    executable = tmp_path / "OpenAI/Codex/bin/first/codex.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"test")
    os.utime(executable, (10, 10))
    assert _codex_command() == [str(executable)]
    updated = executable.parent.parent / "second/codex.exe"
    updated.parent.mkdir()
    updated.write_bytes(b"test")
    os.utime(updated, (20, 20))
    assert _codex_command() == [str(updated)]


def test_configured_cli_takes_precedence_and_reports_bad_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "custom cli/codex.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"test")
    monkeypatch.setenv("CODEX_TOKEN_REPORT_CODEX_BIN", f'"{executable}"')
    assert _codex_command() == [str(executable)]
    monkeypatch.setenv("CODEX_TOKEN_REPORT_CODEX_BIN", str(tmp_path / "missing.exe"))
    with pytest.raises(QuotaError, match="文件不存在"):
        _codex_command()


def test_cli_reports_missing_only_when_no_installation_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CODEX_TOKEN_REPORT_CODEX_BIN", raising=False)
    monkeypatch.setattr("codex_token_report.quota.shutil.which", lambda _: None)
    monkeypatch.setattr("codex_token_report.quota._desktop_codex_candidates", list)
    with pytest.raises(QuotaError, match="未找到 Codex CLI"):
        _codex_command()


def test_multiple_buckets_plan_precedence_and_credits() -> None:
    result = normalize_quota(
        {"planType": "plus", "email": "private@example.com"},
        {
            "rateLimits": {"planType": "plus", "primary": {"usedPercent": 99}},
            "rateLimitsByLimitId": {
                "codex": {
                    "planType": "prolite",
                    "primary": {"usedPercent": 2, "windowDurationMins": 10080},
                    "credits": {"balance": "0", "hasCredits": False, "unlimited": False},
                },
                "spark": {
                    "limitName": "Spark",
                    "secondary": {"usedPercent": 120, "resetsAt": 1791062171},
                },
            },
            "rateLimitResetCredits": {"availableCount": 0},
        },
    )
    assert result["plan_type"] == "prolite"
    assert [window["remaining_percent"] for window in result["windows"]] == [98, 0]
    assert result["windows"][0]["window_minutes"] == 10080
    assert result["windows"][1]["resets_at"] == 1791062171
    assert result["credits"] == {"balance": 0, "has_credits": False, "unlimited": False}
    assert result["reset_credits_available"] == 0
    assert "private@example.com" not in json.dumps(result)


def test_legacy_missing_fields_and_invalid_numbers() -> None:
    result = normalize_quota(
        {"planType": "plus"},
        {"rateLimits": {
            "planType": " ",
            "primary": {"usedPercent": None, "resetsAt": 1e100},
            "secondary": {"usedPercent": -10, "windowDurationMins": -1},
            "credits": {"balance": "NaN", "unlimited": True},
        }},
    )
    assert result["plan_type"] == "plus"
    assert result["windows"][0]["remaining_percent"] is None
    assert result["windows"][0]["resets_at"] is None
    assert result["windows"][1]["remaining_percent"] == 100
    assert result["windows"][1]["window_minutes"] is None
    assert result["credits"]["balance"] is None
    assert result["credits"]["unlimited"] is True
    empty = normalize_quota({}, {"rateLimits": None, "rateLimitsByLimitId": None})
    assert empty["windows"] == []
    assert empty["credits"] is None


def test_reset_credit_expiries_include_only_available_safe_fields() -> None:
    result = normalize_quota({}, {"rateLimitResetCredits": {
        "availableCount": 3,
        "credits": [
            {"id": "private-id", "status": "available", "title": "Full reset", "expiresAt": 1791062171},
            {"id": "another-private-id", "status": "available", "expiresAt": None},
            {"status": "redeemed", "expiresAt": 1791062171},
            {"status": "available", "expiresAt": 1e100},
        ],
    }})
    assert result["reset_credits_available"] == 3
    assert result["reset_credits_details_available"] is True
    assert result["reset_credits"] == [
        {"title": "Full reset", "expires_at": 1791062171, "expiry_known": True},
        {"title": None, "expires_at": None, "expiry_known": True},
        {"title": None, "expires_at": None, "expiry_known": False},
    ]
    assert "private-id" not in json.dumps(result)

    count_only = normalize_quota({}, {"rateLimitResetCredits": {"availableCount": 2, "credits": None}})
    assert count_only["reset_credits"] == []
    assert count_only["reset_credits_details_available"] is False


@pytest.fixture
def fake_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    script = tmp_path / "fake_cli.py"
    script.write_text('''
import json, os, sys, time
from pathlib import Path
mode = os.environ.get("QUOTA_TEST_MODE", "ready")
for line in sys.stdin:
    message = json.loads(line)
    with (Path(os.environ["CODEX_HOME"]) / "requests.jsonl").open("a") as log:
        log.write(line)
    method = message["method"]
    if "id" not in message:
        continue
    if mode == "timeout":
        time.sleep(60)
    if mode == "exit":
        sys.exit(1)
    if method == "initialize":
        result = {"userAgent": "test"}
    elif method == "account/read":
        result = {"account": None if mode == "logged_out" else
            {"type": "apiKey" if mode == "api_key" else "chatgpt", "planType": "pro"}}
    else:
        result = {"rateLimits": {"primary": {"usedPercent": 25, "windowDurationMins": 300}}}
    print("non-json startup line", flush=True)
    print(json.dumps({"method": "account/updated", "params": {}}), flush=True)
    if mode == "error" and method == "account/rateLimits/read":
        print(json.dumps({"id": message["id"], "error": {"message": "secret-token"}}), flush=True)
    else:
        print(json.dumps({"id": message["id"], "result": result}), flush=True)
''', encoding="utf-8")
    monkeypatch.setattr("codex_token_report.quota._codex_command", lambda: [sys.executable, str(script)])
    return tmp_path


def test_rpc_handshake_and_selected_codex_home(fake_cli: Path) -> None:
    result = QuotaService(fake_cli).read()
    assert result["status"] == "ready"
    assert result["windows"][0]["remaining_percent"] == 75
    requests = [json.loads(line) for line in (fake_cli / "requests.jsonl").read_text().splitlines()]
    assert [request["method"] for request in requests] == [
        "initialize", "initialized", "account/read", "account/rateLimits/read",
    ]
    assert requests[2]["params"] == {"refreshToken": False}


@pytest.mark.parametrize("mode", ["api_key", "logged_out", "error"])
def test_auth_and_rpc_errors_are_safe(
    fake_cli: Path, monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    monkeypatch.setenv("QUOTA_TEST_MODE", mode)
    result = QuotaService(fake_cli).read()
    assert result["status"] == "unavailable"
    assert result["windows"] == []
    assert result["fetched_at"] is None
    assert "secret-token" not in json.dumps(result)
    methods = [json.loads(line)["method"] for line in (fake_cli / "requests.jsonl").read_text().splitlines()]
    if mode != "error":
        assert "account/rateLimits/read" not in methods


@pytest.mark.parametrize("mode", ["timeout", "exit"])
def test_rpc_startup_failure_stops_child(
    fake_cli: Path, monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    monkeypatch.setenv("QUOTA_TEST_MODE", mode)
    rpc = CodexRPC(fake_cli, timeout=0.2)
    started = time.monotonic()
    with pytest.raises(QuotaError), rpc:
        pass
    assert time.monotonic() - started < 5
    assert rpc.process.poll() is not None
    assert not rpc.reader.is_alive()


def test_cache_refresh_failure_and_concurrent_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = QuotaService(tmp_path)
    calls = []

    def fetch():
        calls.append(1)
        return normalize_quota({"planType": "plus"}, {})

    monkeypatch.setattr(service, "_fetch", fetch)
    assert service.read()["plan_type"] == "plus"
    assert service.read()["plan_type"] == "plus"
    assert len(calls) == 1
    service.read(force=True)
    assert len(calls) == 2

    entered = threading.Event()
    release = threading.Event()

    def slow_fetch():
        calls.append(1)
        entered.set()
        assert release.wait(2)
        return normalize_quota({"planType": "pro"}, {})

    monkeypatch.setattr(service, "_fetch", slow_fetch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.read, force=True)
        assert entered.wait(1)
        second = pool.submit(service.read)
        release.set()
        assert first.result() == second.result()
    assert len(calls) == 3

    def fail_fetch():
        raise QuotaError("已退出登录")

    monkeypatch.setattr(service, "_fetch", fail_fetch)
    result = service.read(force=True)
    assert result["plan_type"] is None  # Never keep a previous account's quota on error.
    assert result["fetched_at"] is None


def test_quota_api_and_refresh(fake_cli: Path) -> None:
    app = create_app(Settings(codex_home=fake_cli, data_dir=fake_cli / "data", scan_interval_minutes=0))
    with TestClient(app) as client:
        result = client.get("/api/quota")
        assert result.status_code == 200
        assert result.json()["windows"][0]["remaining_percent"] == 75
        assert client.get("/api/quota").json()["fetched_at"] == result.json()["fetched_at"]
        assert client.post("/api/quota/refresh").json()["fetched_at"] != result.json()["fetched_at"]
