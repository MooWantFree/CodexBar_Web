import asyncio
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from codex_token_report import cli
from codex_token_report.config import CODEX_HOME_METADATA_KEY, Settings
from codex_token_report.main import create_app
from codex_token_report.quota import QuotaError, QuotaService


@pytest.fixture
def settings_app(tmp_path):
    original = tmp_path / "original-codex"
    selected = tmp_path / "selected-codex"
    (original / "sessions").mkdir(parents=True)
    (selected / "sessions").mkdir(parents=True)
    settings = Settings(codex_home=original, data_dir=tmp_path / "data", scan_interval_minutes=0)
    app = create_app(settings)
    return app, TestClient(app), settings, selected


def write_rollout(home, session):
    records = [
        {"timestamp": "2026-10-01T01:00:00Z", "type": "session_meta",
         "payload": {"id": session, "cwd": str(home)}},
        {"timestamp": "2026-10-01T01:00:01Z", "type": "turn_context",
         "payload": {"model": "gpt-6.1-sol", "turn_id": f"{session}-turn", "cwd": str(home)}},
        {"timestamp": "2026-10-01T01:00:02Z", "ordinal": 3, "type": "token_usage_record",
         "payload": {"turn_id": f"{session}-turn", "response_id": f"{session}-response",
                     "usage": {"input_tokens": 100, "cached_input_tokens": 20,
                               "output_tokens": 10, "total_tokens": 110}}},
    ]
    (home / "sessions" / f"{session}.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records), encoding="utf-8",
    )


def reading(identity="old-account", used=25):
    return {"status": "ready", "plan_type": "pro", "_account_key": identity,
            "windows": [{"limit_id": "codex", "limit_name": "Codex", "slot": "primary",
                         "used_percent": used, "remaining_percent": 100 - used,
                         "window_minutes": 300,
                         "resets_at": datetime.now(UTC).timestamp() + 3600}]}


def test_settings_api_switches_active_services_without_scanning_or_removing_history(settings_app):
    app, client, initial, selected = settings_app
    write_rollout(initial.codex_home, "old-session")
    write_rollout(selected, "new-session")
    assert client.post("/api/scan").status_code == 200
    database, old_scanner, old_quota = app.state.database, app.state.scanner, app.state.quota
    old_quota.cached = {"status": "ready", "windows": [{"remaining_percent": 75}]}
    old_quota._history_account_key = "old-account"

    assert client.get("/api/settings").json() == {
        "codex_home": str(initial.codex_home), "codex_home_exists": True,
    }
    result = client.put("/api/settings", json={"codex_home": f"  {selected}  "})
    assert result.status_code == 200
    assert result.json()["codex_home"] == str(selected.resolve())
    assert result.json()["codex_home_exists"] is True
    assert result.json()["ui_config"] == client.get("/api/ui-config").json()
    assert result.json()["ui_config"]["codexHome"] == str(selected.resolve())
    assert app.state.settings.codex_home == app.state.scanner.codex_home == selected.resolve()
    assert app.state.scanner is not old_scanner and app.state.quota is not old_quota
    assert app.state.quota.value_history is old_quota.value_history
    assert app.state.quota.archive.home_key != old_quota.archive.home_key
    assert app.state.quota.cached is None and app.state.quota._history_account_key is None
    assert app.state.database is database
    assert database.get_metadata(CODEX_HOME_METADATA_KEY) == str(selected.resolve())
    # PUT saves the directory only; scanning is an explicit follow-up request.
    assert {event["session_id"] for event in database.fetch_events()} == {"old-session"}
    assert client.post("/api/scan").json()["discovered_files"] == 1
    assert {event["session_id"] for event in database.fetch_events()} == {"old-session", "new-session"}
    assert all(name.endswith("archived_sessions") for name in json.loads(
        database.get_metadata("last_scan"),
    )["missing_directories"])
    assert client.get("/settings").status_code == client.get("/pricing").status_code == 200
    assert str(selected) in client.get("/settings").text


