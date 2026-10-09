@echo off
REM Real CFO OS on the common Postgres (gold_fpa, read-only fpa_ro). API on 8081, UI on 5180.
cd /d "%~dp0backend"
set FPA_SOURCE=gold
start "FPA API" .venv\Scripts\python -m uvicorn app.creditors_api.main:app --host 127.0.0.1 --port 8081
cd /d "%~dp0frontend"
start "FPA UI" npm run dev -- --port 5180 --host 127.0.0.1
echo UI: http://127.0.0.1:5180   API: http://127.0.0.1:8081/docs
