from __future__ import annotations

import argparse
import json
import threading
import webbrowser
from pathlib import Path

import uvicorn

from .config import Settings
from .db import Database
from .main import create_app
from .pricing_store import PricingStore
from .scanner import SessionScanner


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Codex token usage local dashboard")
    parser.add_argument("--codex-home", type=Path, help="Codex home directory")
    parser.add_argument("--data-dir", type=Path, help="Application data directory")
    parser.add_argument("--timezone", help="IANA timezone, default: Asia/Taipei")
    parser.add_argument("--host", default=None, help="Bind host, default: 127.0.0.1")
    parser.add_argument("--port", type=int, default=None, help="Bind port, default: 8765")
    parser.add_argument(
        "--scan-interval-minutes",
        type=int,
        default=None,
        help="Background scan interval; 0 disables it, default: 60",
    )
    parser.add_argument("--no-browser", action="store_true", help="Do not open the browser")
    parser.add_argument("--scan-only", action="store_true", help="Scan logs and exit")
    return parser


def _settings(args: argparse.Namespace) -> Settings:
    return Settings.from_env().with_overrides(
        codex_home=args.codex_home,
        data_dir=args.data_dir,
        timezone=args.timezone,
        host=args.host,
        port=args.port,
        scan_interval_minutes=args.scan_interval_minutes,
    )


def main() -> None:
    args = _parser().parse_args()
    settings = _settings(args)
    if args.scan_only:
        database = Database(settings.database_path)
        PricingStore(database=database)
        scanner = SessionScanner(
            codex_home=settings.codex_home,
            database=database,
            timezone=settings.timezone,
        )
        print(json.dumps(scanner.scan().to_dict(), ensure_ascii=False, indent=2))
        return

    if not args.no_browser:
        url = f"http://{settings.host}:{settings.port}"
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