def test_saved_settings_reload_and_explicit_cli_precedence(settings_app, monkeypatch):
    _, client, initial, selected = settings_app
    assert client.put("/api/settings", json={"codex_home": str(selected)}).status_code == 200
    monkeypatch.setenv("CODEX_HOME", str(initial.codex_home))
    monkeypatch.setenv("CODEX_TOKEN_REPORT_DATA_DIR", str(initial.data_dir))
    restored = create_app()
    assert restored.state.settings.codex_home == selected.resolve()
    assert restored.state.scanner.codex_home == restored.state.quota.codex_home == selected.resolve()
    explicit = Settings.from_env().with_overrides(codex_home=initial.codex_home)
    assert explicit.codex_home_explicit is True
    overridden = create_app(explicit)
    assert overridden.state.settings.codex_home == initial.codex_home.resolve()
    assert overridden.state.database.get_metadata(CODEX_HOME_METADATA_KEY) == str(selected.resolve())
    assert create_app().state.settings.codex_home == selected.resolve()


@pytest.mark.parametrize("explicit", [False, True])
def test_scan_only_uses_saved_home_unless_cli_explicit(settings_app, monkeypatch, capsys, explicit):
    _, client, initial, selected = settings_app
    assert client.put("/api/settings", json={"codex_home": str(selected)}).status_code == 200
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls: initial))
    argv = ["codex-token-report", "--scan-only"]
    if explicit:
        argv.extend(["--codex-home", str(initial.codex_home)])
    monkeypatch.setattr("sys.argv", argv)
    scanned = []

    def scan(scanner):
        scanned.append(scanner.codex_home)
        return SimpleNamespace(to_dict=lambda: {"directory": str(scanner.codex_home)})

    monkeypatch.setattr(cli.SessionScanner, "scan", scan)
    cli.main()
    assert scanned == [initial.codex_home.resolve() if explicit else selected.resolve()]
    assert json.loads(capsys.readouterr().out)["directory"] == str(scanned[0])


def test_saved_disconnected_directory_stays_selected_without_creation(settings_app):
    app, _, initial, _ = settings_app
    missing = initial.codex_home.parent / "disconnected-drive"
    app.state.database.set_metadata(CODEX_HOME_METADATA_KEY, str(missing))
    restored = create_app(initial)
    assert restored.state.settings.codex_home == missing
    assert TestClient(restored).get("/api/settings").json() == {
        "codex_home": str(missing), "codex_home_exists": False,
    }
    assert not missing.exists()


@pytest.mark.parametrize("value", ["", "  ", None, 1])
def test_invalid_settings_payload_retains_active_directory(settings_app, value):
    app, client, initial, _ = settings_app
    response = client.put("/api/settings", json={"codex_home": value})
    assert response.status_code == 400
    assert app.state.settings.codex_home == initial.codex_home
    assert app.state.database.get_metadata(CODEX_HOME_METADATA_KEY) is None


def test_nonexistent_file_and_invalid_structure_paths_are_not_created(settings_app):
    app, client, initial, selected = settings_app
    missing = selected / "missing"
    assert client.put("/api/settings", json={"codex_home": str(missing)}).status_code == 400
    assert not missing.exists()
    file = selected / "file"
    file.write_text("not a directory", encoding="utf-8")
    assert client.put("/api/settings", json={"codex_home": str(file)}).json()["detail"] == "Codex 路径必须是目录。"
    broken = selected / "wrong-structure"
    broken.mkdir()
    (broken / "sessions").write_text("not a directory", encoding="utf-8")
    response = client.put("/api/settings", json={"codex_home": str(broken)})
    assert response.status_code == 400 and "目录结构无效" in response.json()["detail"]
    assert app.state.settings.codex_home == initial.codex_home


@pytest.mark.parametrize("denied_child", [None, "sessions"])
def test_unreadable_directory_returns_localized_validation_error(settings_app, monkeypatch, denied_child):
    app, client, initial, selected = settings_app
    denied = selected / denied_child if denied_child else selected
    original = __import__("os").scandir

    def scandir(path):
        if Path(path) == denied:
            raise PermissionError("fixture access denied")
        return original(path)

    monkeypatch.setattr("codex_token_report.config.os.scandir", scandir)
    response = client.put("/api/settings", json={"codex_home": str(selected)})
    assert response.status_code == 400
    assert response.json()["detail"] == "Codex 目录无法读取，请检查访问权限。"
    assert app.state.settings.codex_home == initial.codex_home


