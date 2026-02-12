@echo off
chcp 65001 >nul
title KODIK DOWNLOADER

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python not found!
    pause
    exit
)

echo Checking dependencies...
pip install -r requirements.txt >nul 2>&1
python -m playwright install chromium >nul 2>&1

cls
python -m src.main
exit /b
