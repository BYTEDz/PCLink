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
from typing import Dict, List

import psutil
try:
    from pynput.keyboard import Controller as KeyboardController
    from pynput.keyboard import Key
    from pynput.mouse import Button
    from pynput.mouse import Controller as MouseController
    PYNPUT_AVAILABLE = True
except ImportError:
    PYNPUT_AVAILABLE = False
    log = logging.getLogger(__name__)
    log.warning("pynput not available - input control features disabled")

log = logging.getLogger(__name__)
DEFAULT_MEDIA_INFO = {
    "title": "Nothing Playing",
    "artist": "",
    "album_title": "",
    "status": "STOPPED",
    "position_sec": 0,
    "duration_sec": 0,
    "is_shuffle_active": False,
    "repeat_mode": "NONE",
}

SUBPROCESS_FLAGS = 0
if sys.platform == "win32":
    SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW


async def run_subprocess(cmd: list[str]) -> str:
    """
    Asynchronously runs a subprocess and returns its stdout.

    Args:
        cmd: A list of strings representing the command and its arguments.

    Returns:
        The decoded and stripped stdout from the subprocess.

    Raises:
        subprocess.CalledProcessError: If the command returns a non-zero exit code.
    """
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


async def _get_media_info_win32() -> Dict[str, str]:
    """
    Fetches media information on Windows using the Windows SDK.

    Returns:
        A dictionary containing media playback information. Returns default
        values if media is not playing or if the SDK is unavailable/fails.
    """
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
            0: "STOPPED",
            1: "PAUSED",
            2: "STOPPED",
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
        return DEFAULT_MEDIA_INFO
    except Exception:
        return DEFAULT_MEDIA_INFO


async def _get_media_info_linux() -> Dict[str, str]:
    """
    Fetches media information on Linux using `playerctl` asynchronously.

    Returns:
        A dictionary containing media playback information. Returns default
        values if no media player is active or if `playerctl` is not found.
    """
    try:
        status_raw = await run_subprocess(["playerctl", "status"])
        status_map = {"Playing": "PLAYING", "Paused": "PAUSED", "Stopped": "STOPPED"}
        status = status_map.get(status_raw, "STOPPED")

        if status == "STOPPED":
            return DEFAULT_MEDIA_INFO

        metadata_format = "{{title}}||{{artist}}||{{album}}||{{mpris:length}}"
        metadata_raw = await run_subprocess(
            ["playerctl", "metadata", "--format", metadata_format]
        )
        title, artist, album, length_str = (
            metadata_raw.split("||", 3) + ["", "", "", ""]
        )[:4]

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
    """
    Fetches media information on macOS using AppleScript asynchronously.

    Supports Spotify and Music applications.

    Returns:
        A dictionary containing media playback information. Returns default
        values if no supported media player is active or if AppleScript fails.
    """
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
            "is_shuffle_active": False,
            "repeat_mode": "NONE",
        }
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        return DEFAULT_MEDIA_INFO


class NetworkMonitor:
    """
    Monitors network speed by calculating the difference in I/O counters over time.
    """
    def __init__(self):
        self.last_update_time = time.time()
        self.last_io_counters = psutil.net_io_counters()

    def get_speed(self) -> Dict[str, float]:
        """
        Calculates and returns the current upload and download speeds in Mbps.

        Returns:
            A dictionary with 'upload_mbps' and 'download_mbps'.
        """
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
    """
    Retrieves media playback information based on the operating system.

    Returns:
        A dictionary containing media playback details.
    """
    if sys.platform == "win32":
        return await _get_media_info_win32()
    if sys.platform == "darwin":
        return await _get_media_info_darwin()
    if sys.platform.startswith("linux"):
        return await _get_media_info_linux()

    return DEFAULT_MEDIA_INFO


