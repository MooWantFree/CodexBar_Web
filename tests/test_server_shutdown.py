import sys
from types import SimpleNamespace

from codex_token_report import cli, desktop
from codex_token_report.config import SERVER_GRACEFUL_SHUTDOWN_SECONDS, Settings


def test_cli_bounds_pending_http_requests_before_lifespan_shutdown(tmp_path, monkeypatch):
    settings = Settings(codex_home=tmp_path, data_dir=tmp_path / "data")
    application = object()
    calls = []
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda _: settings))
    monkeypatch.setattr(cli, "create_app", lambda _: application)
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kwargs: calls.append((app, kwargs)))
    monkeypatch.setattr(sys, "argv", ["codex-token-report", "--no-browser"])
    cli.main()
    assert calls[0][0] is application
    assert calls[0][1]["timeout_graceful_shutdown"] == SERVER_GRACEFUL_SHUTDOWN_SECONDS == 2


def test_desktop_bounds_pending_http_requests_before_lifespan_shutdown(tmp_path, monkeypatch):
    settings = Settings(codex_home=tmp_path, data_dir=tmp_path / "data")
    configuration, thread_actions = [], []
    server = SimpleNamespace(run=lambda: None, should_exit=False)

    class Thread:
        def __init__(self, target, daemon):
            assert target is server.run and daemon is True

        def start(self):
            thread_actions.append("start")

        def join(self, timeout):
            assert server.should_exit is True
            thread_actions.append(("join", timeout))

    monkeypatch.setattr(desktop.Settings, "from_env", classmethod(lambda _: settings))
    monkeypatch.setattr(desktop, "create_app", lambda _: object())
    monkeypatch.setattr(desktop.uvicorn, "Config", lambda app, **kwargs: configuration.append(kwargs))
    monkeypatch.setattr(desktop.uvicorn, "Server", lambda _: server)
    monkeypatch.setattr(desktop.threading, "Thread", Thread)
    monkeypatch.setattr(desktop, "_wait_for_port", lambda *_: None)
    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace(
        create_window=lambda *_args, **_kwargs: None, start=lambda: None,
    ))
    desktop.main()
    assert configuration[0]["timeout_graceful_shutdown"] == SERVER_GRACEFUL_SHUTDOWN_SECONDS == 2
    assert thread_actions == ["start", ("join", 10)]
