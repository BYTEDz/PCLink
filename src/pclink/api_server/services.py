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

# --- Native Input Control ---
try:
    from pynput.keyboard import Controller as KeyboardController
    from pynput.keyboard import Key
    from pynput.mouse import Button
    from pynput.mouse import Controller as MouseController
    PYNPUT_AVAILABLE = True
except ImportError:
    PYNPUT_AVAILABLE = False

# --- Windows Legacy Scraping ---
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

# Default state for UI when no media is active
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

_MEDIA_CACHE_TTL = 1.0        # Refresh rate for active media
_LEGACY_STATE_RETENTION = 5.0  # Time to hold last known state (flicker prevention)
_COMMAND_STICKY_TIME = 3.0     # Time to prefer predicted state after command

# --- Media State Cache ---
_media_info_cache = {
    "data": DEFAULT_MEDIA_INFO, 
    "timestamp": 0,
    "last_valid_data": None,
    "last_valid_time": 0,
    "command_lock_target": None, # "PLAYING" or "PAUSED"
    "command_lock_until": 0
}

# --- Known Media Players (Windows Legacy) ---
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
    """Helper to run async subprocesses with hidden windows on Windows."""
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

# ==============================================================================
# MEDIA INFORMATION SERVICE
# ==============================================================================

def _clean_media_title(title: str, app_name: str) -> tuple[Optional[str], Optional[str]]:
    """Strips app names and common suffixes from window titles to extract song/artist."""
    if not title or title.strip() == app_name:
        return None, None
    
    clean_title = title
    for suffix in [f" - {app_name}", f" — {app_name}", f"- {app_name}"]:
        if clean_title.endswith(suffix):
            clean_title = clean_title[:-len(suffix)]
    
    clean_title = clean_title.replace(app_name, "").strip()
    # Explicitly remove VLC suffix which often stays
    if app_name == "VLC":
        clean_title = clean_title.replace(" - VLC media player", "").strip()

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
    """Uses PyCaw to identify PIDs currently outputting audio."""
    audible_pids = set()
    if not LEGACY_SUPPORT_AVAILABLE:
        return audible_pids
    
    try:
        CoInitialize()
        sessions = AudioUtilities.GetAllSessions()
        for session in sessions:
            if session.Process and session.State == 1: # AudioSessionStateActive
                audible_pids.add(session.ProcessId)
    except Exception as e:
        log.debug(f"Audio session scan failed: {e}")
    finally:
        try:
            CoUninitialize()
        except Exception: pass
    return audible_pids

def _get_legacy_media_info_sync() -> Optional[Dict[str, Any]]:
    """Windows Fallback: Scrapes window titles and verifies via audio session."""
    if not LEGACY_SUPPORT_AVAILABLE:
        return None

    audible_pids = _get_audible_pids_sync()
    found_media = None
    best_priority = -1 

    def enum_window_callback(hwnd, _):
        nonlocal found_media, best_priority
        if not win32gui.IsWindowVisible(hwnd): return
        try:
            length = win32gui.GetWindowTextLength(hwnd)
            if length == 0: return
            
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            try:
                proc = psutil.Process(pid)
                name = proc.name().lower()
            except (psutil.NoSuchProcess, psutil.AccessDenied): return

            if name not in KNOWN_LEGACY_PLAYERS: return
            
            # For browsers, only accept if they are actually making noise
            if name in ["chrome.exe", "firefox.exe", "msedge.exe", "opera.exe", "brave.exe"]:
                if pid not in audible_pids:
                    return

            app_display_name = KNOWN_LEGACY_PLAYERS[name]
            title = win32gui.GetWindowText(hwnd)
            
            # Detect status before cleaning title
            status = "PLAYING"
            # More comprehensive status detection from title
            lc_title = title.lower()
            if any(p in lc_title for p in ["[paused]", "(paused)", " - paused", "paused:"]):
                status = "PAUSED"
            elif any(p in lc_title for p in ["[stopped]", "(stopped)", " - stopped"]):
                status = "STOPPED"

            song, artist = _clean_media_title(title, app_display_name)
            
            if not song: return
            
            # Prioritize dedicated players over browsers
            priority = 10 if "browser" not in app_display_name.lower() else 5
            
            if priority > best_priority:
                best_priority = priority
                found_media = {
                    "title": song,
                    "artist": artist or "",
                    "album_title": "",
                    "status": status,
                    "position_sec": 0,
                    "duration_sec": 0,
                    "is_shuffle_active": False,
                    "repeat_mode": "NONE",
                    "control_level": "basic",
                    "source_app": f"{app_display_name} (Legacy)",
                    "_hwnd": hwnd  # Private field for targeted control
                }
        except Exception: pass

    try:
        win32gui.EnumWindows(enum_window_callback, None)
    except Exception: pass
    
    return found_media