def test_metadata_failure_leaves_active_services_and_path_unchanged(settings_app, monkeypatch):
    app, client, initial, selected = settings_app
    scanner, quota = app.state.scanner, app.state.quota

    def failed_save(*_):
        raise sqlite3.OperationalError("fixture disk full")

    monkeypatch.setattr(app.state.database, "set_metadata", failed_save)
    response = client.put("/api/settings", json={"codex_home": str(selected)})
    assert response.status_code == 503
    assert response.json()["detail"] == "保存 Codex 目录失败，请稍后重试。"
    assert app.state.scanner is scanner and app.state.quota is quota
    assert app.state.settings.codex_home == initial.codex_home
    assert app.state.database.get_metadata(CODEX_HOME_METADATA_KEY) is None


def test_switch_waits_for_active_scan_then_followup_scan_uses_new_home(settings_app, monkeypatch):
    app, _, initial, selected = settings_app
    started, release, validated = threading.Event(), threading.Event(), threading.Event()
    old_scan = app.state.scanner.scan
    from codex_token_report import main

    original_validate = main.validate_codex_home

    def validate(path):
        result = original_validate(path)
        validated.set()
        return result

    def slow_scan():
        started.set()
        assert release.wait(5)
        return old_scan()

    monkeypatch.setattr(main, "validate_codex_home", validate)
    monkeypatch.setattr(app.state.scanner, "scan", slow_scan)
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as executor:
        try:
            assert started.wait(2)
            future = executor.submit(client.put, "/api/settings", json={"codex_home": str(selected)})
            assert validated.wait(2)
            assert not future.done()
            assert client.get("/api/settings").json()["codex_home"] == str(initial.codex_home)
        finally:
            release.set()
        assert future.result(timeout=5).status_code == 200
        assert app.state.scanner.codex_home == selected.resolve()
        scan = client.post("/api/scan")
        assert scan.status_code == 200
        assert scan.json()["missing_directories"] == [str(selected / "archived_sessions")]


def test_switch_waits_for_inflight_quota_and_never_reuses_old_cache_or_history(settings_app, monkeypatch):
    app, _, initial, selected = settings_app
    started, release, validated = threading.Event(), threading.Event(), threading.Event()
    old_quota = app.state.quota
    from codex_token_report import main

    original_validate = main.validate_codex_home

    def validate(path):
        result = original_validate(path)
        validated.set()
        return result

    def slow_fetch():
        started.set()
        assert release.wait(5)
        return reading()

    def unavailable(_):
        raise QuotaError("fixture offline")

    monkeypatch.setattr(main, "validate_codex_home", validate)
    monkeypatch.setattr(old_quota, "_fetch", slow_fetch)
    monkeypatch.setattr(QuotaService, "_fetch", unavailable)
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as executor:
        try:
            old_read = executor.submit(client.get, "/api/quota")
            assert started.wait(2)
            switched = executor.submit(client.put, "/api/settings", json={"codex_home": str(selected)})
            assert validated.wait(2)
            assert not switched.done()
            assert app.state.quota is old_quota
        finally:
            release.set()
        old_result = old_read.result(timeout=5).json()
        assert old_result["windows"][0]["remaining_percent"] == 75
        assert switched.result(timeout=5).status_code == 200
        assert app.state.quota.cached is None
        offline = client.get("/api/quota").json()
        assert offline["windows"] == [] and offline["reset_history_scope"] is None
        assert offline["history_mode"] == "unavailable"
        assert client.get("/api/quota/value/history").json()["cycles"] == []
        # The former home's archived readings remain intact and restore only
        # after deliberately selecting that directory again.
        assert client.put("/api/settings", json={"codex_home": str(initial.codex_home)}).status_code == 200
        restored = client.get("/api/quota").json()
        assert restored["history_mode"] == "offline"
        assert restored["history_directory_verified"] is True
        assert restored["reset_history_scope"] != old_result["reset_history_scope"]
        assert app.state.database.get_metadata(CODEX_HOME_METADATA_KEY) == str(initial.codex_home)


