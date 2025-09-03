# filename: src/pclink/api_server/services.py
"""
PCLink - Remote PC Control Server - API Services Module
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

import asyncio
import logging
import platform
import socket
import subprocess
import sys
import time
from typing import Dict

import psutil
from pynput.keyboard import Controller as KeyboardController
from pynput.keyboard import Key
from pynput.mouse import Button
from pynput.mouse import Controller as MouseController

log = logging.getLogger(__name__)
DEFAULT_MEDIA_INFO = {
    "title": "Nothing Playing",
    "artist": "",
    "album_title": "",
    "status": "STOPPED",
    "position_sec": 0,
    "duration_sec": 0,
    "is_shuffle_active": False,
    "repeat_mode": "NONE",  # Can be NONE, ONE, or ALL
}

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
        raise subprocess.CalledProcessError(
            process.returncode, cmd, output=stdout, stderr=stderr
        )
    return stdout.decode().strip()


# --- Platform-specific Media Info Fetchers ---


async def _get_media_info_win32() -> Dict[str, str]:
    """Fetches media info on Windows using Windows SDK."""
    try:
        from winsdk.windows.media import MediaPlaybackAutoRepeatMode
        from winsdk.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as MediaManager,
        )

        manager = await MediaManager.request_async()
        session = manager.get_current_session()
        if not session:
            return DEFAULT_MEDIA_INFO

        info = await session.try_get_media_properties_async()
        timeline = session.get_timeline_properties()
        playback_info = session.get_playback_info()

        status_map = {
            0: "STOPPED",  # Closed
            1: "PAUSED",  # Opened
            2: "STOPPED",  # Changing
            3: "STOPPED",
            4: "PLAYING",
            5: "PAUSED",
        }

        repeat_map = {
            MediaPlaybackAutoRepeatMode.NONE: "NONE",
            MediaPlaybackAutoRepeatMode.TRACK: "ONE",
            MediaPlaybackAutoRepeatMode.LIST: "ALL",
        }

        return {
            "title": info.title or "Unknown Title",
            "artist": info.artist or "Unknown Artist",
            "album_title": info.album_title or "",
            "status": status_map.get(playback_info.playback_status, "STOPPED"),
            "position_sec": int(timeline.position.total_seconds()),
            "duration_sec": int(timeline.end_time.total_seconds()),
            "is_shuffle_active": playback_info.is_shuffle_active or False,
            "repeat_mode": repeat_map.get(playback_info.auto_repeat_mode, "NONE"),
        }
    except (ImportError, RuntimeError):
        # Silently fail if winsdk is not installed or fails
        return DEFAULT_MEDIA_INFO
    except Exception:
        # Catch other unexpected errors from the async operations
        return DEFAULT_MEDIA_INFO


async def _get_media_info_linux() -> Dict[str, str]:
    """Fetches media info on Linux using playerctl asynchronously."""
    try:
        status_raw = await run_subprocess(["playerctl", "status"])
        status_map = {"Playing": "PLAYING", "Paused": "PAUSED", "Stopped": "STOPPED"}
        status = status_map.get(status_raw, "STOPPED")

        if status == "STOPPED":
            return DEFAULT_MEDIA_INFO

        # Optimize by fetching multiple metadata fields in one call
        metadata_format = "{{title}}||{{artist}}||{{album}}||{{mpris:length}}"
        metadata_raw = await run_subprocess(
            ["playerctl", "metadata", "--format", metadata_format]
        )
        title, artist, album, length_str = (
            metadata_raw.split("||", 3) + ["", "", "", ""]
        )[:4]

        # Get remaining properties
        position_str, shuffle_str, loop_str = await asyncio.gather(
            run_subprocess(["playerctl", "position"]),
            run_subprocess(["playerctl", "shuffle"]),
            run_subprocess(["playerctl", "loop"]),
        )

        repeat_map = {"None": "NONE", "Track": "ONE", "Playlist": "ALL"}

        return {
            "title": title,
            "artist": artist,
            "album_title": album,
            "status": status,
            "position_sec": int(float(position_str)) if position_str else 0,
            "duration_sec": int(int(length_str) / 1_000_000) if length_str else 0,
            "is_shuffle_active": shuffle_str == "On",
            "repeat_mode": repeat_map.get(loop_str, "NONE"),
        }
    except (FileNotFoundError, subprocess.CalledProcessError, ValueError):
        return DEFAULT_MEDIA_INFO


async def _get_media_info_darwin() -> Dict[str, str]:
    """Fetches media info on macOS using AppleScript asynchronously."""
    script = """
    on getTrackInfo(appName)
        tell application appName
            if player state is playing or player state is paused then
                set track_artist to artist of current track
                set track_title to name of current track
                set track_album to album of current track
                set track_duration to duration of current track
                set track_position to player position
                set track_state to (player state as string)
                return track_state & "||" & track_artist & "||" & track_title & "||" & track_album & "||" & track_position & "||" & track_duration
            end if
        end tell
        return ""
    end getTrackInfo

    tell application "System Events"
        if (name of processes) contains "Spotify" then
            set info to my getTrackInfo("Spotify")
            if info is not "" then return info
        end if
        if (name of processes) contains "Music" then
            set info to my getTrackInfo("Music")
            if info is not "" then return info
        end if
    end tell
    return ""
    """
    try:
        result = await run_subprocess(["osascript", "-e", script])
        if not result:
            return DEFAULT_MEDIA_INFO

        parts = result.split("||", 5)
        if len(parts) != 6:
            return DEFAULT_MEDIA_INFO

        state, artist, title, album, position, duration = parts
        status_map = {"playing": "PLAYING", "paused": "PAUSED", "stopped": "STOPPED"}

        return {
            "title": title,
            "artist": artist,
            "album_title": album,
            "status": status_map.get(state, "STOPPED"),
            "position_sec": int(float(position)),
            "duration_sec": int(float(duration)),
            "is_shuffle_active": False,  # Default value
            "repeat_mode": "NONE",  # Default value
        }
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        return DEFAULT_MEDIA_INFO


class NetworkMonitor:
    def __init__(self):
        self.last_update_time = time.time()
        self.last_io_counters = psutil.net_io_counters()

    def get_speed(self) -> Dict[str, float]:
        current_time = time.time()
        current_io_counters = psutil.net_io_counters()
        time_delta = current_time - self.last_update_time
        if time_delta < 0.1:
            return {"upload_mbps": 0.0, "download_mbps": 0.0}

        bytes_sent_delta = (
            current_io_counters.bytes_sent - self.last_io_counters.bytes_sent
        )
        bytes_recv_delta = (
            current_io_counters.bytes_recv - self.last_io_counters.bytes_recv
        )

        upload_speed_mbps = (bytes_sent_delta * 8 / time_delta) / 1_000_000
        download_speed_mbps = (bytes_recv_delta * 8 / time_delta) / 1_000_000

        self.last_update_time = current_time
        self.last_io_counters = current_io_counters

        return {
            "upload_mbps": round(upload_speed_mbps, 2),
            "download_mbps": round(download_speed_mbps, 2),
        }


async def get_media_info_data() -> Dict[str, str]:
    if sys.platform == "win32":
        return await _get_media_info_win32()
    if sys.platform == "darwin":
        return await _get_media_info_darwin()
    if sys.platform.startswith("linux"):
        return await _get_media_info_linux()

    return DEFAULT_MEDIA_INFO


def _get_sync_system_info(network_monitor: NetworkMonitor) -> Dict:
    """Synchronous helper to gather system info."""
    mem = psutil.virtual_memory()
    cpu_freq = psutil.cpu_freq()
    return {
        "os": f"{platform.system()} {platform.release()}",
        "hostname": socket.gethostname(),
        "cpu": {
            "percent": psutil.cpu_percent(interval=None),
            "physical_cores": psutil.cpu_count(logical=False),
            "total_cores": psutil.cpu_count(logical=True),
            "current_freq_mhz": cpu_freq.current if cpu_freq else 0,
        },
        "ram": {
            "percent": mem.percent,
            "total_gb": round(mem.total / (1024**3), 2),
            "used_gb": round(mem.used / (1024**3), 2),
        },
        "network_speed": network_monitor.get_speed(),
    }


async def get_system_info_data(network_monitor: NetworkMonitor) -> Dict:
    """Asynchronously gets system info by running sync calls in a thread pool."""
    return await asyncio.to_thread(_get_sync_system_info, network_monitor)


mouse_controller = MouseController()
keyboard_controller = KeyboardController()
button_map = {"left": Button.left, "right": Button.right, "middle": Button.middle}
key_map = {
    "enter": Key.enter,
    "esc": Key.esc,
    "shift": Key.shift,
    "ctrl": Key.ctrl,
    "alt": Key.alt,
    "cmd": Key.cmd,
    "win": Key.cmd,
    "backspace": Key.backspace,
    "delete": Key.delete,
    "tab": Key.tab,
    "space": Key.space,
    "up": Key.up,
    "down": Key.down,
    "left": Key.left,
    "right": Key.right,
    "f1": Key.f1,
    "f2": Key.f2,
    "f3": Key.f3,
    "f4": Key.f4,
    "f5": Key.f5,
    "f6": Key.f6,
    "f7": Key.f7,
    "f8": Key.f8,
    "f9": Key.f9,
    "f10": Key.f10,
    "f11": Key.f11,
    "f12": Key.f12,
}


def get_key(key_str: str):
    return key_map.get(key_str.lower(), key_str)