from __future__ import annotations

import socket
import threading
import time

import uvicorn

from .config import SERVER_GRACEFUL_SHUTDOWN_SECONDS, Settings
from .main import create_app


def _wait_for_port(host: str, port: int, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.25):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("本地 Web 服务启动超时")


def main() -> None:
    try:
        import webview
    except ImportError as exc:
        raise SystemExit("请先运行：uv sync --extra desktop") from exc

    settings = Settings.from_env()
    config = uvicorn.Config(
        create_app(settings), host=settings.host, port=settings.port, log_level="warning",
        timeout_graceful_shutdown=SERVER_GRACEFUL_SHUTDOWN_SECONDS,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    _wait_for_port(settings.host, settings.port)
    webview.create_window(
        "Codex Token Report",
        f"http://{settings.host}:{settings.port}",
        width=1320,
        height=880,
        min_size=(980, 680),
    )
    webview.start()
    server.should_exit = True
    # Allow the HTTP grace period and native chooser termination to finish.
    thread.join(timeout=10)


if __name__ == "__main__":
    main()
