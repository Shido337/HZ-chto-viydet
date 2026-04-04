@echo off
echo ========================================
echo  SCALPER-AI — Stopping all services
echo ========================================
echo.
echo Stopping backend (python)...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":9000.*LISTENING"') do (
    echo   Killing PID %%p (port 9000)
    taskkill /PID %%p /F >nul 2>&1
)
echo Stopping dashboard (node)...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":4000.*LISTENING"') do (
    echo   Killing PID %%p (port 4000)
    taskkill /PID %%p /F >nul 2>&1
)
echo.
echo All services stopped.
pause
