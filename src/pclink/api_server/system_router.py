"""
PCLink - Remote PC Control Server - System Commands API Module
Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published
by the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it was useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
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


async def run_subprocess(cmd: list[str]) -> str:
    """
    Asynchronously runs a subprocess and returns its stdout.

    Args:
        cmd: A list of strings representing the command and its arguments.

    Returns:
        The decoded stdout from the subprocess.

    Raises:
        HTTPException: If the command fails to execute or returns a non-zero exit code.
    """
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        creationflags=SUBPROCESS_FLAGS,
    )
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        error_msg = stderr.decode().strip()
        raise HTTPException(
            status_code=500, detail=f"Command failed: {cmd[0]} - {error_msg}"
        )
    return stdout.decode()


def _execute_sync_power_command(cmd: list[str]):
    """
    Synchronously runs a command in a hidden window.
    This is used because asyncio.create_subprocess_exec was causing a
    NotImplementedError on the default Windows event loop.

    Args:
        cmd: A list of strings representing the command and its arguments.
    """
    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            creationflags=SUBPROCESS_FLAGS,
        )
    except subprocess.CalledProcessError as e:
        error_output = e.stderr.decode().strip()
        log.error(f"Power command failed: {' '.join(cmd)}. Error: {error_output}")
    except Exception as e:
        log.error(f"Failed to spawn power command: {' '.join(cmd)}. Exception: {e}")


@router.post("/power/{command}")
async def power_command(command: str):
    """
    Handles power commands such as shutdown, reboot, lock, sleep, and logout.

    Args:
        command: The power command to execute (shutdown, reboot, lock, sleep, logout).

    Returns:
        A dictionary indicating the status of the command.

    Raises:
        HTTPException: If the command is not supported for the current operating system.
    """
    cmd_map = {
        "win32": {
            "shutdown": ["shutdown", "/s", "/t", "1"],
            "reboot": ["shutdown", "/r", "/t", "1"],
            "lock": ["rundll32.exe", "user32.dll,LockWorkStation"],
            "sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
            "logout": ["shutdown", "/l"],
        },
        "linux": {
            "shutdown": ["systemctl", "poweroff"],
            "reboot": ["systemctl", "reboot"],
            "lock": ["xdg-screensaver", "lock"],
            "sleep": ["systemctl", "suspend"],
            "logout": ["loginctl", "terminate-user", os.getlogin()],
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

    await asyncio.to_thread(_execute_sync_power_command, cmd_to_run)
    return {"status": "command sent"}


def _get_volume_win32() -> Dict[str, Any]:
    """
    Synchronously retrieves the current master volume level and mute status on Windows.

    Returns:
        A dictionary containing the volume level (0-100) and mute status.
    """
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    volume = interface.QueryInterface(IAudioEndpointVolume)
    return {
        "level": round(volume.GetMasterVolumeLevelScalar() * 100),
        "muted": bool(volume.GetMute()),
    }


def _set_volume_win32(level: int):
    """
    Synchronously sets the master volume level on Windows.

    Args:
        level: The desired volume level (0-100). Mutes at 0.
    """
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    volume = interface.QueryInterface(IAudioEndpointVolume)
    if level == 0:
        volume.SetMute(1, None)
    else:
        volume.SetMute(0, None)
        volume.SetMasterVolumeLevelScalar(level / 100, None)


@router.get("/volume")
async def get_volume():
    """
    Gets the current master volume level and mute status.

    Returns:
        A dictionary containing the volume level (0-100) and mute status.

    Raises:
        HTTPException: If there's an error retrieving the volume information.
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
        else:  # linux with amixer
            result = await run_subprocess(["amixer", "sget", "Master"])
            level_match = re.search(r"\[(\d+)%\]", result)
            mute_match = re.search(r"\[(on|off)\]", result)
            return {
                "level": int(level_match.group(1)) if level_match else 50,
                "muted": mute_match.group(1) == "off" if mute_match else False,
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get volume: {e}")


@router.post("/volume/set/{level}")
async def set_volume(level: int):
    """
    Sets the master volume level (0-100). Mutes at 0 and unmutes otherwise.

    Args:
        level: The desired volume level (0-100).

    Returns:
        A dictionary indicating the status of the command.

    Raises:
        HTTPException: If the volume level is out of range or if there's an error setting it.
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

    Returns:
        A dictionary containing WoL support status, MAC address, interface name,
        and WoL enabled status.
    """
    log.info("Attempting to retrieve MAC address for WoL.")
    try:
        # Use the getmac library to find the MAC address of the active interface.
        # This is a synchronous call, so we run it in a thread to avoid blocking.
        mac = await asyncio.to_thread(get_mac_address)

        if mac:
            log.info(f"Successfully found MAC address: {mac}")
            return {
                "supported": True,
                "mac_address": mac,
                "interface_name": "unknown", # Library does not provide interface name.
                "wol_enabled": None, # Assume enabled if MAC is found.
            }
        else:
            log.warning("get_mac_address() returned None. No active network interface found?")
            return {"supported": False, "mac_address": None, "interface_name": None, "wol_enabled": False}

    except Exception as e:
        log.error(f"An exception occurred while trying to get MAC address: {e}")
        return {"supported": False, "mac_address": None, "interface_name": None, "wol_enabled": False}