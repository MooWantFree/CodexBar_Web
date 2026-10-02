"""Open the host's folder chooser without changing application settings."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path


def _initial_directory(initial_path: str, fallback: Path) -> Path | None:
    for value in (initial_path.strip(), fallback, Path.home()):
        if not value:
            continue
        try:
            candidate = Path(value).expanduser().resolve(strict=True)
            if candidate.is_dir():
                return candidate
        except (OSError, ValueError, RuntimeError):
            continue
    return None


def choose_folder(initial_path: str, fallback: Path) -> str | None:
    # Import lazily so the dashboard remains usable on hosts without a GUI.
    import tkinter
    from tkinter import filedialog

    initial = _initial_directory(initial_path, fallback)
    root = tkinter.Tk()
    try:
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(
            parent=root, title="Choose Codex log folder", mustexist=True,
            **({"initialdir": str(initial)} if initial else {}),
        )
        if not selected:
            return None
        path = Path(selected).expanduser().resolve(strict=True)
        if not path.is_dir():
            raise ValueError("Selected folder is unavailable")
        return str(path)
    finally:
        root.destroy()


class FolderPicker:
    """Keep the native GUI on a child main thread, with bounded shutdown."""

    def __init__(self):
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._closed = False

    def reopen(self) -> None:
        with self._lock:
            self._closed = False

    def choose(self, initial_path: str, fallback: Path) -> str | None:
        with self._lock:
            if self._closed:
                raise OSError("Folder picker is shutting down")
            process = subprocess.Popen(
                [sys.executable, "-m", "codex_token_report.folder_picker", initial_path, str(fallback)],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding="utf-8",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            self._process = process
        try:
            output, _ = process.communicate()
            if process.returncode:
                raise OSError("Native folder picker failed")
            result = json.loads(output)
            if not isinstance(result, dict) or "path" not in result:
                raise ValueError("Native folder picker returned an invalid result")
            path = result["path"]
            if path is not None and not isinstance(path, str):
                raise ValueError("Native folder picker returned an invalid result")
            return path
        finally:
            if process.poll() is None:
                self._stop(process)
            with self._lock:
                if self._process is process:
                    self._process = None
            if process.stdout:
                process.stdout.close()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            process = self._process
        if process is not None and process.poll() is None:
            self._stop(process)

    @staticmethod
    def _stop(process) -> None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


def main() -> int:
    path = choose_folder(sys.argv[1], Path(sys.argv[2]))
    print(json.dumps({"path": path}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
