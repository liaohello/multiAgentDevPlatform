@echo off
rem dev mode: backend with autoreload (http://127.0.0.1:8787)
setlocal
cd /d %~dp0..\backend
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8787
endlocal