# --- Platform Implementation: Windows ---

async def _get_media_info_win32() -> Dict[str, Any]:
    smtc_data = None
    try:
        from winsdk.windows.media import MediaPlaybackAutoRepeatMode
        from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as MediaManager

        manager = await MediaManager.request_async()
        session = manager.get_current_session()
        
        if session:
            info = await session.try_get_media_properties_async()
            playback = session.get_playback_info()
            timeline = session.get_timeline_properties()

            status_map = {0: "STOPPED", 1: "PAUSED", 2: "STOPPED", 3: "STOPPED", 4: "PLAYING", 5: "PAUSED"}
            status = status_map.get(playback.playback_status, "STOPPED")
            
            if info.title and info.title.lower() not in ["", "unknown", "none"]:
                rep_map = {
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
                    "is_shuffle_active": playback.is_shuffle_active or False,
                    "repeat_mode": rep_map.get(playback.auto_repeat_mode, "NONE"),
                    "control_level": "full",
                    "source_app": "System Media"
                }
    except Exception: pass

    # Fallback/Merge with legacy scraping
    legacy_data = await asyncio.to_thread(_get_legacy_media_info_sync)

    # Source Prioritization & Merging Logic
    # 1. If we have legacy data for a known dedicated player (like VLC), 
    #    we prefer it to keep the UI in "Legacy Mode" (no flickers).
    if legacy_data and "(Legacy)" in legacy_data.get("source_app", ""):
        # If SMTC is also seeing something with a similar title, merge the details
        # (SMTC often has better duration/playback info)
        if smtc_data and (smtc_data["title"].lower() in legacy_data["title"].lower() or 
                          legacy_data["title"].lower() in smtc_data["title"].lower()):
            legacy_data.update({
                "position_sec": smtc_data["position_sec"],
                "duration_sec": smtc_data["duration_sec"],
                "is_shuffle_active": smtc_data["is_shuffle_active"],
                "repeat_mode": smtc_data["repeat_mode"],
                "control_level": smtc_data["control_level"]
            })
            # Prefer SMTC status if it's not STOPPED (more accurate for "Paused" vs "Stopped")
            if smtc_data["status"] != "STOPPED":
                legacy_data["status"] = smtc_data["status"]
        
        return legacy_data

    # 2. Otherwise, prefer SMTC (modern apps like Firefox/Spotify)
    if smtc_data and smtc_data["title"] and smtc_data["title"].lower() not in ["", "unknown"]:
        return smtc_data
    
    # 3. Last fallback
    return legacy_data if legacy_data else DEFAULT_MEDIA_INFO.copy()

# --- Platform Implementation: Linux ---

async def _get_media_info_linux() -> Dict[str, Any]:
    try:
        status_raw = await run_subprocess(["playerctl", "status"])
        status_map = {"Playing": "PLAYING", "Paused": "PAUSED", "Stopped": "STOPPED"}
        status = status_map.get(status_raw, "STOPPED")

        if status == "STOPPED": return DEFAULT_MEDIA_INFO.copy()

        fmt = "{{title}}||{{artist}}||{{album}}||{{mpris:length}}"
        meta = await run_subprocess(["playerctl", "metadata", "--format", fmt])
        title, artist, album, length = (meta.split("||", 3) + ["", "", "", ""])[:4]

        pos, shuffle, loop = await asyncio.gather(
            run_subprocess(["playerctl", "position"]),
            run_subprocess(["playerctl", "shuffle"]),
            run_subprocess(["playerctl", "loop"]),
            return_exceptions=True
        )
        
        # Handle potential errors in gather
        pos_val = int(float(pos)) if isinstance(pos, str) and pos else 0
        shuffle_active = shuffle == "On" if isinstance(shuffle, str) else False
        repeat_mode = {"None": "NONE", "Track": "ONE", "Playlist": "ALL"}.get(loop if isinstance(loop, str) else "None", "NONE")

        return {
            "title": title,
            "artist": artist,
            "album_title": album,
            "status": status,
            "position_sec": pos_val,
            "duration_sec": int(int(length) / 1_000_000) if (isinstance(length, str) and length.isdigit()) else 0,
            "is_shuffle_active": shuffle_active,
            "repeat_mode": repeat_mode,
            "control_level": "full",
            "source_app": "Mpris"
        }
    except Exception:
        return DEFAULT_MEDIA_INFO.copy()

