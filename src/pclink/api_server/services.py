# src/pclink/api_server/services.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import logging
import platform
import socket
import subprocess
import sys
import time
from typing import Dict, List, Optional, Any

import psutil

# --- Imports for Input Control ---
try:
    from pynput.keyboard import Controller as KeyboardController
    from pynput.keyboard import Key
    from pynput.mouse import Button
    from pynput.mouse import Controller as MouseController
    PYNPUT_AVAILABLE = True
except ImportError:
    PYNPUT_AVAILABLE = False

# --- Imports for Legacy Window Scraping (Windows) ---
try:
    import win32gui
    import win32process
    import comtypes
    from comtypes import CLSCTX_ALL, CoInitialize, CoUninitialize
    from pycaw.pycaw import AudioUtilities
    LEGACY_SUPPORT_AVAILABLE = True
except ImportError:
    LEGACY_SUPPORT_AVAILABLE = False

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
    "control_level": "basic",
    "source_app": None
}

SUBPROCESS_FLAGS = 0
if sys.platform == "win32":
    SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW

# --- Cache State ---
_media_info_cache = {
    "data": DEFAULT_MEDIA_INFO, 
    "timestamp": 0,
    "last_valid_data": None,
    "last_valid_time": 0
}
_MEDIA_CACHE_TTL = 1.0  # Reduced to 1s for snappier updates
_LEGACY_STATE_RETENTION = 5.0 

# --- Legacy Player Config ---
KNOWN_LEGACY_PLAYERS = {
    "vlc.exe": "VLC",
    "mpc-hc.exe": "MPC-HC",
    "mpc-hc64.exe": "MPC-HC",
    "mpc-be.exe": "MPC-BE",
    "mpc-be64.exe": "MPC-BE",
    "potplayer.exe": "PotPlayer",
    "potplayermini.exe": "PotPlayer",
    "potplayermini64.exe": "PotPlayer",
    "kmplayer.exe": "KMPlayer",
    "kmplayer64.exe": "KMPlayer",
    "wmplayer.exe": "Windows Media Player",
    "gom.exe": "GOM Player",
    "gomplayerplus.exe": "GOM Player Plus",
    "spotify.exe": "Spotify",
    "itunes.exe": "iTunes",
    "foobar2000.exe": "foobar2000",
    "aimp.exe": "AIMP",
    "musicbee.exe": "MusicBee",
    "winamp.exe": "Winamp",
    "chrome.exe": "Chrome",
    "firefox.exe": "Firefox",
    "msedge.exe": "Edge",
    "opera.exe": "Opera",
    "brave.exe": "Brave",
}

TITLE_CLEANUP_PATTERNS = [
    " - YouTube", " - Spotify", " - SoundCloud", " - Twitch", " - Netflix",
    " - Disney+", " - Prime Video", " - Apple Music", " - Tidal", " - Deezer",
    " - Pandora", " - YouTube Music", " - VLC media player", 
    "[Paused]", "[Stopped]", "(Paused)", "(Stopped)",
]

async def run_subprocess(cmd: list[str]) -> str:
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        creationflags=SUBPROCESS_FLAGS,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise subprocess.CalledProcessError(process.returncode, cmd, output=stdout, stderr=stderr)
    return stdout.decode().strip()

# --- Legacy Helper Functions ---

def _clean_media_title(title: str, app_name: str) -> tuple[Optional[str], Optional[str]]:
    if not title or title.strip() == app_name:
        return None, None
    
    clean_title = title
    for suffix in [f" - {app_name}", f" — {app_name}", f"- {app_name}"]:
        if clean_title.endswith(suffix):
            clean_title = clean_title[:-len(suffix)]
    
    clean_title = clean_title.replace(app_name, "").strip()
    for pattern in TITLE_CLEANUP_PATTERNS:
        clean_title = clean_title.replace(pattern, "")
    
    clean_title = clean_title.strip(" -—|")
    if not clean_title or len(clean_title) < 2:
        return None, None
    
    artist = None
    song_title = clean_title
    for separator in [" - ", " — ", " – "]:
        if separator in clean_title:
            parts = clean_title.split(separator, 1)
            if len(parts[0]) < len(parts[1]):
                artist = parts[0].strip()
                song_title = parts[1].strip()
            else:
                song_title = parts[0].strip()
                artist = parts[1].strip()
            break
    return song_title, artist

