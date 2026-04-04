@echo off
title SCALPER-AI Launcher
cd /d "%~dp0"
echo ========================================
echo  SCALPER-AI — Starting all services
echo ========================================
echo.
echo Starting backend (port 9000)...
start "SCALPER-AI Backend" cmd /k "cd /d "%~dp0" && "%LOCALAPPDATA%\Python\bin\python.exe" run_server.py"
timeout /t 3 /nobreak >nul
echo Starting dashboard (port 4000)...
start "SCALPER-AI Dashboard" cmd /k "cd /d "%~dp0dashboard" && npm run dev"
echo.
echo Both services started.
echo   Backend:   http://localhost:9000
echo   Dashboard: http://localhost:4000
echo.
echo Use stop-all.bat to shut down.
pause
