import asyncio
import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from codex_token_report import folder_picker
from codex_token_report.config import CODEX_HOME_METADATA_KEY, Settings
from codex_token_report.main import create_app

BASE_URL = "http://127.0.0.1:8765"
ENDPOINT = "/api/settings/select-folder"


@pytest.fixture
def picker_app(tmp_path):
    current = tmp_path / "codex"
    (current / "sessions").mkdir(parents=True)
    app = create_app(Settings(
        codex_home=current, data_dir=tmp_path / "data", scan_interval_minutes=0,
    ))
    client = TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000))
    return app, client


@pytest.mark.parametrize("selected", [None, "folder"])
def test_select_folder_returns_result_without_saving_or_scanning(
    picker_app, tmp_path, monkeypatch, selected,
):
    app, client = picker_app
    current = app.state.settings.codex_home
    path = str(tmp_path.resolve()) if selected else None
    calls = []

    def choose(initial, fallback):
        calls.append((initial, fallback))
        return path

    def forbid_scan():
        raise AssertionError("Choosing a directory must not scan logs")

    monkeypatch.setattr(app.state.folder_picker, "choose", choose)
    monkeypatch.setattr(app.state.scanner, "scan", forbid_scan)
    result = client.post(ENDPOINT, json={"initial_path": str(tmp_path)}, headers={"Origin": BASE_URL})
    assert result.status_code == 200
    assert result.json() == {"path": path}
    assert calls == [(str(tmp_path), current)]
    assert app.state.settings.codex_home == current
    assert app.state.database.get_metadata(CODEX_HOME_METADATA_KEY) is None
    assert app.state.quota.cached is None


def test_picker_error_is_safe_and_allows_another_attempt(picker_app, monkeypatch):
    app, client = picker_app

    def fail(*_):
        raise RuntimeError("private native error")

    monkeypatch.setattr(app.state.folder_picker, "choose", fail)
    failed = client.post(ENDPOINT, json={"initial_path": ""})
    assert failed.status_code == 503
    assert failed.json()["detail"] == "无法打开系统文件夹选择器，请手工填写目录。"
    assert "private" not in failed.text
    monkeypatch.setattr(app.state.folder_picker, "choose", lambda *_: None)
    assert client.post(ENDPOINT, json={"initial_path": ""}).json() == {"path": None}


def test_open_picker_does_not_block_other_requests_and_rejects_second_dialog(
    picker_app, monkeypatch,
):
    app, client = picker_app
    started, release = threading.Event(), threading.Event()

    def choose(*_):
        started.set()
        assert release.wait(5)

    monkeypatch.setattr(app.state.folder_picker, "choose", choose)
    with ThreadPoolExecutor(max_workers=1) as executor:
        opening = executor.submit(client.post, ENDPOINT, json={"initial_path": ""})
        try:
            assert started.wait(2)
            assert client.get("/api/settings").json()["codex_home"] == str(app.state.settings.codex_home)
            duplicate = client.post(ENDPOINT, json={"initial_path": ""})
            assert duplicate.status_code == 409
            assert duplicate.json()["detail"] == "文件夹选择器已打开，请先完成或取消选择。"
        finally:
            release.set()
        assert opening.result(timeout=3).json() == {"path": None}
    assert client.post(ENDPOINT, json={"initial_path": ""}).status_code == 200


def test_disconnected_picker_request_keeps_dialog_reserved_until_worker_finishes(
    picker_app, monkeypatch,
):
    app, _ = picker_app
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def choose(*_):
        started.set()
        assert release.wait(5)
        finished.set()

    monkeypatch.setattr(app.state.folder_picker, "choose", choose)

    async def exercise():
        transport = ASGITransport(app=app, client=("127.0.0.1", 50000))
        async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
            opening = asyncio.create_task(client.post(ENDPOINT, json={"initial_path": ""}))
            try:
                assert await asyncio.to_thread(started.wait, 2)
                opening.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await opening
                assert (await client.post(ENDPOINT, json={"initial_path": ""})).status_code == 409
            finally:
                release.set()
            assert await asyncio.to_thread(finished.wait, 2)
            await asyncio.sleep(0.02)
            assert (await client.post(ENDPOINT, json={"initial_path": ""})).status_code == 200

    asyncio.run(exercise())


