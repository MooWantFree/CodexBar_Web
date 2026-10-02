"""Exercise saved-history rendering and request behavior without a browser dependency."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed for frontend checks")
def test_frontend_history_behavior():
    script = Path(__file__).with_name("frontend_history_checks.cjs")
    result = subprocess.run(
        [shutil.which("node"), str(script)], capture_output=True, text=True,
        encoding="utf-8", timeout=15, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