def _get_audible_pids_sync() -> set[int]:
    """Returns a set of PIDs that currently have an active audio session on Windows."""
    audible_pids = set()
    if not LEGACY_SUPPORT_AVAILABLE:
        return audible_pids
    
    try:
        CoInitialize()
        sessions = AudioUtilities.GetAllSessions()
        for session in sessions:
            if session.Process and session.State == 1: # 1 = AudioSessionStateActive
                audible_pids.add(session.ProcessId)
    except Exception as e:
        log.debug(f"Error getting audio sessions: {e}")
    finally:
        try:
            CoUninitialize()
        except Exception: pass
    return audible_pids

def _get_legacy_media_info_sync() -> Optional[Dict[str, Any]]:
    if not LEGACY_SUPPORT_AVAILABLE:
        return None

    audible_pids = _get_audible_pids_sync()
    found_media = None
    best_match_priority = -1 

    def enum_window_callback(hwnd, _):
        nonlocal found_media, best_match_priority
        if not win32gui.IsWindowVisible(hwnd): return
        try:
            length = win32gui.GetWindowTextLength(hwnd)
            if length == 0: return
            
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            try:
                proc = psutil.Process(pid)
                proc_name = proc.name().lower()
            except (psutil.NoSuchProcess, psutil.AccessDenied): return

            if proc_name not in KNOWN_LEGACY_PLAYERS: return
            
            # Browser Filter: Only accept browsers if they have an active audio session
            if proc_name in ["chrome.exe", "firefox.exe", "msedge.exe", "opera.exe", "brave.exe"]:
                if pid not in audible_pids:
                    return

            app_name = KNOWN_LEGACY_PLAYERS[proc_name]
            title = win32gui.GetWindowText(hwnd)
            song_title, artist = _clean_media_title(title, app_name)
            
            if not song_title: return
            
            # Priority: Dedicated players > Browsers with audio
            priority = 10 if proc_name not in ["chrome.exe", "firefox.exe", "msedge.exe", "opera.exe", "brave.exe"] else 5
            
            if priority > best_match_priority:
                best_match_priority = priority
                found_media = {
                    "title": song_title,
                    "artist": artist or "",
                    "album_title": "",
                    "status": "PLAYING", # If it has audio and a title, it's likely playing
                    "position_sec": 0,
                    "duration_sec": 0,
                    "is_shuffle_active": False,
                    "repeat_mode": "NONE",
                    "control_level": "basic",
                    "source_app": f"{app_name} (Legacy)"
                }
        except Exception: pass

    try:
        win32gui.EnumWindows(enum_window_callback, None)
    except Exception: pass
    
    return found_media

# --- OS Specific Fetchers ---