@pytest.mark.parametrize("base_url,client_host,origin", [
    (BASE_URL, "192.0.2.1", BASE_URL),
    ("http://attacker.example:8765", "127.0.0.1", "http://attacker.example:8765"),
    (BASE_URL, "127.0.0.1", "http://attacker.example"),
    (BASE_URL, "127.0.0.1", "http://localhost:8765"),
    (BASE_URL, "127.0.0.1", "http://127.0.0.1:8766"),
    (BASE_URL, "127.0.0.1", "https://127.0.0.1:8765"),
    (BASE_URL, "127.0.0.1", "null"),
    (BASE_URL, "127.0.0.1", "http://127.0.0.1:invalid"),
])
def test_picker_rejects_remote_or_cross_origin_requests_before_opening_dialog(
    picker_app, monkeypatch, base_url, client_host, origin,
):
    app, _ = picker_app

    def forbidden(*_):
        raise AssertionError("Untrusted requests must not open a dialog")

    monkeypatch.setattr(app.state.folder_picker, "choose", forbidden)
    client = TestClient(app, base_url=base_url, client=(client_host, 50000))
    result = client.post(ENDPOINT, json={"initial_path": ""}, headers={"Origin": origin})
    assert result.status_code == 403
    assert result.json()["detail"] == "只能从本机页面打开文件夹选择器。"


@pytest.mark.parametrize("base_url,client_host", [
    ("http://localhost:8765", "127.0.0.1"),
    ("http://[::1]:8765", "::1"),
    (BASE_URL, "::ffff:127.0.0.1"),
])
def test_picker_accepts_localhost_and_ipv6_loopback(picker_app, monkeypatch, base_url, client_host):
    app, _ = picker_app
    monkeypatch.setattr(app.state.folder_picker, "choose", lambda *_: None)

    async def exercise():
        transport = ASGITransport(app=app, client=(client_host, 50000))
        async with AsyncClient(transport=transport, base_url=base_url) as client:
            assert (await client.post(ENDPOINT, json={}, headers={"Origin": base_url})).status_code == 200

    asyncio.run(exercise())


@pytest.mark.parametrize("value", [None, 42, []])
def test_picker_invalid_payload_does_not_open_dialog(picker_app, monkeypatch, value):
    app, client = picker_app

    def forbidden(*_):
        raise AssertionError("Invalid payload must not open a dialog")

    monkeypatch.setattr(app.state.folder_picker, "choose", forbidden)
    assert client.post(ENDPOINT, json={"initial_path": value}).status_code == 400


@pytest.fixture
def native_stub(monkeypatch):
    actions, options = [], {}

    class Root:
        def __init__(self):
            actions.append("create")

        def withdraw(self):
            actions.append("withdraw")

        def attributes(self, *args):
            actions.append(("attributes", args))

        def destroy(self):
            actions.append("destroy")

    def askdirectory(**kwargs):
        options.update(kwargs)
        return options.pop("selected", "")

    tkinter = SimpleNamespace(Tk=Root, filedialog=SimpleNamespace(askdirectory=askdirectory))
    monkeypatch.setitem(sys.modules, "tkinter", tkinter)
    monkeypatch.setattr(folder_picker.sys, "platform", "win32")
    return actions, options, tkinter


@pytest.mark.parametrize("initial_kind", ["valid", "missing", "file", "empty", "invalid"])
def test_native_picker_initial_path_and_cancel_destroy_root(
    tmp_path, native_stub, initial_kind,
):
    actions, options, _ = native_stub
    fallback = tmp_path / "fallback"
    fallback.mkdir()
    valid = tmp_path / "selected"
    valid.mkdir()
    file = tmp_path / "file"
    file.write_text("fixture", encoding="utf-8")
    initial = {
        "valid": str(valid), "missing": str(tmp_path / "missing"), "file": str(file),
        "empty": "", "invalid": "bad\0path",
    }[initial_kind]
    assert folder_picker.choose_folder(initial, fallback) is None
    expected = valid if initial_kind == "valid" else fallback
    assert options["initialdir"] == str(expected.resolve())
    assert options["mustexist"] is True
    assert actions[0] == "create" and actions[-1] == "destroy"


def test_native_picker_returns_absolute_selected_path(tmp_path, native_stub):
    actions, options, _ = native_stub
    selected = tmp_path / "folder"
    selected.mkdir()
    options["selected"] = str(selected / ".." / "folder")
    assert folder_picker.choose_folder("", tmp_path) == str(selected.resolve())
    assert actions[-1] == "destroy"


