@echo off
title SCALPER-AI Backend (port 9000)
cd /d "%~dp0"
echo Starting backend on port 9000...
"%LOCALAPPDATA%\Python\bin\python.exe" run_server.py
pause
