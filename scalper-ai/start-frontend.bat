@echo off
title SCALPER-AI Dashboard (port 4000)
cd /d "%~dp0dashboard"
if not exist node_modules (
    echo Installing dependencies...
    call npm install
)
echo Starting dashboard on port 4000...
call npm run dev
pause
