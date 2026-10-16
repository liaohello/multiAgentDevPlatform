@echo off
rem agentProj workbench launcher: build (if needed) + start backend (foreground) + open browser
rem Closing this window (or Ctrl+C) stops the service. scripts\stop_workbench.bat also works.
setlocal
cd /d %~dp0..

echo [1/3] checking frontend build...
if not exist "ui\dist\index.html" (
  pushd ui
  echo       installing npm deps...
  call npm install --no-audit --no-fund
  if errorlevel 1 (echo npm install failed & popd & exit /b 1)
  echo       building frontend...
  call npm run build
  if errorlevel 1 (echo vite build failed & popd & exit /b 1)
  popd
)

echo [2/3] preparing backend python env...
if not exist "backend\.venv\Scripts\python.exe" (
  echo       first run: creating python venv + installing deps...
  python -m venv backend\.venv
  if errorlevel 1 (echo venv creation failed & exit /b 1)
  backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt -i https://pypi.org/simple
  if errorlevel 1 (echo pip install failed & exit /b 1)
)

echo [3/3] starting backend on http://127.0.0.1:8787 (close this window to stop)
start "agentproj-open" /min cmd /c "timeout /t 3 /nobreak >nul & start "" "http://127.0.0.1:8787""
title agentProj backend - close window or Ctrl+C to stop
backend\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8787 --app-dir backend
endlocal
