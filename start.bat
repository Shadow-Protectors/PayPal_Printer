@echo off
title SmartPrint AI Server
cd /d "%~dp0"
echo Starting SmartPrint AI at http://127.0.0.1:8000 ...
python run.py
pause
