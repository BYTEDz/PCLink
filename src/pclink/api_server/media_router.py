# src/pclink/api_server/media_router.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import logging
import sys
import time
from datetime import timedelta
from typing import Dict, Any, Optional, Literal
from enum import Enum

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

# Import services to access the cache and unified logic
from .services import get_media_info_data, _media_info_cache 

router = APIRouter()
log = logging.getLogger(__name__)

SEEK_AMOUNT_SECONDS = 10

try:
    import comtypes
    from comtypes import CLSCTX_ALL, CoInitialize, CoUninitialize
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    PYCAW_AVAILABLE = True
except ImportError:
    PYCAW_AVAILABLE = False

try:
    import win32gui
    import win32process
    import psutil
    LEGACY_SUPPORT_AVAILABLE = True
except ImportError:
    LEGACY_SUPPORT_AVAILABLE = False


class MediaStatus(str, Enum):
    NO_SESSION = "no_session"
    INACTIVE = "inactive"
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"

class MediaInfoResponse(BaseModel):
    status: MediaStatus = Field(..., description="The current playback status.")
    control_level: Literal["full", "basic"] = Field(..., description="The level of control available.")
    title: Optional[str] = None
    artist: Optional[str] = None
    album_title: Optional[str] = None
    duration_sec: int = 0
    position_sec: int = 0
    server_timestamp: float = Field(..., description="The UTC timestamp (epoch) when the media info was captured.")
    is_shuffle_active: Optional[bool] = None
    repeat_mode: Optional[str] = None
    source_app: Optional[str] = None

class MediaActionModel(BaseModel):
    action: str

class SeekModel(BaseModel):
    position_sec: int


def _control_volume_win32(action: str):
    if not PYCAW_AVAILABLE:
        # Fallback to keyboard keys for volume if pycaw is missing
        try:
            import keyboard
            key_map = {"volume_up": "volume up", "volume_down": "volume down", "mute_toggle": "volume mute"}
            if key := key_map.get(action): keyboard.send(key)
        except ImportError: pass
        return

    try:
        CoInitialize()
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = interface.QueryInterface(IAudioEndpointVolume)
        
        if action == "volume_up":
            current_vol = volume.GetMasterVolumeLevelScalar()
            volume.SetMasterVolumeLevelScalar(min(1.0, current_vol + 0.02), None)
        elif action == "volume_down":
            current_vol = volume.GetMasterVolumeLevelScalar()
            volume.SetMasterVolumeLevelScalar(max(0.0, current_vol - 0.02), None)
        elif action == "mute_toggle":
            volume.SetMute(not volume.GetMute(), None)
    except Exception as e:
        log.error(f"Error controlling volume via COM: {e}")
    finally:
        if PYCAW_AVAILABLE: CoUninitialize()

async def _control_media_linux(action: str, position_sec: int = 0):
    """Controls media on Linux using playerctl."""
    action_map = {
        "play": "play",
        "pause": "pause",
        "toggle_play": "play-pause",
        "next": "next",
        "previous": "previous",
        "stop": "stop",
    }
    
    try:
        from .services import run_subprocess
        if action == "seek":
            await run_subprocess(["playerctl", "position", str(position_sec)])
        elif action == "seek_forward":
            await run_subprocess(["playerctl", "position", f"{SEEK_AMOUNT_SECONDS}+"])
        elif action == "seek_backward":
            await run_subprocess(["playerctl", "position", f"{SEEK_AMOUNT_SECONDS}-"])
        elif cmd := action_map.get(action):
            await run_subprocess(["playerctl", cmd])
    except Exception as e:
        log.error(f"Linux media control failed: {e}")

async def _control_media_darwin(action: str, position_sec: int = 0):
    """Controls media on macOS using AppleScript."""
    # This is a simplified version, ideally we target the active app found in services
    script_template = """
    tell application "System Events"
        set runningApps to name of processes
        if runningApps contains "{app}" then
            tell application "{app}"
                {cmd}
            end tell
            return true
        end if
    end tell
    return false
    """
    
    apps = ["Spotify", "Music", "TV", "QuickTime Player"]
    cmd_map = {
        "play": "play",
        "pause": "pause",
        "toggle_play": "playpause",
        "next": "next track",
        "previous": "previous track",
        "stop": "stop",
    }
    
    cmd = cmd_map.get(action)
    if not cmd: return

    from .services import run_subprocess
    for app in apps:
        script = script_template.format(app=app, cmd=cmd)
        result = await run_subprocess(["osascript", "-e", script])
        if result == "true": break