def test_native_picker_error_still_destroys_root(tmp_path, native_stub):
    actions, _, tkinter = native_stub

    def fail(**_):
        raise OSError("fixture GUI unavailable")

    tkinter.filedialog.askdirectory = fail
    with pytest.raises(OSError):
        folder_picker.choose_folder("", tmp_path)
    assert actions[-1] == "destroy"


def test_child_picker_allows_macos_main_thread_gui(tmp_path, native_stub, monkeypatch):
    actions, _, _ = native_stub
    monkeypatch.setattr(folder_picker.sys, "platform", "darwin")
    assert folder_picker.choose_folder("", Path(tmp_path)) is None
    assert actions[0] == "create" and actions[-1] == "destroy"


@pytest.mark.parametrize("selected", [None, "folder"])
def test_process_picker_uses_child_main_thread_and_closes_completed_process(
    tmp_path, monkeypatch, selected,
):
    calls = []
    closed = []
    path = str(tmp_path) if selected else None

    class Process:
        returncode = None
        stdout = SimpleNamespace(close=lambda: closed.append(True))

        def communicate(self):
            self.returncode = 0
            return json.dumps({"path": path}), None

        def poll(self):
            return self.returncode

    def popen(command, **kwargs):
        calls.append((command, kwargs))
        return Process()

    monkeypatch.setattr(folder_picker.subprocess, "Popen", popen)
    picker = folder_picker.FolderPicker()
    assert picker.choose("draft", tmp_path) == path
    command, options = calls[0]
    assert command == [sys.executable, "-m", "codex_token_report.folder_picker", "draft", str(tmp_path)]
    assert options["stderr"] == subprocess.DEVNULL
    assert options["creationflags"] == (subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert closed == [True]
    assert picker._process is None
    picker.close()
    with pytest.raises(OSError, match="shutting down"):
        picker.choose("", tmp_path)
    assert len(calls) == 1
    picker.reopen()
    assert picker.choose("", tmp_path) == path


@pytest.mark.parametrize("returncode,output", [(1, ""), (0, "invalid"), (0, "{}"), (0, '{"path": 1}')])
def test_process_picker_failure_does_not_expose_native_output(tmp_path, monkeypatch, returncode, output):
    class Process:
        stdout = None

        def communicate(self):
            self.returncode = returncode
            return output, None

        def poll(self):
            return self.returncode

    monkeypatch.setattr(folder_picker.subprocess, "Popen", lambda *_args, **_kwargs: Process())
    picker = folder_picker.FolderPicker()
    with pytest.raises((OSError, ValueError)):
        picker.choose("", tmp_path)
    assert picker._process is None


def test_shutdown_terminates_an_open_dialog_without_waiting_for_user_input(picker_app, monkeypatch):
    app, _ = picker_app
    started, stopped = threading.Event(), threading.Event()
    actions = []

    class Process:
        returncode = None
        stdout = None

        def communicate(self):
            started.set()
            assert stopped.wait(5)
            return "", None

        def poll(self):
            return self.returncode

        def terminate(self):
            actions.append("terminate")
            self.returncode = -15
            stopped.set()

        def wait(self, timeout):
            assert timeout == 3
            actions.append("wait")
            return self.returncode

    monkeypatch.setattr(folder_picker.subprocess, "Popen", lambda *_args, **_kwargs: Process())

    async def exercise():
        lifespan = app.router.lifespan_context(app)
        await lifespan.__aenter__()
        transport = ASGITransport(app=app, client=("127.0.0.1", 50000))
        async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
            opening = asyncio.create_task(client.post(ENDPOINT, json={"initial_path": ""}))
            try:
                assert await asyncio.to_thread(started.wait, 2)
                await asyncio.wait_for(lifespan.__aexit__(None, None, None), timeout=2)
            finally:
                stopped.set()
            response = await asyncio.wait_for(opening, timeout=2)
            assert response.status_code == 503
            assert response.json()["detail"] == "无法打开系统文件夹选择器，请手工填写目录。"
            assert app.state.folder_picker._process is None

    asyncio.run(exercise())
    assert actions == ["terminate", "wait"]


def test_process_shutdown_kills_a_child_that_ignores_termination():
    actions = []

    class Process:
        def terminate(self):
            actions.append("terminate")

        def wait(self, timeout):
            assert timeout == 3
            actions.append("wait")
            if "kill" not in actions:
                raise subprocess.TimeoutExpired("picker", timeout)

        def kill(self):
            actions.append("kill")

    folder_picker.FolderPicker._stop(Process())
    assert actions == ["terminate", "wait", "kill", "wait"]
