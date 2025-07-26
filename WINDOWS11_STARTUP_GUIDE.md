# Windows 11 Startup Issues - Solutions Guide

## Problem
PCLink doesn't start automatically on Windows 11 boot, while it works fine on Windows 10.

## Root Cause
Windows 11 has stricter startup policies and different behavior compared to Windows 10:
- Registry startup entries may be delayed or blocked
- Windows Defender and security policies are more restrictive
- Task Scheduler requires elevated permissions
- Timing issues during boot process

## Solutions Implemented

### 1. Multi-Method Startup Approach
PCLink now uses three different startup methods simultaneously:

#### Method 1: Registry Startup (Traditional)
- Location: `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run`
- Works on most systems but may be delayed on Windows 11

#### Method 2: Windows Startup Folder
- Location: `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`
- Creates a shortcut (.lnk file) that Windows 11 respects
- More reliable than registry on Windows 11

#### Method 3: Task Scheduler (Most Reliable)
- Creates a scheduled task that runs at user logon
- Most reliable method for Windows 11
- Includes 10-second delay to avoid boot timing issues
- Requires admin permissions to create

### 2. Enhanced Error Handling
- Graceful fallback if one method fails
- Detailed logging for troubleshooting
- Multiple removal methods for clean uninstall

## Manual Windows 11 Startup Setup

If automatic setup fails, you can manually configure startup:

### Option A: Windows Startup Folder (Recommended)
1. Press `Win + R`, type `shell:startup`, press Enter
2. Create a shortcut to your PCLink executable
3. Right-click the shortcut → Properties
4. In "Target" field, add ` --startup` at the end
5. Example: `"C:\Program Files\PCLink\PCLink.exe" --startup`

### Option B: Task Scheduler (Most Reliable)
1. Press `Win + R`, type `taskschd.msc`, press Enter
2. Click "Create Basic Task" in the right panel
3. Name: "PCLink Startup"
4. Trigger: "When I log on"
5. Action: "Start a program"
6. Program: Path to PCLink.exe
7. Arguments: `--startup`
8. Check "Open Properties dialog" and click Finish
9. In Properties → Settings:
   - Uncheck "Stop if computer switches to battery power"
   - Check "Start task as soon as possible after a scheduled start is missed"
   - Set "If task is already running": "Do not start a new instance"

### Option C: Windows Settings (GUI Method)
1. Open Windows Settings (`Win + I`)
2. Go to Apps → Startup
3. Find PCLink in the list and toggle it ON
4. If not listed, use Option A or B above

## Troubleshooting Windows 11 Startup Issues

### Check Current Startup Status
```powershell
# Check registry
Get-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "PCLink" -ErrorAction SilentlyContinue

# Check startup folder
Get-ChildItem "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\PCLink.lnk" -ErrorAction SilentlyContinue

# Check scheduled tasks
Get-ScheduledTask -TaskName "PCLink_PCLink" -ErrorAction SilentlyContinue
```

### Common Windows 11 Issues and Solutions

#### Issue 1: "Access Denied" when creating scheduled task
**Solution**: Run PCLink as administrator once to create the task, then it will work normally.

#### Issue 2: PCLink starts but GUI doesn't appear
**Solution**: This is normal for `--startup` mode. PCLink runs in headless mode with system tray icon.

#### Issue 3: Antivirus blocking startup
**Solution**: Add PCLink.exe to antivirus exclusions.

#### Issue 4: Windows Defender SmartScreen blocking
**Solution**: 
1. Click "More info" when SmartScreen appears
2. Click "Run anyway"
3. Or add PCLink to Windows Defender exclusions

#### Issue 5: Startup delay on Windows 11
**Solution**: This is normal. Windows 11 delays startup programs. PCLink will start within 30-60 seconds after login.

## Verification

To verify PCLink is configured for startup:
1. Run PCLink normally
2. Go to Settings menu
3. Check "Start with OS" option
4. Look for checkmark indicating it's enabled

## Advanced Configuration

For enterprise or managed Windows 11 systems:

### Group Policy Configuration
1. Open `gpedit.msc`
2. Navigate to: Computer Configuration → Administrative Templates → Windows Components → Windows Logon Options
3. Enable "Show first sign-in animation" (helps with startup timing)
4. Configure "Turn on convenience PIN sign-in" as needed

### Registry Tweaks for Startup Optimization
```reg
[HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Explorer\Serialize]
"StartupDelayInMSec"=dword:00000000
```

## Testing Your Configuration

1. Restart your computer
2. Log in normally
3. Wait 60 seconds
4. Check system tray for PCLink icon
5. If not visible, check Task Manager → Startup tab
6. Look for PCLink in the list and ensure it's "Enabled"

## Support

If startup still doesn't work after trying these solutions:
1. Check Windows Event Viewer for errors
2. Run PCLink with `--startup` manually to test
3. Check antivirus/firewall logs
4. Ensure PCLink.exe has proper permissions
5. Try running as administrator once

The enhanced startup system should resolve most Windows 11 compatibility issues while maintaining backward compatibility with Windows 10.