async def _get_media_info_win32() -> Dict[str, Any]:
    # 1. Try Modern SMTC
    smtc_data = None
    try:
        from winsdk.windows.media import MediaPlaybackAutoRepeatMode
        from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as MediaManager

        manager = await MediaManager.request_async()
        session = manager.get_current_session()
        
        if session:
            info = await session.try_get_media_properties_async()
            playback_info = session.get_playback_info()
            timeline = session.get_timeline_properties()

            status_map = {0: "STOPPED", 1: "PAUSED", 2: "STOPPED", 3: "STOPPED", 4: "PLAYING", 5: "PAUSED"}
            status = status_map.get(playback_info.playback_status, "STOPPED")
            
            # Check if data looks valid (ignore "Unknown" or empty titles)
            clean_title = (info.title or "").strip()
            if clean_title and clean_title.lower() not in ["", "unknown", "none"]:
                repeat_map = {
                    MediaPlaybackAutoRepeatMode.NONE: "NONE",
                    MediaPlaybackAutoRepeatMode.TRACK: "ONE",
                    MediaPlaybackAutoRepeatMode.LIST: "ALL",
                }
                smtc_data = {
                    "title": info.title,
                    "artist": info.artist or "",
                    "album_title": info.album_title or "",
                    "status": status,
                    "position_sec": int(timeline.position.total_seconds()),
                    "duration_sec": int(timeline.end_time.total_seconds()),
                    "is_shuffle_active": playback_info.is_shuffle_active or False,
                    "repeat_mode": repeat_map.get(playback_info.auto_repeat_mode, "NONE"),
                    "control_level": "full",
                    "source_app": "Windows Media"
                }
    except Exception: pass

    # 2. Try Legacy (Scraping windows with audio session verification)
    legacy_data = await asyncio.to_thread(_get_legacy_media_info_sync)

    # 3. Decision Logic
    # 3a. If SMTC is PLAYING, use it (highest confidence)
    if smtc_data and smtc_data["status"] == "PLAYING":
        return smtc_data
    
    # 3b. If Legacy is found (verified by audio sessions), use it
    if legacy_data:
        # If SMTC is also PAUSED, decide which is better.
        # Usually, SMTC is more accurate for modern apps, but legacy handles browsers better with our PID check.
        # If legacy is playing, it takes preference over a paused SMTC session.
        return legacy_data
        
    # 3c. Fallback to PAUSED SMTC data
    if smtc_data and smtc_data["title"]:
        return smtc_data
        
    return DEFAULT_MEDIA_INFO.copy()

async def _get_media_info_linux() -> Dict[str, Any]:
    try:
        status_raw = await run_subprocess(["playerctl", "status"])
        status_map = {"Playing": "PLAYING", "Paused": "PAUSED", "Stopped": "STOPPED"}
        status = status_map.get(status_raw, "STOPPED")

        if status == "STOPPED": return DEFAULT_MEDIA_INFO.copy()

        metadata_format = "{{title}}||{{artist}}||{{album}}||{{mpris:length}}"
        metadata_raw = await run_subprocess(["playerctl", "metadata", "--format", metadata_format])
        title, artist, album, length_str = (metadata_raw.split("||", 3) + ["", "", "", ""])[:4]

        position_str, shuffle_str, loop_str = await asyncio.gather(
            run_subprocess(["playerctl", "position"]),
            run_subprocess(["playerctl", "shuffle"]),
            run_subprocess(["playerctl", "loop"]),
        )
        
        return {
            "title": title,
            "artist": artist,
            "album_title": album,
            "status": status,
            "position_sec": int(float(position_str)) if position_str else 0,
            "duration_sec": int(int(length_str) / 1_000_000) if length_str else 0,
            "is_shuffle_active": shuffle_str == "On",
            "repeat_mode": {"None": "NONE", "Track": "ONE", "Playlist": "ALL"}.get(loop_str, "NONE"),
            "control_level": "full",
            "source_app": "Playerctl"
        }
    except Exception:
        return DEFAULT_MEDIA_INFO.copy()

async def _get_media_info_darwin() -> Dict[str, Any]:
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
        if not result: return DEFAULT_MEDIA_INFO.copy()
        
        parts = result.split("||", 5)
        if len(parts) != 6: return DEFAULT_MEDIA_INFO.copy()
        
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
            "control_level": "basic",
            "source_app": "macOS Script"
        }
    except Exception:
        return DEFAULT_MEDIA_INFO.copy()

# --- Main Public Function ---

