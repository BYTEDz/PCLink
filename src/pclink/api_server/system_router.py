# filename: src/pclink/api_server/system_router.py
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

router = APIRouter()
log = logging.getLogger(__name__)

# Set creation flags for subprocess on Windows to hide console window
SUBPROCESS_FLAGS = 0
if sys.platform == "win32":
    SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW


async def run_subprocess(cmd: list[str]) -> str:
    """Asynchronously runs a subprocess and returns its stdout."""
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


# --- FIX: Synchronous Helper for Power Commands ---
def _execute_sync_power_command(cmd: list[str]):
    """
    Synchronously runs a command in a hidden window.
    This is used because asyncio.create_subprocess_exec was causing a
    NotImplementedError on the default Windows event loop.
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


# --- FIX: Updated Asynchronous Power Command Endpoint ---
@router.post("/power/{command}")
async def power_command(command: str):
    """Handles power commands like shutdown, reboot, and lock."""
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

    # Run the synchronous, blocking command in a separate thread to avoid
    # freezing the server and to ensure compatibility with the event loop.
    await asyncio.to_thread(_execute_sync_power_command, cmd_to_run)

    return {"status": "command sent"}


def _get_volume_win32() -> Dict[str, Any]:
    """Synchronous helper for getting volume on Windows."""
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
    """Synchronous helper for setting volume on Windows."""
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
    """Gets the current master volume level and mute status."""
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
    """Sets the master volume level (0-100), muting at 0 and unmuting otherwise."""
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


def _get_wol_info_linux() -> Dict[str, Any]:
    """Synchronous helper for getting WoL info on Linux."""
    for iface in os.listdir("/sys/class/net"):
        if iface == "lo" or iface.startswith(("veth", "docker")):
            continue
        try:
            with open(f"/sys/class/net/{iface}/address") as f:
                mac = f.read().strip()
            if not mac or mac == "00:00:00:00:00:00":
                continue

            wol_enabled = False
            try:
                result = subprocess.run(
                    ["ethtool", iface],
                    capture_output=True,
                    text=True,
                    check=True,
                    creationflags=SUBPROCESS_FLAGS,
                )
                wol_enabled = (
                    "Wake-on:" in result.stdout
                    and "g" in result.stdout.split("Wake-on:")[1].split()[0]
                )
            except Exception:
                pass  # ethtool might not be installed or fail

            return {
                "supported": True,
                "mac_address": mac,
                "interface_name": iface,
                "wol_enabled": wol_enabled,
            }
        except Exception:
            continue
    return {"supported": False, "mac_address": None, "interface_name": None}


@router.get("/wake-on-lan/info")
async def get_wake_on_lan_info():
    """Get Wake-on-LAN capability and MAC address of this machine for client-side WoL."""
    wol_info = {
        "supported": False,
        "mac_address": None,
        "interface_name": None,
        "wol_enabled": None,
    }

    try:
        if sys.platform == "win32":
            try:  # PowerShell (preferred)
                ps_command = (
                    "Get-NetAdapter | Where-Object {$_.Virtual -eq $false} | "
                    "Select-Object Name, MacAddress, "
                    "@{Name='WoLSupported'; Expression={("
                    "  Get-NetAdapterPowerManagement -Name $_.Name -ErrorAction SilentlyContinue"
                    ").WakeOnMagicPacket -eq 'Enabled'"
                    "}} | ConvertTo-Json"
                )
                result_stdout = await run_subprocess(
                    ["powershell", "-Command", ps_command]
                )
                adapters = json.loads(result_stdout)
                if not isinstance(adapters, list):
                    adapters = [adapters]

                for adapter in sorted(
                    adapters, key=lambda x: x.get("WoLSupported", False), reverse=True
                ):
                    if adapter.get("MacAddress"):
                        wol_info.update(
                            {
                                "supported": True,
                                "mac_address": adapter["MacAddress"].replace("-", ":"),
                                "interface_name": adapter["Name"],
                                "wol_enabled": adapter.get("WoLSupported", False),
                            }
                        )
                        return wol_info
            except Exception:  # WMIC (fallback)
                wmic_result = await run_subprocess(
                    [
                        "wmic",
                        "path",
                        "Win32_NetworkAdapter",
                        "where",
                        "PhysicalAdapter=TRUE",
                        "get",
                        "Name,MACAddress",
                        "/format:csv",
                    ]
                )
                for line in wmic_result.strip().split("\n")[1:]:
                    if line.strip():
                        parts = [p.strip() for p in line.split(",") if p.strip()]
                        if len(parts) >= 2 and re.match(
                            r"^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$", parts[1]
                        ):
                            wol_info.update(
                                {
                                    "supported": True,
                                    "mac_address": parts[1],
                                    "interface_name": parts[0],
                                }
                            )
                            return wol_info

        elif sys.platform == "darwin":
            ifconfig_out = await run_subprocess(["ifconfig"])
            interfaces = re.findall(r"^(\w+): flags=", ifconfig_out, re.MULTILINE)
            for interface in interfaces:
                if interface.startswith(("en", "eth")):
                    if_result = await run_subprocess(["ifconfig", interface])
                    mac_match = re.search(
                        r"ether (([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2})", if_result
                    )
                    if mac_match:
                        wol_info.update(
                            {
                                "supported": True,
                                "mac_address": mac_match.group(1),
                                "interface_name": interface,
                            }
                        )
                        return wol_info
        else:  # Linux
            return await asyncio.to_thread(_get_wol_info_linux)

    except Exception as e:
        # Don't raise an exception if WoL info fails, just return the default
        log.warning(f"Could not retrieve Wake-on-LAN info: {e}")

    return wol_info