# --- Platform Implementation: macOS ---

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
        set runningApps to name of processes
        if runningApps contains "Spotify" then
            set info to my getTrackInfo("Spotify")
            if info is not "" then return info
        end if
        if runningApps contains "Music" then
            set info to my getTrackInfo("Music")
            if info is not "" then return info
        end if
        if runningApps contains "TV" then
            set info to my getTrackInfo("TV")
            if info is not "" then return info
        end if
        if runningApps contains "QuickTime Player" then
            set info to my getTrackInfo("QuickTime Player")
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
        
        state, artist, title, album, pos, dur = parts
        status_map = {"playing": "PLAYING", "paused": "PAUSED", "stopped": "STOPPED"}
        
        return {
            "title": title,
            "artist": artist,
            "album_title": album,
            "status": status_map.get(state, "STOPPED"),
            "position_sec": int(float(pos)),
            "duration_sec": int(float(dur)),
            "is_shuffle_active": False,
            "repeat_mode": "NONE",
            "control_level": "basic",
            "source_app": "AppleScript"
        }
    except Exception:
        return DEFAULT_MEDIA_INFO.copy()

# ==============================================================================
# SYSTEM INFORMATION SERVICE
# ==============================================================================

async def get_media_info_data() -> Dict[str, Any]:
    """Caches and returns the current media playback state across platforms."""
    now = time.time()
    
    # Return buffered data if within TTL to avoid high-freq syscalls
    if (_media_info_cache["data"] is not None and 
        _media_info_cache["data"].get("title") != "Nothing Playing" and
        now - _media_info_cache["timestamp"] < _MEDIA_CACHE_TTL):
        return _media_info_cache["data"]
    
    if sys.platform == "win32":
        data = await _get_media_info_win32()
    elif sys.platform == "darwin":
        data = await _get_media_info_darwin()
    elif sys.platform.startswith("linux"):
        data = await _get_media_info_linux()
    else:
        data = DEFAULT_MEDIA_INFO.copy()
    
    # State Persistence Logic: Prevents UI from flickering to "Nothing Playing" 
    # during rapid transitions or legacy player metadata gaps.
    is_empty = (data.get("status") in ["STOPPED", "NO_SESSION", "INACTIVE"] 
                or data.get("title") in ["Nothing Playing", "Unknown", ""])
    
    last_valid = _media_info_cache.get("last_valid_data")
    last_time = _media_info_cache.get("last_valid_time", 0)

    if is_empty and last_valid and (now - last_time < _LEGACY_STATE_RETENTION):
        synthetic = last_valid.copy()
        if last_valid.get("status") == "PLAYING":
            synthetic["status"] = "PAUSED"
        _media_info_cache["data"] = synthetic
        _media_info_cache["timestamp"] = now
        return synthetic

    # Sticky status override: Prefer the predicted state if we just sent a command
    lock_target = _media_info_cache.get("command_lock_target")
    lock_until = _media_info_cache.get("command_lock_until", 0)
    
    if lock_target and now < lock_until:
        if data.get("status") != lock_target:
            log.debug(f"Overriding status '{data.get('status')}' with sticky '{lock_target}'")
            data["status"] = lock_target
            # Also update position if we are PAUSED to prevent jumping
            if lock_target == "PAUSED" and last_valid:
                data["position_sec"] = last_valid.get("position_sec", 0)

    _media_info_cache["data"] = data
    _media_info_cache["timestamp"] = now
    
    if not is_empty and data.get("title") != "Nothing Playing":
        _media_info_cache["last_valid_data"] = data
        _media_info_cache["last_valid_time"] = now
        
    return data

class NetworkMonitor:
    """Tracks network I/O throughput to calculate real-time transfer speeds."""
    def __init__(self):
        self.last_update = time.time()
        self.last_io = psutil.net_io_counters()

    def get_speed(self) -> Dict[str, float]:
        now = time.time()
        curr_io = psutil.net_io_counters()
        delta = now - self.last_update
        if delta < 0.1:
            return {"upload_mbps": 0.0, "download_mbps": 0.0}

        up_mbps = ((curr_io.bytes_sent - self.last_io.bytes_sent) * 8 / delta) / 1_000_000
        down_mbps = ((curr_io.bytes_recv - self.last_io.bytes_recv) * 8 / delta) / 1_000_000

        self.last_update = now
        self.last_io = curr_io

        return {
            "upload_mbps": round(up_mbps, 2),
            "download_mbps": round(down_mbps, 2),
        }