async def get_media_info_data() -> Dict[str, Any]:
    current_time = time.time()
    
    # 1. Check short-term cache
    if (_media_info_cache["data"] is not None and 
        _media_info_cache["data"].get("title") != "Nothing Playing" and
        current_time - _media_info_cache["timestamp"] < _MEDIA_CACHE_TTL):
        return _media_info_cache["data"]
    
    # 2. Fetch OS Data
    if sys.platform == "win32":
        data = await _get_media_info_win32()
    elif sys.platform == "darwin":
        data = await _get_media_info_darwin()
    elif sys.platform.startswith("linux"):
        data = await _get_media_info_linux()
    else:
        data = DEFAULT_MEDIA_INFO.copy()
    
    # 3. Sticky Logic for Legacy/Flickering
    is_empty = (data.get("status") in ["STOPPED", "NO_SESSION", "INACTIVE"] 
                or data.get("title") in ["Nothing Playing", "Unknown", ""])
    
    last_valid = _media_info_cache.get("last_valid_data")
    last_time = _media_info_cache.get("last_valid_time", 0)

    # If current is empty but we had valid data recently
    if is_empty and last_valid and (current_time - last_time < _LEGACY_STATE_RETENTION):
        # Infer PAUSED state
        synthetic_data = last_valid.copy()
        if last_valid.get("status") == "PLAYING":
            synthetic_data["status"] = "PAUSED"
        _media_info_cache["data"] = synthetic_data
        _media_info_cache["timestamp"] = current_time
        return synthetic_data

    # 4. Update Cache
    _media_info_cache["data"] = data
    _media_info_cache["timestamp"] = current_time
    
    if not is_empty and data.get("title") != "Nothing Playing":
        _media_info_cache["last_valid_data"] = data
        _media_info_cache["last_valid_time"] = current_time
        
    return data

# --- System Info Helpers (Unchanged) ---

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

        bytes_sent_delta = current_io_counters.bytes_sent - self.last_io_counters.bytes_sent
        bytes_recv_delta = current_io_counters.bytes_recv - self.last_io_counters.bytes_recv

        upload_speed_mbps = (bytes_sent_delta * 8 / time_delta) / 1_000_000
        download_speed_mbps = (bytes_recv_delta * 8 / time_delta) / 1_000_000

        self.last_update_time = current_time
        self.last_io_counters = current_io_counters

        return {
            "upload_mbps": round(upload_speed_mbps, 2),
            "download_mbps": round(download_speed_mbps, 2),
        }

def _get_sync_system_info(network_monitor: NetworkMonitor) -> Dict:
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    cpu_freq = psutil.cpu_freq()
    boot_timestamp = psutil.boot_time()
    uptime_seconds = time.time() - boot_timestamp
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
        except Exception: pass

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
        "network": {
            "speed": current_speed,
            "io_total": psutil.net_io_counters()._asdict(),
        },
        "network_speed": current_speed,
        "sensors": temps_info,
    }

async def get_system_info_data(network_monitor: NetworkMonitor) -> Dict:
    return await asyncio.to_thread(_get_sync_system_info, network_monitor)

def _get_sync_disks_info() -> Dict[str, List]:
    disks = []
    try:
        partitions = psutil.disk_partitions(all=False)
        for p in partitions:
            if not p.fstype: continue
            if sys.platform.startswith("linux") and p.device.startswith(("/dev/loop", "/dev/snap")): continue
            try:
                usage = psutil.disk_usage(p.mountpoint)
                disks.append({
                    "device": p.device,
                    "total": f"{round(usage.total / (1024**3), 1)} GB",
                    "used": f"{round(usage.used / (1024**3), 1)} GB",
                    "free": f"{round(usage.free / (1024**3), 1)} GB",
                    "percent": int(usage.percent),
                })
            except Exception: continue
        return {"disks": disks}
    except Exception: return {"disks": []}

async def get_disks_info_data() -> Dict[str, List]:
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
    "enter": Key.enter, "esc": Key.esc, "shift": Key.shift, "ctrl": Key.ctrl, "alt": Key.alt,
    "cmd": Key.cmd, "win": Key.cmd, "backspace": Key.backspace, "delete": Key.delete, "tab": Key.tab,
    "space": Key.space, "up": Key.up, "down": Key.down, "left": Key.left, "right": Key.right,
    "f1": Key.f1, "f2": Key.f2, "f3": Key.f3, "f4": Key.f4, "f5": Key.f5, "f6": Key.f6,
    "f7": Key.f7, "f8": Key.f8, "f9": Key.f9, "f10": Key.f10, "f11": Key.f11, "f12": Key.f12,
}

def get_key(key_str: str):
    return key_map.get(key_str.lower(), key_str)