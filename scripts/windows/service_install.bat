@echo off
setlocal

:: Check for administrative privileges
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERROR] This script must be run as Administrator.
    echo.
    echo Right-click this file and select "Run as administrator".
    pause
    exit /b 1
)

set "SCRIPT_DIR=%~dp0"
set "PCLINK_SERVICE_PY=%SCRIPT_DIR%pclink_service.py"

echo [INFO] Installing PCLink Service...
python "%PCLINK_SERVICE_PY%" install
if %errorLevel% neq 0 (
    echo [ERROR] Failed to install service.
    pause
    exit /b %errorLevel%
)

echo [INFO] Starting PCLink Service...
python "%PCLINK_SERVICE_PY%" start
if %errorLevel% neq 0 (
    echo [ERROR] Failed to start service.
    pause
    exit /b %errorLevel%
)

echo [OK] PCLink Service installed and started successfully.
pause
exit /b 0