def _get_windows_thermals() -> Dict[str, float]:
    """
    Windows Best-Effort Thermal Detection: WMI (BIOS) + Third-party Hooks.
    """
    thermals = {}
    
    # Sources: BIOS ACPI, LibreHardwareMonitor, OpenHardwareMonitor
    ps_commands = [
        "Get-CimInstance -Namespace root/WMI -ClassName MSAcpi_ThermalZoneTemperature | Select-Object -ExpandProperty CurrentTemperature",
        "Get-CimInstance -Namespace root/LibreHardwareMonitor -Query 'Select * from Sensor where SensorType=\"Temperature\"' | Select-Object -Property Name, Value",
        "Get-CimInstance -Namespace root/OpenHardwareMonitor -Query 'Select * from Sensor where SensorType=\"Temperature\"' | Select-Object -Property Name, Value"
    ]

    try:
        # Batch execute to minimize shell spawn overhead
        full_cmd = " ; ".join([f"try {{ {cmd} }} catch {{}}" for cmd in ps_commands])
        process = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", full_cmd],
            capture_output=True, text=True, timeout=2, creationflags=SUBPROCESS_FLAGS
        )
        
        lines = process.stdout.strip().splitlines()
        for line in lines:
            # Type 1: Raw ACPI (reported in Decikelvins)
            if line.strip().isdigit():
                temp_c = (int(line.strip()) - 2732) / 10.0
                if 0 < temp_c < 120: # ACPI sanity range
                    thermals["cpu_temp_celsius"] = round(temp_c, 1)
            
            # Type 2: LHM/OHM sensor pairs (e.g. "CPU Package 45.1")
            elif " " in line:
                parts = line.rsplit(None, 1)
                if len(parts) == 2:
                    name, value = parts
                    try:
                        val = float(value)
                        key = name.lower().replace(" ", "_")
                        # Normalize common sensor labels for dashboard consistency
                        if "cpu" in key and "package" in key:
                            thermals["cpu_temp_celsius"] = val
                        elif "gpu" in key and "core" in key:
                            thermals["gpu_temp_celsius"] = val
                        else:
                            thermals[f"sensor_{key}"] = val
                    except ValueError: pass
    except Exception: pass
    
    return thermals

