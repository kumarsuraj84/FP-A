@echo off
REM Real CFO OS on the common Postgres (gold_fpa, read-only fpa_ro). API on 8081, UI on 5180.
REM The API uses the D: Python (it holds every dependency, argon2 included; backend\.venv is older and incomplete). Runs entirely from D: : Python 3.12 and Node.js live in ..\runtime (copied from the C: installs), caches and temp files in ..\runtime too.
set "RT=%~dp0..\runtime"
set "PATH=%RT%\nodejs;%RT%\python312;%PATH%"
set "TEMP=%RT%\temp"
set "TMP=%RT%\temp"
set "npm_config_cache=%RT%\npm-cache"
set "PIP_CACHE_DIR=%RT%\pip-cache"
if not exist "%RT%\temp" mkdir "%RT%\temp"
cd /d "%~dp0backend"
set FPA_SOURCE=gold
start "FPA API" "%RT%\python312\python.exe" -m uvicorn app.creditors_api.main:app --host 127.0.0.1 --port 8081
cd /d "%~dp0frontend"
start "FPA UI" "%RT%\nodejs\npm.cmd" run dev -- --port 5180 --host 127.0.0.1
echo UI: http://127.0.0.1:5180   API: http://127.0.0.1:8081/docs