def _get_sync_system_info(network_monitor: NetworkMonitor) -> Dict:
    """
    Synchronously gathers a comprehensive set of system information using psutil.

    Args:
        network_monitor: An instance of NetworkMonitor to get real-time network speed.

    Returns:
        A dictionary containing detailed system, CPU, RAM, swap, and network info.
    """
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    cpu_freq = psutil.cpu_freq()
    boot_timestamp = psutil.boot_time()
    uptime_seconds = time.time() - boot_timestamp

    # Get network speed once to use in both old and new data structures
    current_speed = network_monitor.get_speed()

    temps_info = {}
    if hasattr(psutil, "sensors_temperatures"):
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                if 'coretemp' in temps and temps['coretemp']:
                    temps_info['cpu_temp_celsius'] = temps['coretemp'][0].current
                elif 'k10temp' in temps and temps['k10temp']:
                    temps_info['cpu_temp_celsius'] = temps['k10temp'][0].current
        except Exception:
            pass

    return {
        "os": f"{platform.system()} {platform.release()}",
        "hostname": socket.gethostname(),
        "uptime_seconds": int(uptime_seconds),
        "cpu": {
            "percent": psutil.cpu_percent(interval=None),
            "per_cpu_percent": psutil.cpu_percent(interval=None, percpu=True),
            "physical_cores": psutil.cpu_count(logical=False),
            "total_cores": psutil.cpu_count(logical=True),
            "current_freq_mhz": cpu_freq.current if cpu_freq else None,
            "max_freq_mhz": cpu_freq.max if cpu_freq else None,
            "min_freq_mhz": cpu_freq.min if cpu_freq else None,
            "times_percent": psutil.cpu_times_percent()._asdict(),
        },
        "ram": {
            "percent": mem.percent,
            "total_gb": round(mem.total / (1024**3), 2),
            "used_gb": round(mem.used / (1024**3), 2),
            "available_gb": round(mem.available / (1024**3), 2),
        },
        "swap": {
            "percent": swap.percent,
            "total_gb": round(swap.total / (1024**3), 2),
            "used_gb": round(swap.used / (1024**3), 2),
            "free_gb": round(swap.free / (1024**3), 2),
        },
        # The new, richer network object for updated clients
        "network": {
            "speed": current_speed,
            "io_total": psutil.net_io_counters()._asdict(),
        },
        # FIX: Restore the original 'network_speed' key for backward compatibility
        "network_speed": current_speed,
        "sensors": temps_info,
    }


async def get_system_info_data(network_monitor: NetworkMonitor) -> Dict:
    """
    Asynchronously retrieves system information by running synchronous calls
    in a thread pool executor.

    Args:
        network_monitor: An instance of NetworkMonitor to get network speed.

    Returns:
        A dictionary containing system, CPU, RAM, and network speed information.
    """
    return await asyncio.to_thread(_get_sync_system_info, network_monitor)


def _get_sync_disks_info() -> Dict[str, List]:
    """
    Synchronously gathers detailed information about all physical disk partitions.
    Filters out virtual filesystems, loop devices, and CD-ROMs.
    """
    disks = []
    try:
        partitions = psutil.disk_partitions(all=False)
        for p in partitions:
            if not p.fstype:
                continue

            if sys.platform.startswith("linux") and p.device.startswith(("/dev/loop", "/dev/snap")):
                continue

            try:
                usage = psutil.disk_usage(p.mountpoint)
                disks.append({
                    "device": p.device,
                    "total": f"{round(usage.total / (1024**3), 1)} GB",
                    "used": f"{round(usage.used / (1024**3), 1)} GB",
                    "free": f"{round(usage.free / (1024**3), 1)} GB",
                    "percent": int(usage.percent),
                })
            except (PermissionError, FileNotFoundError):
                log.warning(f"Could not access disk usage for {p.mountpoint}")
                continue
        return {"disks": disks}
    except Exception as e:
        log.error(f"An unexpected error occurred while getting disk info: {e}")
        return {"disks": []}


async def get_disks_info_data() -> Dict[str, List]:
    """
    Asynchronously retrieves disk information for all physical drives.
    """
    return await asyncio.to_thread(_get_sync_disks_info)


if PYNPUT_AVAILABLE:
    mouse_controller = MouseController()
    keyboard_controller = KeyboardController()
else:
    mouse_controller = None
    keyboard_controller = None

if PYNPUT_AVAILABLE:
    button_map = {"left": Button.left, "right": Button.right, "middle": Button.middle}
else:
    button_map = {}

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
    "f1": Key.f1, "f2": Key.f2, "f3": Key.f3, "f4": Key.f4,
    "f5": Key.f5, "f6": Key.f6, "f7": Key.f7, "f8": Key.f8,
    "f9": Key.f9, "f10": Key.f10, "f11": Key.f11, "f12": Key.f12,
}


def get_key(key_str: str):
    """
    Converts a string representation of a key to a pynput Key object.

    Args:
        key_str: The string representation of the key (e.g., "enter", "a").

    Returns:
        A pynput Key object or the original string if it's not a special key.
    """
    return key_map.get(key_str.lower(), key_str)