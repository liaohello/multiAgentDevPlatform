@echo off
rem dev mode: frontend via Vite (port 5173, proxies /api to 8787)
setlocal
cd /d %~dp0..\ui
call npm run dev
endlocal
