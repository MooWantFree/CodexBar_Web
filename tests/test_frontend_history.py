"""Run React UI regression checks when the frontend development dependencies exist."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed for frontend checks")
def test_frontend_history_behavior():
    frontend = Path(__file__).resolve().parents[1] / "frontend"
    script = frontend / "node_modules" / "vitest" / "vitest.mjs"
    if not script.exists():
        pytest.skip("Run npm ci in frontend to install React test dependencies")
    result = subprocess.run(
        [shutil.which("node"), str(script), "run"], cwd=frontend,
        capture_output=True, text=True, encoding="utf-8", timeout=90, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
