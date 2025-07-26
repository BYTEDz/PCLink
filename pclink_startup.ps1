# PCLink Startup Script for Windows PowerShell
# This script starts PCLink in headless mode at system startup

# Get the script directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Change to the PCLink directory
Set-Location $ScriptDir

# Start PCLink in headless mode
try {
    python run_pclink.py --startup
    Write-Host "PCLink started successfully"
} catch {
    Write-Error "PCLink failed to start: $_"
    # Log the error to a file
    $ErrorMessage = "$(Get-Date): PCLink startup failed - $_"
    Add-Content -Path "pclink_startup_errors.log" -Value $ErrorMessage
}