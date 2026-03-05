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
set "PCLINK_SERVICE_EXE=%SCRIPT_DIR%..\..\PCLinkService.exe"

echo [INFO] Stopping PCLink Service...
if exist "%PCLINK_SERVICE_EXE%" (
    "%PCLINK_SERVICE_EXE%" stop
) else (
    python "%PCLINK_SERVICE_PY%" stop
)
if %errorLevel% neq 0 (
    echo [WARNING] Service might not be running or failed to stop.
)

echo [INFO] Uninstalling PCLink Service...
if exist "%PCLINK_SERVICE_EXE%" (
    "%PCLINK_SERVICE_EXE%" remove
) else (
    python "%PCLINK_SERVICE_PY%" remove
)
if %errorLevel% neq 0 (
    echo [ERROR] Failed to remove service.
    pause
    exit /b %errorLevel%
)

echo [OK] PCLink Service stopped and removed successfully.
pause
exit /b 0
