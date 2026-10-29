from __future__ import annotations

import logging
import sys
import threading
import time
import webbrowser
from logging.handlers import RotatingFileHandler

import uvicorn

from .config import SERVER_GRACEFUL_SHUTDOWN_SECONDS, Settings
from .main import create_app

WM_LBUTTONDBLCLK = 0x0203


def browser_url(settings: Settings) -> str:
    host = settings.host
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1" if host == "0.0.0.0" else "::1"
    if ":" in host:
        host = f"[{host}]"
    return f"http://{host}:{settings.port}"


def _icon_type(base_icon):
    if sys.platform != "win32":
        return base_icon

    # Only the Windows backend uses native mouse messages. Other platforms
    # keep pystray's public API and their native menu interaction.
    from pystray._util import win32

    class DoubleClickIcon(base_icon):
        def _on_notify(self, wparam, lparam):
            # pystray's Windows default action uses a single click. Restrict it
            # to a double click while retaining its native right-click menu.
            if lparam == WM_LBUTTONDBLCLK:
                self()
            elif lparam != win32.WM_LBUTTONUP:
                super()._on_notify(wparam, lparam)

    return DoubleClickIcon


def _create_icon(open_page, exit_app):
    # Keep GUI imports lazy so ordinary CLI/headless use needs no tray backend.
    try:
        from PIL import Image, ImageDraw
        from pystray import Icon, Menu, MenuItem
    except Exception as exc:
        raise RuntimeError(
            "无法初始化托盘。请先运行 uv sync --locked，并在图形桌面会话中启动。"
            "Linux 还需 GTK 3、AppIndicator / Ayatana AppIndicator 和 PyGObject"
            "（准备系统依赖后运行 uv sync --locked --extra tray-linux）。"
            "无图形桌面时请去掉 --tray 使用普通网页模式。"
        ) from exc
    if not Icon.HAS_MENU:
        raise RuntimeError(
            "当前托盘后端不支持菜单，无法提供退出选项。"
            "Linux 请安装 GTK 3、AppIndicator / Ayatana AppIndicator 和 PyGObject，"
            "并确认桌面支持托盘；也可去掉 --tray 使用普通网页模式。"
        )

    # Match the dashboard's terminal + usage-bars logo at tray icon sizes.
    image = Image.new("RGBA", (64, 64))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, 63, 63), radius=16, fill="#277ad9")
    draw.line([(14, 24), (22, 32), (14, 40)], fill="white", width=4)
    for x, top in ((29, 36), (38, 28), (47, 20)):
        draw.rounded_rectangle((x, top, x + 5, 46), radius=2, fill="white")
    return _icon_type(Icon)(
        "codex-token-report", image, "Codex Token Report",
        menu=Menu(
            MenuItem("打开网页", open_page, default=Icon.HAS_DEFAULT_ACTION),
            MenuItem("退出", exit_app),
        ),
    )


def _run_server(settings: Settings, *, open_browser: bool) -> None:
    server = uvicorn.Server(uvicorn.Config(
        create_app(settings), host=settings.host, port=settings.port,
        log_config=None, log_level="info",
        timeout_graceful_shutdown=SERVER_GRACEFUL_SHUTDOWN_SECONDS,
    ))
    finished = threading.Event()
    tray_ready = threading.Event()
    failures: list[BaseException] = []

    def open_page(icon=None, item=None):
        if server.started and not server.should_exit:
            webbrowser.open(browser_url(settings))

    def exit_app(icon, item=None):
        server.should_exit = True
        icon.stop()

    icon = _create_icon(open_page, exit_app)

    def serve():
        try:
            server.run()
        except BaseException as exc:
            failures.append(exc)
            logging.getLogger(__name__).exception("Web service failed")
        finally:
            finished.set()
            if tray_ready.is_set():
                icon.stop()

    def setup(icon):
        try:
            icon.visible = True
            tray_ready.set()
            deadline = time.monotonic() + 30
            while not server.started:
                if finished.wait(0.1) or server.should_exit:
                    icon.stop()
                    return
                if time.monotonic() >= deadline:
                    raise RuntimeError("本地 Web 服务启动超时")
            if open_browser:
                open_page()
        except Exception as exc:
            failures.append(exc)
            logging.getLogger(__name__).exception("Tray setup failed")
            exit_app(icon)

    # Non-daemon plus join allows active scans and SQLite writes to finish.
    thread = threading.Thread(target=serve, name="codex-report-server", daemon=False)
    thread.start()
    try:
        icon.run(setup=setup)
    finally:
        server.should_exit = True
        thread.join()
        icon.stop()
    if failures:
        raise RuntimeError("托盘服务异常退出，请查看 tray.log") from failures[0]
    if not server.started:
        raise RuntimeError("本地 Web 服务未能启动，请查看 tray.log")


def run_tray(settings: Settings, *, open_browser: bool = True) -> None:
    # macOS requires the tray event loop to run on the main thread.
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("托盘模式必须从主线程启动。")

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        settings.data_dir / "tray.log", maxBytes=2 * 1024 * 1024,
        backupCount=2, encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger = logging.getLogger()
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        _run_server(settings, open_browser=open_browser)
    except BaseException:
        logger.exception("Tray application stopped")
        raise
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        handler.close()
