@echo off
rem run the backend test suite
setlocal
cd /d %~dp0..\backend
.venv\Scripts\python.exe -m pytest -q
endlocal
