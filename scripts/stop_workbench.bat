@echo off
rem stop the agentProj backend (only the process this app owns, via runtime.json pid)
setlocal
cd /d %~dp0..
if not exist ".agentproj\runtime.json" (
  echo runtime.json not found; service probably not running.
  exit /b 0
)
for /f "usebackq delims=" %%p in (`backend\.venv\Scripts\python.exe -c "import json;print(json.load(open(r'.agentproj/runtime.json',encoding='utf-8'))['pid'])"`) do (
  echo stopping pid %%p ...
  taskkill /PID %%p /T /F
)
endlocal
