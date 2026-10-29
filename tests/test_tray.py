import socket
import sys
import threading
import time
from types import SimpleNamespace
from urllib.request import urlopen

import pytest
from fastapi import FastAPI

from codex_token_report import cli, tray
from codex_token_report.config import Settings


@pytest.mark.parametrize(("host", "expected"), [
    ("127.0.0.1", "127.0.0.1"), ("0.0.0.0", "127.0.0.1"),
    ("::", "[::1]"), ("::1", "[::1]"), ("localhost", "localhost"),
])
def test_browser_url_uses_reachable_address(tmp_path, host, expected):
    settings = Settings(codex_home=tmp_path, data_dir=tmp_path, host=host, port=18765)
    assert tray.browser_url(settings) == f"http://{expected}:18765"


def test_cli_passes_tray_settings_and_browser_preference(tmp_path, monkeypatch):
    settings = Settings(codex_home=tmp_path, data_dir=tmp_path)
    calls = []
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda _: settings))
    monkeypatch.setattr(tray, "run_tray", lambda settings, **kw: calls.append((settings, kw)))
    monkeypatch.setattr(sys, "argv", [
        "codex-token-report", "--tray", "--no-browser", "--port", "18765",
    ])
    cli.main()
    assert calls[0][0].port == 18765
    assert calls[0][1] == {"open_browser": False}


@pytest.mark.skipif(sys.platform != "win32", reason="Windows tray backend")
def test_tray_opens_once_on_double_click_and_has_two_menu_items():
    from pystray._util import win32

    actions = []
    icon = tray._create_icon(lambda *_: actions.append("open"), lambda *_: actions.append("exit"))
    try:
        assert [item.text for item in icon.menu.items] == ["打开网页", "退出"]
        icon._on_notify(0, win32.WM_LBUTTONUP)
        assert actions == []
        icon._on_notify(0, tray.WM_LBUTTONDBLCLK)
        icon._on_notify(0, win32.WM_LBUTTONUP)
        assert actions == ["open"]
        icon.menu.items[0](icon)
        icon.menu.items[1](icon)
        assert actions == ["open", "open", "exit"]
    finally:
        # This icon never entered run(), so release its registered window class.
        icon._unregister_class(icon._atom)


@pytest.mark.parametrize("open_browser", [True, False])
@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_service_continues_until_tray_exit_and_finishes_shutdown(
    tmp_path, monkeypatch, open_browser, platform,
):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    settings = Settings(codex_home=tmp_path, data_dir=tmp_path, port=port)
    application = FastAPI()
    application.get("/health")(lambda: {"status": "ok"})
    opened, stopped = [], []

    class Icon:
        visible = False

        def __init__(self, open_page, exit_app):
            self.open_page, self.exit_app = open_page, exit_app
            self.closed = threading.Event()

        def stop(self):
            self.closed.set()

        def run(self, setup):
            worker = threading.Thread(target=lambda: setup(self))
            worker.start()
            try:
                deadline = time.monotonic() + 10
                while open_browser and not opened and time.monotonic() < deadline:
                    time.sleep(0.01)
                assert opened == ([tray.browser_url(settings)] if open_browser else [])
                with urlopen(f"{tray.browser_url(settings)}/health", timeout=2) as response:
                    assert response.status == 200
                # Opening a webpage leaves the service running.
                self.open_page()
                assert not self.closed.is_set()
                with urlopen(f"{tray.browser_url(settings)}/health", timeout=2) as response:
                    assert response.status == 200
            finally:
                self.exit_app(self)
                worker.join(timeout=5)
                stopped.append(self.closed.is_set())

    monkeypatch.setattr(tray, "create_app", lambda _: application)
    monkeypatch.setattr(tray, "_create_icon", Icon)
    monkeypatch.setattr(tray.webbrowser, "open", opened.append)
    monkeypatch.setattr(tray.sys, "platform", platform)
    tray.run_tray(settings, open_browser=open_browser)
    assert stopped == [True]
    assert len(opened) == (2 if open_browser else 1)
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=0.2)
    assert not any(thread.name == "codex-report-server" for thread in threading.enumerate())
    assert "Application shutdown complete" in (tmp_path / "tray.log").read_text(encoding="utf-8")


def test_bind_failure_closes_tray_instead_of_leaving_orphan(tmp_path, monkeypatch):
    class Icon:
        def __init__(self, *_):
            self.closed = threading.Event()

        def stop(self):
            self.closed.set()

        def run(self, setup):
            setup(self)
            assert self.closed.wait(5)

    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        settings = Settings(
            codex_home=tmp_path, data_dir=tmp_path, port=occupied.getsockname()[1],
        )
        monkeypatch.setattr(tray, "create_app", lambda _: FastAPI())
        monkeypatch.setattr(tray, "_create_icon", Icon)
        with pytest.raises(RuntimeError, match="托盘服务异常退出"):
            tray.run_tray(settings, open_browser=False)
    assert not any(thread.name == "codex-report-server" for thread in threading.enumerate())


@pytest.mark.parametrize("platform", ["darwin", "linux"])
@pytest.mark.parametrize("has_default", [True, False])
def test_native_backend_needs_no_windows_api(monkeypatch, platform, has_default):
    class NativeIcon:
        HAS_MENU = True
        HAS_DEFAULT_ACTION = has_default

        def __init__(self, *args, **kwargs):
            self.menu = kwargs["menu"]

    backend = SimpleNamespace(
        Icon=NativeIcon,
        Menu=lambda *items: items,
        MenuItem=lambda text, action, **kwargs: SimpleNamespace(
            text=text, action=action, **kwargs,
        ),
    )
    monkeypatch.setitem(sys.modules, "pystray", backend)
    monkeypatch.setattr(tray.sys, "platform", platform)
    icon = tray._create_icon(lambda *_: None, lambda *_: None)
    assert type(icon) is NativeIcon
    assert [item.text for item in icon.menu] == ["打开网页", "退出"]
    assert icon.menu[0].default is has_default


def test_menuless_backend_is_rejected_before_starting_service(monkeypatch):
    monkeypatch.setitem(sys.modules, "pystray", SimpleNamespace(
        Icon=SimpleNamespace(HAS_MENU=False), Menu=None, MenuItem=None,
    ))
    with pytest.raises(RuntimeError, match="不支持菜单"):
        tray._create_icon(lambda *_: None, lambda *_: None)
    assert not any(thread.name == "codex-report-server" for thread in threading.enumerate())


def test_missing_backend_explains_desktop_dependencies(monkeypatch):
    monkeypatch.setitem(sys.modules, "pystray", None)
    with pytest.raises(RuntimeError, match="tray-linux"):
        tray._create_icon(lambda *_: None, lambda *_: None)


def test_tray_requires_main_thread(tmp_path):
    errors = []

    def start_in_worker():
        try:
            tray.run_tray(Settings(codex_home=tmp_path, data_dir=tmp_path))
        except RuntimeError as exc:
            errors.append(str(exc))

    worker = threading.Thread(target=start_in_worker)
    worker.start()
    worker.join(timeout=2)
    assert errors == ["托盘模式必须从主线程启动。"]