def test_simultaneous_api_refreshes_share_fetch_while_directory_switch_waits(settings_app, monkeypatch):
    app, client, _, selected = settings_app
    quota = app.state.quota
    monkeypatch.setattr(quota, "_fetch", lambda: reading(used=20))
    assert client.get("/api/quota").json()["windows"][0]["used_percent"] == 20
    started, second_read, release, validated = (
        threading.Event(), threading.Event(), threading.Event(), threading.Event()
    )
    underlying, count_guard = threading.Lock(), threading.Lock()
    lock_entries, fetches = 0, 0
    from codex_token_report import main

    original_validate = main.validate_codex_home

    def validate(path):
        result = original_validate(path)
        validated.set()
        return result

    class ObservedLock:
        def __enter__(self):
            nonlocal lock_entries
            with count_guard:
                lock_entries += 1
                if lock_entries == 2:
                    # QuotaService captures its prior cache before entering
                    # this lock, proving both requests observed the same read.
                    second_read.set()
            underlying.acquire()

        def __exit__(self, *_):
            underlying.release()

    def fetch():
        nonlocal fetches
        fetches += 1
        started.set()
        assert release.wait(5)
        return reading(used=30)

    monkeypatch.setattr(main, "validate_codex_home", validate)
    monkeypatch.setattr(quota, "lock", ObservedLock())
    monkeypatch.setattr(quota, "_fetch", fetch)
    with TestClient(app) as running_client, ThreadPoolExecutor(max_workers=3) as executor:
        try:
            first = executor.submit(running_client.post, "/api/quota/refresh")
            assert started.wait(2)
            second = executor.submit(running_client.post, "/api/quota/refresh")
            assert second_read.wait(2)
            switch = executor.submit(running_client.put, "/api/settings", json={"codex_home": str(selected)})
            assert validated.wait(2)
            assert not switch.done()
        finally:
            release.set()
        a, b = first.result(timeout=5).json(), second.result(timeout=5).json()
        assert a == b and a["windows"][0]["used_percent"] == 30
        assert fetches == 1
        assert switch.result(timeout=5).status_code == 200
        assert app.state.quota is not quota and app.state.quota.cached is None


def test_directory_switch_waits_for_worker_even_if_quota_http_caller_is_canceled(settings_app, monkeypatch):
    app, _, initial, selected = settings_app
    started, release, validated = threading.Event(), threading.Event(), threading.Event()
    from codex_token_report import main

    original_validate = main.validate_codex_home

    def validate(path):
        result = original_validate(path)
        validated.set()
        return result

    def fetch():
        started.set()
        assert release.wait(5)
        return reading()

    monkeypatch.setattr(main, "validate_codex_home", validate)
    monkeypatch.setattr(app.state.quota, "_fetch", fetch)

    async def exercise():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            pending_read = asyncio.create_task(client.get("/api/quota"))
            try:
                assert await asyncio.to_thread(started.wait, 2)
                pending_read.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending_read
                switch = asyncio.create_task(client.put("/api/settings", json={"codex_home": str(selected)}))
                assert await asyncio.to_thread(validated.wait, 2)
                assert not switch.done()
                assert app.state.settings.codex_home == initial.codex_home
            finally:
                release.set()
            assert (await asyncio.wait_for(switch, timeout=5)).status_code == 200
            assert app.state.quota.cached is None

    asyncio.run(exercise())


def test_completed_quota_worker_does_not_block_switch_if_release_callback_was_canceled(settings_app, monkeypatch):
    app, _, _, selected = settings_app
    monkeypatch.setattr(app.state.quota, "_fetch", lambda: reading())
    create_task = asyncio.create_task
    canceled_callbacks = []

    def canceled_release(coroutine, **kwargs):
        task = create_task(coroutine, **kwargs)
        if coroutine.cr_code.co_name == "release_quota_task":
            # Closing a short-lived ASGI/TestClient portal can cancel this
            # bookkeeping callback after the worker itself has completed.
            canceled_callbacks.append(task)
            task.cancel()
        return task

    monkeypatch.setattr("codex_token_report.main.asyncio.create_task", canceled_release)

    async def exercise():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/api/quota")).status_code == 200
            assert canceled_callbacks
            response = await asyncio.wait_for(
                client.put("/api/settings", json={"codex_home": str(selected)}), timeout=3,
            )
            assert response.status_code == 200
            assert app.state.quota.cached is None

    asyncio.run(exercise())
