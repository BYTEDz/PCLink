@echo off
REM PCLink Startup Script for Windows
REM This script starts PCLink in headless mode at system startup

REM Change to the PCLink directory
cd /d "%~dp0"

REM Start PCLink in headless mode
python run_pclink.py --startup

REM If there's an error, pause to see the error message
if errorlevel 1 (
    echo PCLink failed to start. Press any key to continue...
    pause >nul
)