# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

# Import the getmac library for MAC address retrieval.
from getmac import get_mac_address

router = APIRouter()
log = logging.getLogger(__name__)

# Set creation flags for subprocess on Windows to hide the console window.
SUBPROCESS_FLAGS = 0
if sys.platform == "win32":
    SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW


def _get_current_user():
    """Safely get the current user name, handling headless/service environments."""
    try:
        # Try os.getlogin() first (works in normal terminal sessions)
        return os.getlogin()
    except OSError:
        # Fallback for headless/service environments
        try:
            import pwd
            return pwd.getpwuid(os.getuid()).pw_name
        except (ImportError, KeyError):
            # Final fallback
            return os.environ.get('USER', os.environ.get('USERNAME', 'unknown'))


async def run_subprocess(cmd: list[str], timeout: float = 5.0) -> str:
    """
    Asynchronously runs a subprocess and returns its stdout with a strict timeout.

    Args:
        cmd: A list of strings representing the command and its arguments.
        timeout: Maximum time in seconds to wait for the command.

    Returns:
        The decoded stdout from the subprocess.

    Raises:
        HTTPException: If the command fails, times out, or returns a non-zero exit code.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=SUBPROCESS_FLAGS,
        )

        # FIX: Wrap communication in a timeout to prevent server hangs
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            log.warning(f"Command timed out after {timeout}s: {cmd[0]}")
            raise HTTPException(status_code=504, detail="System command timed out")

        if process.returncode != 0:
            error_msg = stderr.decode().strip()
            # Log debug info but return clean error
            log.debug(f"Command execution failed: {cmd} -> {error_msg}")
            raise HTTPException(
                status_code=500, detail=f"Command failed: {cmd[0]} - {error_msg}"
            )
        
        return stdout.decode()

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Subprocess error for {cmd}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal system error: {str(e)}")


async def try_power_command_with_fallbacks(command: str, primary_cmd: list[str]) -> bool:
    """
    Try to execute a power command with fallbacks for Linux systems.
    Enhanced for Debian-based systems with proper permission handling.
    
    Args:
        command: The power command name (shutdown, reboot, etc.)
        primary_cmd: The primary command to try
        
    Returns:
        True if any command succeeded, False otherwise
    """
    # Enhanced fallback commands for Debian-based systems
    fallback_commands = {
        "shutdown": [
            # PCLink power wrapper (preferred for .deb installations)
            ["pclink-power-wrapper", "poweroff"],
            # Systemd with sudo (works with sudoers config)
            ["sudo", "systemctl", "poweroff"],
            # Systemd without sudo (fallback)
            ["systemctl", "poweroff"],
            # Traditional shutdown
            ["shutdown", "-h", "now"],
            ["sudo", "shutdown", "-h", "now"],
            # Direct poweroff
            ["poweroff"],
            ["sudo", "poweroff"],
            # ConsoleKit (older systems)
            ["dbus-send", "--system", "--print-reply", "--dest=org.freedesktop.ConsoleKit", 
             "/org/freedesktop/ConsoleKit/Manager", "org.freedesktop.ConsoleKit.Manager.Stop"],
            # Fallback for minimal systems
            ["/sbin/poweroff"],
            ["sudo", "/sbin/poweroff"]
        ],
        "reboot": [
            # PCLink power wrapper (preferred for .deb installations)
            ["pclink-power-wrapper", "reboot"],
            # Systemd with sudo (works with sudoers config)
            ["sudo", "systemctl", "reboot"],
            # Systemd without sudo (fallback)
            ["systemctl", "reboot"],
            # Traditional shutdown
            ["shutdown", "-r", "now"],
            ["sudo", "shutdown", "-r", "now"],
            # Direct reboot
            ["reboot"],
            ["sudo", "reboot"],
            # ConsoleKit (older systems)
            ["dbus-send", "--system", "--print-reply", "--dest=org.freedesktop.ConsoleKit", 
             "/org/freedesktop/ConsoleKit/Manager", "org.freedesktop.ConsoleKit.Manager.Restart"],
            # Fallback for minimal systems
            ["/sbin/reboot"],
            ["sudo", "/sbin/reboot"]
        ],
        "lock": [
            # Modern desktop environments
            ["loginctl", "lock-session"],
            ["loginctl", "lock-sessions"],
            # XDG standard
            ["xdg-screensaver", "lock"],
            # GNOME
            ["gnome-screensaver-command", "-l"],
            ["dbus-send", "--session", "--dest=org.gnome.ScreenSaver", 
             "/org/gnome/ScreenSaver", "org.gnome.ScreenSaver.Lock"],
            # KDE
            ["qdbus", "org.kde.screensaver", "/ScreenSaver", "Lock"],
            ["dbus-send", "--session", "--dest=org.kde.screensaver", 
             "/ScreenSaver", "org.kde.screensaver.Lock"],
            # XFCE
            ["xflock4"],
            # i3/sway
            ["i3lock"],
            ["swaylock"],
            # X11 screensaver
            ["xscreensaver-command", "-lock"],
            # Light DM
            ["dm-tool", "lock"],
            # Cinnamon
            ["cinnamon-screensaver-command", "-l"],
            # MATE
            ["mate-screensaver-command", "-l"]
        ],
        "sleep": [
            # PCLink power wrapper (preferred for .deb installations)
            ["pclink-power-wrapper", "suspend"],
            # Systemd suspend with sudo (works with sudoers config)
            ["sudo", "systemctl", "suspend"],
            # Systemd suspend without sudo (fallback)
            ["systemctl", "suspend"],
            # pm-utils (older systems)
            ["pm-suspend"],
            ["sudo", "pm-suspend"],
            # UPower (desktop environments)
            ["dbus-send", "--system", "--print-reply", "--dest=org.freedesktop.UPower", 
             "/org/freedesktop/UPower", "org.freedesktop.UPower.Suspend"],
            # ConsoleKit
            ["dbus-send", "--system", "--print-reply", "--dest=org.freedesktop.ConsoleKit", 
             "/org/freedesktop/ConsoleKit/Manager", "org.freedesktop.ConsoleKit.Manager.Suspend", "boolean:true"],
            # Direct kernel interface
            ["echo", "mem", "|", "sudo", "tee", "/sys/power/state"]
        ],
        "logout": [
            # Systemd user session
            ["loginctl", "terminate-user", _get_current_user()],
            ["loginctl", "kill-user", _get_current_user()],
            # Process termination
            ["pkill", "-TERM", "-u", _get_current_user()],
            ["pkill", "-KILL", "-u", _get_current_user()],
            # Desktop environment specific
            ["gnome-session-quit", "--logout", "--no-prompt"],
            ["gnome-session-quit", "--logout", "--force"],
            ["qdbus", "org.kde.ksmserver", "/KSMServer", "logout", "0", "0", "0"],
            ["xfce4-session-logout", "--logout"],
            ["mate-session-save", "--logout"],
            ["cinnamon-session-quit", "--logout", "--no-prompt"],
            # X11 session
            ["pkill", "-f", "startx"],
            ["pkill", "-f", "xinit"]
        ]
    }
    
    commands_to_try = fallback_commands.get(command, [primary_cmd])
    
    for cmd in commands_to_try:
        try:
            # Handle shell commands with pipes
            if "|" in cmd:
                # Execute shell commands that contain pipes
                shell_cmd = " ".join(cmd)
                process = await asyncio.create_subprocess_shell(
                    shell_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            else:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    creationflags=SUBPROCESS_FLAGS,
                )
            
            # Wait with timeout
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5.0)
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                log.debug(f"Fallback command timed out: {cmd}")
                continue

            if process.returncode == 0:
                log.info(f"Power command '{command}' succeeded with: {' '.join(cmd)}")
                return True
            else:
                log.debug(f"Command failed: {' '.join(cmd)} - {stderr.decode().strip()}")
                
        except FileNotFoundError:
            log.debug(f"Command not found: {' '.join(cmd)}")
        except Exception as e:
            log.debug(f"Command error: {' '.join(cmd)} - {e}")
    
    return False


def _execute_sync_power_command(cmd: list[str]):
    """
    Synchronously runs a command in a hidden window.
    """
    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            creationflags=SUBPROCESS_FLAGS,
            timeout=5.0 # Add timeout to sync call as well
        )
    except subprocess.TimeoutExpired:
        log.error(f"Power command timed out: {' '.join(cmd)}")
    except subprocess.CalledProcessError as e:
        error_output = e.stderr.decode().strip()
        log.error(f"Power command failed: {' '.join(cmd)}. Error: {error_output}")
    except Exception as e:
        log.error(f"Failed to spawn power command: {' '.join(cmd)}. Exception: {e}")


@router.post("/power/{command}")
async def power_command(command: str, hybrid: bool = True):
    """
    Handles power commands such as shutdown, reboot, lock, sleep, and logout.
    """
    cmd_map = {
        "win32": {
            "shutdown": ["shutdown", "/s", "/hybrid", "/t", "1"] if hybrid else ["shutdown", "/s", "/t", "1"],
            "reboot": ["shutdown", "/r", "/t", "1"],
            "lock": ["rundll32.exe", "user32.dll,LockWorkStation"],
            "sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
            "logout": ["shutdown", "/l"],
        },
        "linux": {
            "shutdown": ["systemctl", "poweroff"],
            "reboot": ["systemctl", "reboot"],
            "lock": ["loginctl", "lock-session"],
            "sleep": ["systemctl", "suspend"],
            "logout": ["loginctl", "terminate-user", _get_current_user()],
        },
        "darwin": {
            "shutdown": ["osascript", "-e", 'tell app "System Events" to shut down'],
            "reboot": ["osascript", "-e", 'tell app "System Events" to restart'],
            "lock": ["osascript", "-e", 'tell app "loginwindow" to  «event aevtrlok»'],
            "sleep": ["pmset", "sleepnow"],
            "logout": ["osascript", "-e", 'tell app "System Events" to log out'],
        },
    }

    cmd_to_run = cmd_map.get(sys.platform, {}).get(command)
    if not cmd_to_run:
        raise HTTPException(status_code=404, detail=f"Unsupported command: {command}")

    # Use enhanced fallback system for Linux
    if sys.platform == "linux":
        success = await try_power_command_with_fallbacks(command, cmd_to_run)
        if not success:
            raise HTTPException(
                status_code=500, 
                detail=f"Power command '{command}' failed - insufficient permissions or command not available"
            )
    else:
        # Use original method for Windows and macOS
        await asyncio.to_thread(_execute_sync_power_command, cmd_to_run)
    
    return {"status": "command sent"}


def _get_volume_win32() -> Dict[str, Any]:
    from comtypes import CLSCTX_ALL, CoInitialize, CoUninitialize
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    try:
        CoInitialize()  # Initialize COM for this thread
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = interface.QueryInterface(IAudioEndpointVolume)
        return {
            "level": round(volume.GetMasterVolumeLevelScalar() * 100),
            "muted": bool(volume.GetMute()),
        }
    finally:
        CoUninitialize()  # Clean up COM


def _set_volume_win32(level: int):
    from comtypes import CLSCTX_ALL, CoInitialize, CoUninitialize
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    try:
        CoInitialize()  # Initialize COM for this thread
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = interface.QueryInterface(IAudioEndpointVolume)
        if level == 0:
            volume.SetMute(1, None)
        else:
            volume.SetMute(0, None)
            volume.SetMasterVolumeLevelScalar(level / 100, None)
    finally:
        CoUninitialize()  # Clean up COM


async def _get_volume_linux_fallback():
    """Try multiple methods to get volume on Linux."""
    methods = [
        # Method 1: amixer with Master
        (["amixer", "sget", "Master"], "amixer_master"),
        # Method 2: amixer with PCM
        (["amixer", "sget", "PCM"], "amixer_pcm"),
        # Method 3: pactl (PulseAudio)
        (["pactl", "get-sink-volume", "@DEFAULT_SINK@"], "pactl"),
    ]
    
    for cmd, method_name in methods:
        try:
            # Use small timeout for volume checks
            result = await run_subprocess(cmd, timeout=2.0)
            
            if method_name.startswith("amixer"):
                level_match = re.search(r"\[(\d+)%\]", result)
                mute_match = re.search(r"\[(on|off)\]", result)
                if level_match:
                    return {
                        "level": int(level_match.group(1)),
                        "muted": mute_match.group(1) == "off" if mute_match else False,
                    }
            elif method_name == "pactl":
                # Parse pactl output
                level_match = re.search(r"(\d+)%", result)
                if level_match:
                    # Check mute status separately for pactl
                    is_muted = False
                    try:
                        mute_out = await run_subprocess(["pactl", "get-sink-mute", "@DEFAULT_SINK@"], timeout=1.0)
                        is_muted = "yes" in mute_out.lower()
                    except:
                        pass
                        
                    return {
                        "level": int(level_match.group(1)),
                        "muted": is_muted,
                    }
        except HTTPException:
            continue
        except Exception:
            continue
    
    # All methods failed
    raise HTTPException(
        status_code=503,
        detail="Volume control not available. Install 'alsa-utils' or 'pulseaudio-utils'."
    )


@router.get("/volume")
async def get_volume():
    """
    Gets the current master volume level and mute status.
    """
    try:
        if sys.platform == "win32":
            return await asyncio.to_thread(_get_volume_win32)
        elif sys.platform == "darwin":
            vol_str = await run_subprocess(
                ["osascript", "-e", "output volume of (get volume settings)"]
            )
            mute_str = await run_subprocess(
                ["osascript", "-e", "output muted of (get volume settings)"]
            )
            return {"level": int(vol_str.strip()), "muted": mute_str.strip() == "true"}
        else:  # linux
            return await _get_volume_linux_fallback()
    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is
    except Exception as e:
        log.error(f"Unexpected error getting volume: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get volume: {e}")


@router.post("/volume/set/{level}")
async def set_volume(level: int):
    """
    Sets the master volume level (0-100). Mutes at 0 and unmutes otherwise.
    """
    if not 0 <= level <= 100:
        raise HTTPException(
            status_code=400, detail="Volume level must be between 0 and 100."
        )
    try:
        if sys.platform == "win32":
            await asyncio.to_thread(_set_volume_win32, level)
        elif sys.platform == "darwin":
            if level == 0:
                await run_subprocess(
                    ["osascript", "-e", "set volume output muted true"]
                )
            else:
                await run_subprocess(
                    ["osascript", "-e", "set volume output muted false"]
                )
                await run_subprocess(
                    ["osascript", "-e", f"set volume output volume {level}"]
                )
        else:  # linux
            if level == 0:
                await run_subprocess(["amixer", "-q", "set", "Master", "mute"])
            else:
                await run_subprocess(["amixer", "-q", "set", "Master", "unmute"])
                await run_subprocess(["amixer", "-q", "set", "Master", f"{level}%"])
        return {"status": "volume set"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to set volume: {e}")


@router.get("/wake-on-lan/info")
async def get_wake_on_lan_info():
    """
    Retrieves Wake-on-LAN capability and MAC address using a reliable library.
    """
    log.info("Attempting to retrieve MAC address for WoL.")
    try:
        # Use the getmac library to find the MAC address of the active interface.
        mac = await asyncio.to_thread(get_mac_address)

        if mac:
            log.info(f"Successfully found MAC address: {mac}")
            return {
                "supported": True,
                "mac_address": mac,
                "interface_name": "unknown", 
                "wol_enabled": None, 
            }
        else:
            log.warning("get_mac_address() returned None. No active network interface found?")
            return {"supported": False, "mac_address": None, "interface_name": None, "wol_enabled": False}

    except Exception as e:
        log.error(f"An exception occurred while trying to get MAC address: {e}")
        return {"supported": False, "mac_address": None, "interface_name": None, "wol_enabled": False}