async def _control_media_win32(action: str, position_sec: int = 0):
    # 1. Normalize Action Strings
    action_map = {
        "toggle_play": "play_pause",
        "prev_track": "previous",
        "next_track": "next",
    }
    normalized_action = action_map.get(action, action)
    log.info(f"Win32 Media Control: {action} (mapped: {normalized_action})")
    
    # 2. Handle Volume (Always handled separately via Core Audio)
    if normalized_action in ["volume_up", "volume_down", "mute_toggle"]:
        await asyncio.to_thread(_control_volume_win32, normalized_action)
        return

    # 3. Determine the best control method based on current source
    last_source = _media_info_cache.get("data", {}).get("source_app", "")
    
    use_smtc = True
    if last_source and "Legacy" in str(last_source):
        use_smtc = False
    
    # 4. Try SMTC (Windows Media Controls) if appropriate
    if use_smtc:
        try:
            from winsdk.windows.media import MediaPlaybackAutoRepeatMode
            from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as MediaManager

            manager = await MediaManager.request_async()
            session = manager.get_current_session()

            if session:
                try:
                    if normalized_action == "play_pause": 
                        await session.try_toggle_play_pause_async()
                    elif normalized_action == "play":
                        await session.try_play_async()
                    elif normalized_action == "pause":
                        await session.try_pause_async()
                    elif normalized_action == "next": 
                        await session.try_skip_next_async()
                    elif normalized_action == "previous": 
                        await session.try_skip_previous_async()
                    elif normalized_action == "stop": 
                        await session.try_stop_async()
                    elif normalized_action == "seek": 
                        await session.try_change_playback_position_async(int(position_sec * 10_000_000))
                    elif normalized_action == "seek_forward":
                        timeline = session.get_timeline_properties()
                        new_pos = timeline.position.total_seconds() + SEEK_AMOUNT_SECONDS
                        await session.try_change_playback_position_async(int(new_pos * 10_000_000))
                    elif normalized_action == "seek_backward":
                        timeline = session.get_timeline_properties()
                        new_pos = max(0, timeline.position.total_seconds() - SEEK_AMOUNT_SECONDS)
                        await session.try_change_playback_position_async(int(new_pos * 10_000_000))
                    elif normalized_action == "toggle_shuffle":
                        playback_info = session.get_playback_info()
                        await session.try_change_shuffle_active_async(not playback_info.is_shuffle_active)
                    elif normalized_action == "toggle_repeat":
                        playback_info = session.get_playback_info()
                        current = playback_info.auto_repeat_mode
                        next_mode = MediaPlaybackAutoRepeatMode.LIST if current == MediaPlaybackAutoRepeatMode.NONE else \
                                    MediaPlaybackAutoRepeatMode.TRACK if current == MediaPlaybackAutoRepeatMode.LIST else \
                                    MediaPlaybackAutoRepeatMode.NONE
                        await session.try_change_auto_repeat_mode_async(next_mode)
                    log.info(f"SMTC command '{normalized_action}' succeeded")
                    return # Success!
                except Exception as e:
                    log.error(f"SMTC session command failed: {e}")
                    # fall through to keyboard
            else:
                # No SMTC session, but use_smtc was true. 
                # This is normal if only legacy players are running.
                pass
        except ImportError:
            pass 
        except Exception as e:
            log.debug(f"SMTC registration or manager request failed: {e}")
            # fall through to keyboard

    # 5. targeted Control for Legacy Apps (WM_APPCOMMAND)
    # If we have a specific window handle, we can send commands directly to it.
    # This prevents other apps (like Firefox/Chrome) from "stealing" the media key.
    hwnd = _media_info_cache.get("data", {}).get("_hwnd")
    if hwnd:
        try:
            # WM_APPCOMMAND = 0x0319
            # APPCOMMAND constants
            APPCOMMAND_MAP = {
                "play_pause": 14, "play": 14, "pause": 14,
                "next": 11, "previous": 12, "stop": 13,
                "volume_up": 10, "volume_down": 9, "mute_toggle": 8
            }
            if cmd := APPCOMMAND_MAP.get(normalized_action):
                # We use SendMessage to ensure the app processes it before we continue
                import win32gui
                # The lParameter is (APPCOMMAND << 16)
                win32gui.SendMessage(hwnd, 0x0319, hwnd, cmd << 16)
                log.info(f"Sent targeted WM_APPCOMMAND {cmd} to HWND {hwnd} for action '{action}'")
                
                # Special addition for VLC: if it's Play/Pause, also send a targeted Space key 
                # as some versions of VLC ignore APPCOMMAND if not in focus.
                if action in ["play", "pause", "play_pause"] and "vlc" in last_source.lower():
                    # WM_KEYDOWN = 0x0100, VK_SPACE = 0x20
                    win32gui.PostMessage(hwnd, 0x0100, 0x20, 0)
                    log.debug(f"Sent diagnostic Space key to VLC HWND {hwnd}")
                return
        except Exception as e:
            log.debug(f"Targeted WM_APPCOMMAND failed: {e}")

    # 6. Fallback to Global Media Keys (Keyboard Simulation)
    try:
        import keyboard
        # Action Map for Keyboard (Mostly toggles/jumps)
        key_map = {
            "play_pause": "play/pause media", 
            "play": "play/pause media",
            "pause": "play/pause media",
            "next": "next track",
            "previous": "previous track", 
            "stop": "stop media",
        }
        
        if key := key_map.get(normalized_action):
            # Intelligent Fallback: Only send toggle if the current state requires it.
            current_status = _media_info_cache.get("data", {}).get("status", "STOPPED").upper()
            
            should_send = True
            if action == "play" and current_status == "PLAYING":
                should_send = False
            elif action == "pause" and current_status in ["PAUSED", "STOPPED"]:
                should_send = False
            
            if should_send:
                keyboard.send(key)
                log.info(f"Using global media key '{key}' for action '{action}' (Current state: {current_status})")
            else:
                log.info(f"Skipping global media key '{key}' for action '{action}': state already '{current_status}'")
    except ImportError: 
        log.error("Keyboard module not found, cannot control legacy media")


