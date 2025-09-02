# filename: src/pclink/api_server/system_router.py
"""
PCLink - Remote PC Control Server - System Commands API Module
Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published
by the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
import re
import subprocess
import sys

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.post("/power/{command}")
async def power_command(command: str):
    """Handles power commands like shutdown, reboot, and lock."""
    cmd_map = {
        "win32": {
            "shutdown": ["shutdown", "/s", "/t", "1"],
            "reboot": ["shutdown", "/r", "/t", "1"],
            "lock": ["rundll32.exe", "user32.dll,LockWorkStation"],
        },
        "linux": {
            "shutdown": ["shutdown", "now"],
            "reboot": ["reboot"],
            "lock": ["xdg-screensaver", "lock"],
        },
        "darwin": {
            "shutdown": ["osascript", "-e", 'tell app "System Events" to shut down'],
            "reboot": ["osascript", "-e", 'tell app "System Events" to restart'],
            "lock": ["osascript", "-e", 'tell app "loginwindow" to  «event aevtrlok»'],
        },
    }

    if command not in cmd_map.get(sys.platform, {}):
        raise HTTPException(status_code=404, detail=f"Unsupported command: {command}")

    try:
        subprocess.run(cmd_map[sys.platform][command], check=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to execute command: {e}")

    return {"status": "command sent"}


@router.get("/volume")
async def get_volume():
    """Gets the current master volume level and mute status."""
    try:
        if sys.platform == "win32":
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = interface.QueryInterface(IAudioEndpointVolume)
            return {
                "level": round(volume.GetMasterVolumeLevelScalar() * 100),
                "muted": bool(volume.GetMute())
            }
        elif sys.platform == "darwin":
            vol_str = subprocess.check_output(['osascript', '-e', 'output volume of (get volume settings)']).decode().strip()
            mute_str = subprocess.check_output(['osascript', '-e', 'output muted of (get volume settings)']).decode().strip()
            return {"level": int(vol_str), "muted": mute_str == "true"}
        else:  # linux with amixer
            result = subprocess.check_output(['amixer', 'sget', 'Master']).decode()
            level_match = re.search(r'\[(\d+)%\]', result)
            mute_match = re.search(r'\[(on|off)\]', result)
            return {
                "level": int(level_match.group(1)) if level_match else 50,
                "muted": mute_match.group(1) == 'off' if mute_match else False
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get volume: {e}")


@router.post("/volume/set/{level}")
async def set_volume(level: int):
    """Sets the master volume level (0-100), muting at 0 and unmuting otherwise."""
    if not 0 <= level <= 100:
        raise HTTPException(status_code=400, detail="Volume level must be between 0 and 100.")
    try:
        if sys.platform == "win32":
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
        elif sys.platform == "darwin":
            if level == 0:
                subprocess.run(['osascript', '-e', 'set volume output muted true'], check=True)
            else:
                subprocess.run(['osascript', '-e', 'set volume output muted false'], check=True)
                subprocess.run(['osascript', '-e', f'set volume output volume {level}'], check=True)
        else: # linux
            if level == 0:
                subprocess.run(['amixer', '-q', 'set', 'Master', 'mute'], check=True)
            else:
                subprocess.run(['amixer', '-q', 'set', 'Master', 'unmute'], check=True)
                subprocess.run(['amixer', '-q', 'set', 'Master', f'{level}%'], check=True)
        return {"status": "volume set"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to set volume: {e}")