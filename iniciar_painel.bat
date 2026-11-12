@echo off
chcp 65001 >nul
title Dashboard de Automação Rewards
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" app.py
) else (
    python app.py
)
pause

