@echo off
chcp 65001 > nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
title ระบบประมวลผลวันลาและอัปเดต Dashboard

cd /d "%~dp0"
echo ============================================================
echo   กำลังประมวลผลข้อมูลวันลาและอัปเดต Dashboard...
echo ============================================================

where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    py update_dashboard.py
    goto end
)

where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    python update_dashboard.py
    goto end
)

where python3 >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    python3 update_dashboard.py
    goto end
)

echo.
echo [ERROR] ไม่พบคำสั่ง Python ในระบบ กรุณาตรวจสอบการติดตั้ง Python
pause

:end
