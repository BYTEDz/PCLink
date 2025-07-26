# PCLink Startup Troubleshooting Guide

This guide helps resolve issues with PCLink not starting properly at Windows system boot when packaged with PyInstaller.

## Common Issues and Solutions

### 1. PCLink Not Starting at Boot

**Symptoms:**
- PCLink is configured to start with Windows but doesn't appear in system tray
- No PCLink process visible in Task Manager after boot
- Server not accessible after system restart

**Solutions:**

#### Option A: Use the Startup Fix Script
1. Run the packaged PCLink executable with admin privileges
2. Navigate to the PCLink installation directory
3. Run: `PCLink.exe --startup` manually to test
4. If it works manually but not at boot, run the fix script:
   ```cmd
   python fix_startup_pyinstaller.py
   ```

#### Option B: Manual Registry Fix
1. Open Registry Editor (regedit.exe)
2. Navigate to: `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run`
3. Find the "PCLink" entry
4. Ensure the value is: `"C:\Path\To\PCLink.exe" --startup`
5. Make sure the path is correct and uses quotes

#### Option C: Task Scheduler (Most Reliable)
1. Open Task Scheduler
2. Create Basic Task
3. Name: "PCLink Startup"
4. Trigger: "When I log on"
5. Action: "Start a program"
6. Program: `C:\Path\To\PCLink.exe`
7. Arguments: `--startup`
8. Start in: `C:\Path\To\PCLink\Directory`

### 2. Console Window Appears at Startup

**Symptoms:**
- Black console window briefly appears when PCLink starts
- Console window stays open

**Solutions:**
- Ensure PCLink was built with `console=False` in PyInstaller
- Check that `hide_console_window()` is being called
- Rebuild with the provided `pclink.spec` file

### 3. Startup Delays or Timeouts

**Symptoms:**
- PCLink takes a long time to start at boot
- System tray icon appears but server doesn't start
- Timeout errors in logs

**Solutions:**
- Add a delay before starting PCLink at boot
- Use Task Scheduler with a 30-second delay
- Check Windows Event Viewer for system startup issues

### 4. Permission Issues

**Symptoms:**
- "Access denied" errors in logs
- PCLink starts but can't create files
- Server fails to bind to port

**Solutions:**
- Ensure PCLink directory has write permissions
- Don't run PCLink as administrator (causes tray icon issues)
- Check Windows Defender/antivirus exclusions

## Diagnostic Steps

### Step 1: Test Manual Startup
```cmd
cd "C:\Path\To\PCLink"
PCLink.exe --startup
```

If this works, the issue is with the startup configuration, not PCLink itself.

### Step 2: Check Registry Entry
```cmd
reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v PCLink
```

Should show: `"C:\Path\To\PCLink.exe" --startup`

### Step 3: Check Logs
Look for startup logs in:
- `%APPDATA%\PCLink\pclink.log`
- `%APPDATA%\PCLink\startup_error.log`

### Step 4: Test with Batch File
Create `pclink_startup.bat`:
```batch
@echo off
cd /d "C:\Path\To\PCLink"
PCLink.exe --startup
if errorlevel 1 echo Error: %errorlevel% >> startup_errors.log
```

Add this batch file to startup instead of the exe directly.

## PyInstaller Build Instructions

### Recommended Build Command
```cmd
pyinstaller pclink.spec
```

### Alternative Build Command
```cmd
pyinstaller --onefile --windowed --name PCLink ^
  --add-data "src/pclink/assets;pclink/assets" ^
  --add-data "src/pclink/gui/localizations;pclink/gui/localizations" ^
  --hidden-import psutil ^
  --exclude-module tkinter ^
  run_pclink.py
```

### Build Requirements
- Python 3.8+
- PyInstaller 5.0+
- All PCLink dependencies installed
- Windows 10/11 for best compatibility

## Environment Variables

You can set these environment variables for debugging:

- `PCLINK_STARTUP_MODE=1` - Force startup mode
- `PCLINK_DEBUG=1` - Enable debug logging
- `PCLINK_LOG_LEVEL=DEBUG` - Detailed logging

## Windows 11 Specific Issues

### Issue: Startup Apps Permission
Windows 11 has stricter startup app controls.

**Solution:**
1. Open Settings → Apps → Startup
2. Find PCLink in the list
3. Ensure it's enabled
4. Check the "High impact" warning and allow if needed

### Issue: Windows Defender SmartScreen
Windows Defender might block unsigned executables.

**Solution:**
1. Add PCLink.exe to Windows Defender exclusions
2. Or code-sign the executable (for distribution)

## Testing Startup

### Automated Test
```cmd
# Kill any running PCLink
taskkill /f /im PCLink.exe

# Test startup mode
PCLink.exe --startup

# Check if it's running
tasklist | findstr PCLink
```

### Manual Test
1. Restart your computer
2. Wait for full boot completion
3. Check system tray for PCLink icon
4. Test server connectivity: https://localhost:8000/ping

## Getting Help

If issues persist:

1. Run the diagnostic script: `python fix_startup_pyinstaller.py --diagnose`
2. Check logs in `%APPDATA%\PCLink\`
3. Test manual startup vs automatic startup
4. Check Windows Event Viewer for system errors

## Success Indicators

PCLink is working correctly at startup when:
- ✅ PCLink icon appears in system tray within 30 seconds of login
- ✅ Server responds to: https://localhost:8000/ping
- ✅ Discovery broadcast is active (check with mobile app)
- ✅ No error messages in logs
- ✅ Smooth transition from headless to GUI mode when clicking tray icon