def _get_sync_system_info(network_monitor: NetworkMonitor) -> Dict:
    """Aggregates all system-level telemetry using psutil and native queries."""
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    freq = psutil.cpu_freq()
    boot = psutil.boot_time()
    uptime = time.time() - boot
    speed = network_monitor.get_speed()

    # --- Thermal Detection (Cross-Platform) ---
    temps = {}
    if sys.platform == "win32":
        temps = _get_windows_thermals()
    elif hasattr(psutil, "sensors_temperatures"):
        try:
            raw_temps = psutil.sensors_temperatures()
            if raw_temps:
                # Common Linux sensor keys
                if 'coretemp' in raw_temps and raw_temps['coretemp']:
                    temps['cpu_temp_celsius'] = raw_temps['coretemp'][0].current
                elif 'k10temp' in raw_temps and raw_temps['k10temp']:
                    temps['cpu_temp_celsius'] = raw_temps['k10temp'][0].current
                elif 'package_id_0' in raw_temps and raw_temps['package_id_0']:
                    temps['cpu_temp_celsius'] = raw_temps['package_id_0'][0].current
        except Exception: pass

    # Normalize OS name for display
    os_name = f"{platform.system()} {platform.release()}"
    if platform.system() == "Windows":
        try:
            ver = sys.getwindowsversion()
            if ver.major == 10 and ver.build >= 22000:
                os_name = "Windows 11"
        except Exception: pass

    battery_info = {}
    if hasattr(psutil, "sensors_battery"):
        try:
            battery = psutil.sensors_battery()
            if battery:
                battery_info = {
                    "percent": round(battery.percent, 1),
                    "power_plugged": battery.power_plugged,
                    "secsleft": battery.secsleft if battery.secsleft != psutil.POWER_TIME_UNLIMITED else None
                }
        except Exception: pass

    net_info = {}
    try:
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        for nic, nic_addrs in addrs.items():
            ipv4 = None
            for a in nic_addrs:
                if a.family == socket.AF_INET:
                    ipv4 = a.address
                    break
            
            if ipv4: # Filter interfaces with no IPv4 (clutter reduction)
                net_info[nic] = {
                    "ip": ipv4,
                    "is_up": stats[nic].isup if nic in stats else False,
                    "speed_mbps": stats[nic].speed if nic in stats else 0
                }
    except Exception: pass

    disk_io = None
    try:
        io_counters = psutil.disk_io_counters(perdisk=False)
        if io_counters:
            disk_io = {
                "read_bytes": io_counters.read_bytes,
                "write_bytes": io_counters.write_bytes,
                "read_count": io_counters.read_count,
                "write_count": io_counters.write_count
            }
    except Exception: pass

    active_users = []
    try:
        if hasattr(psutil, "users"):
            for u in psutil.users():
                active_users.append({
                    "name": u.name,
                    "terminal": u.terminal or "local",
                    "host": u.host,
                    "started": int(u.started)
                })
    except Exception: pass

    load = []
    try:
        if hasattr(psutil, "getloadavg"):
            load = list(psutil.getloadavg())
    except Exception: pass

    fans = {}
    if hasattr(psutil, "sensors_fans"):
        try:
            raw_fans = psutil.sensors_fans()
            for name, entries in raw_fans.items():
                list_out = []
                for e in entries:
                    list_out.append({"label": e.label or name, "current": e.current})
                fans[name] = list_out
        except Exception: pass

    return {
        "os": os_name,
        "hostname": socket.gethostname(),
        "uptime_seconds": int(uptime),
        "boot_time": int(boot),
        "procs": len(psutil.pids()),
        "load_avg": load,
        "users": active_users,
        "battery": battery_info,
        "cpu": {
            "percent": psutil.cpu_percent(interval=None),
            "per_cpu_percent": psutil.cpu_percent(interval=None, percpu=True),
            "physical_cores": psutil.cpu_count(logical=False),
            "total_cores": psutil.cpu_count(logical=True),
            "current_freq_mhz": freq.current if freq else None,
            "max_freq_mhz": freq.max if freq else None,
            "min_freq_mhz": freq.min if freq else None,
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
        "disk_io": disk_io,
        "fans": fans,
        "network": {
            "speed": speed,
            "io_total": psutil.net_io_counters()._asdict(),
            "interfaces": net_info,
        },
        "network_speed": speed,
        "sensors": temps,
    }

async def get_system_info_data(network_monitor: NetworkMonitor) -> Dict:
    return await asyncio.to_thread(_get_sync_system_info, network_monitor)

def _get_sync_disks_info() -> Dict[str, List]:
    """Returns a list of mounted persistent volumes with capacity metrics."""
    disks = []
    try:
        for p in psutil.disk_partitions(all=False):
            if not p.fstype: continue
            # Ignore Linux loopbacks/snaps
            if sys.platform.startswith("linux") and p.device.startswith(("/dev/loop", "/dev/snap")): 
                continue
            try:
                u = psutil.disk_usage(p.mountpoint)
                disks.append({
                    "device": p.device,
                    "mount": p.mountpoint,
                    "total": f"{round(u.total / (1024**3), 1)} GB",
                    "used": f"{round(u.used / (1024**3), 1)} GB",
                    "free": f"{round(u.free / (1024**3), 1)} GB",
                    "percent": int(u.percent),
                })
            except Exception: continue
        return {"disks": disks}
    except Exception: return {"disks": []}

async def get_disks_info_data() -> Dict[str, List]:
    return await asyncio.to_thread(_get_sync_disks_info)

# ==============================================================================
# INPUT CONTROLLER INITIALIZATION
# ==============================================================================

if PYNPUT_AVAILABLE:
    mouse_controller = MouseController()
    keyboard_controller = KeyboardController()
    button_map = {"left": Button.left, "right": Button.right, "middle": Button.middle}
else:
    mouse_controller = None
    keyboard_controller = None
    button_map = {}

key_map = {
    "enter": Key.enter, "esc": Key.esc, "shift": Key.shift, "ctrl": Key.ctrl, "alt": Key.alt,
    "cmd": Key.cmd, "win": Key.cmd, "backspace": Key.backspace, "delete": Key.delete, "tab": Key.tab,
    "space": Key.space, "up": Key.up, "down": Key.down, "left": Key.left, "right": Key.right,
    "home": Key.home, "end": Key.end, "pageup": Key.page_up, "pagedown": Key.page_down,
    "insert": Key.insert, "caps_lock": Key.caps_lock, "num_lock": Key.num_lock,
    "print_screen": Key.print_screen, "scroll_lock": Key.scroll_lock, "pause": Key.pause,
    "f1": Key.f1, "f2": Key.f2, "f3": Key.f3, "f4": Key.f4, "f5": Key.f5, "f6": Key.f6,
    "f7": Key.f7, "f8": Key.f8, "f9": Key.f9, "f10": Key.f10, "f11": Key.f11, "f12": Key.f12,
}

def get_key(key_str: str):
    return key_map.get(key_str.lower(), key_str)
