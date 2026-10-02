@echo off
setlocal
cd /d "%~dp0"
uv run codex-token-report --port 18765
endlocal