@router.get("/", response_model=MediaInfoResponse)
async def get_media_info() -> MediaInfoResponse:
    # Use unified service logic (includes legacy + caching + sticky logic)
    data = await get_media_info_data()
    
    # Map raw dict to Pydantic model
    status_str = data.get("status", "STOPPED").upper()
    try:
        status_enum = MediaStatus(status_str.lower())
    except ValueError:
        status_enum = MediaStatus.STOPPED

    return MediaInfoResponse(
        status=status_enum,
        control_level=data.get("control_level", "basic"),
        title=data.get("title"),
        artist=data.get("artist"),
        album_title=data.get("album_title"),
        duration_sec=data.get("duration_sec", 0),
        position_sec=data.get("position_sec", 0),
        server_timestamp=time.time(),
        is_shuffle_active=data.get("is_shuffle_active"),
        repeat_mode=data.get("repeat_mode"),
        source_app=data.get("source_app")
    )


@router.post("/command", response_model=MediaInfoResponse)
async def media_command(payload: MediaActionModel) -> MediaInfoResponse:
    action = payload.action
    
    # 1. Execute Command
    if sys.platform == "win32":
        await _control_media_win32(action)
    elif sys.platform.startswith("linux"):
        await _control_media_linux(action)
    elif sys.platform == "darwin":
        await _control_media_darwin(action)
    else:
        # Generic Keyboard fallback for unsupported/unknown platforms
        try:
            import keyboard
            key_map = {
                "play_pause": "play/pause media", "toggle_play": "play/pause media",
                "play": "play/pause media", "pause": "play/pause media",
                "next": "next track", "next_track": "next track",
                "previous": "previous track", "prev_track": "previous track",
                "stop": "stop media",
                "volume_up": "volume up", "volume_down": "volume down", "mute_toggle": "volume mute",
            }
            if key := key_map.get(action): keyboard.send(key)
        except ImportError: pass

    # 2. Heuristic Update for Legacy Players (Sticky Logic Injection)
    if _media_info_cache.get("last_valid_data"):
        current = _media_info_cache["last_valid_data"].copy()
        
        # Only apply heuristics for toggling play/pause
        if action in ["play_pause", "toggle_play", "play", "pause"]:
            current_status = current.get("status", "STOPPED").upper()
            
            # Intelligent flip: Only flip if the action matches the state or is a toggle
            should_flip = False
            if action in ["play_pause", "toggle_play"]:
                should_flip = True
            elif action == "play" and current_status != "PLAYING":
                should_flip = True
            elif action == "pause" and current_status == "PLAYING":
                should_flip = True
                
            if should_flip:
                new_status = "PAUSED" if current_status == "PLAYING" else "PLAYING"
                current["status"] = new_status
                
                # Update the global cache explicitly
                _media_info_cache["last_valid_data"] = current
                _media_info_cache["last_valid_time"] = time.time()
                _media_info_cache["data"] = current
                _media_info_cache["timestamp"] = time.time()
                
                # Set sticky lock for services.py to respect for 3 seconds
                _media_info_cache["command_lock_target"] = new_status
                _media_info_cache["command_lock_until"] = time.time() + 3.0
                log.info(f"Heuristic flip: {current_status} -> {new_status} (Sticky lock for 3s)")

    # 3. Wait briefly for OS to register
    # Legacy players (VLC) take longer to update window titles
    last_source = _media_info_cache.get("data", {}).get("source_app", "")
    is_legacy = last_source and "Legacy" in str(last_source)
    delay = 0.5 if is_legacy else 0.2
    await asyncio.sleep(delay)
    
    # 4. Fetch (will use our injected cache if OS returns empty)
    return await get_media_info()


@router.post("/seek", response_model=MediaInfoResponse)
async def seek_media_position(payload: SeekModel) -> MediaInfoResponse:
    if sys.platform == "win32":
        await _control_media_win32("seek", position_sec=payload.position_sec)
    elif sys.platform.startswith("linux"):
        await _control_media_linux("seek", position_sec=payload.position_sec)
    elif sys.platform == "darwin":
        await _control_media_darwin("seek", position_sec=payload.position_sec)
    await asyncio.sleep(0.1)
    return await get_media_info()