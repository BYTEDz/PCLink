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

async def _control_media_win32(action: str, position_sec: int = 0):
    # 1. Normalize Action Strings
    action_map = {
        "toggle_play": "play_pause",
        "play": "play_pause",
        "pause": "play_pause",
        "prev_track": "previous",
        "next_track": "next",
    }
    normalized_action = action_map.get(action, action)
    
    # 2. Handle Volume (Always handled separately via Core Audio)
    if normalized_action in ["volume_up", "volume_down", "mute_toggle"]:
        await asyncio.to_thread(_control_volume_win32, normalized_action)
        return

    # 3. Determine the best control method based on current source
    # Check what 'get_media_info' saw last time.
    last_source = _media_info_cache.get("data", {}).get("source_app", "")
    
    use_smtc = True
    
    # If the last known media came from Legacy (VLC, Winamp, Browser Titles), 
    # SMTC is likely not active or reliable. Skip it to avoid lag/logs.
    if "Legacy" in str(last_source):
        use_smtc = False
    
    # 4. Try SMTC (Windows Media Controls) if appropriate
    if use_smtc:
        try:
            from winsdk.windows.media import MediaPlaybackAutoRepeatMode
            from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as MediaManager

            manager = await MediaManager.request_async()
            session = manager.get_current_session()

            if session:
                if normalized_action == "play_pause": 
                    await session.try_toggle_play_pause_async()
                elif normalized_action == "next": 
                    await session.try_skip_next_async()
                elif normalized_action == "previous": 
                    await session.try_skip_previous_async()
                elif normalized_action == "stop": 
                    await session.try_stop_async()
                elif normalized_action == "seek": 
                    await session.try_change_playback_position_async(int(position_sec * 10_000_000))
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
                return # Success!
        except ImportError:
            pass 
        except Exception:
            # Silently fail SMTC and fall through to keyboard
            pass

    # 5. Fallback to Global Media Keys (Keyboard Simulation)
    # This is the "Right API" for legacy apps like VLC that listen for global hotkeys.
    try:
        import keyboard
        key_map = {
            "play_pause": "play/pause media", 
            "next": "next track",
            "previous": "previous track", 
            "stop": "stop media",
        }
        if key := key_map.get(normalized_action):
            keyboard.send(key)
            if not use_smtc:
                log.debug(f"Sent legacy media key '{key}' for action '{normalized_action}'")
            else:
                log.info(f"SMTC failed, fallback to media key '{key}'")
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
    
    # 1. Execute Command (Win32 handled specially, others use keyboard)
    if sys.platform == "win32":
        await _control_media_win32(action)
    else:
        try:
            import keyboard
            key_map = {
                "play_pause": "play/pause media", "toggle_play": "play/pause media",
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
            # Flip status
            current_status = current.get("status", "STOPPED")
            new_status = "PAUSED" if current_status == "PLAYING" else "PLAYING"
            current["status"] = new_status
            
            # Update the global cache explicitly
            _media_info_cache["last_valid_data"] = current
            _media_info_cache["last_valid_time"] = time.time()
            # Also update immediate data to reflect change instantly in response
            _media_info_cache["data"] = current
            _media_info_cache["timestamp"] = time.time()

    # 3. Wait briefly for OS to register (VLC takes ~200ms to update window title)
    await asyncio.sleep(0.3)
    
    # 4. Fetch (will use our injected cache if OS returns empty)
    return await get_media_info()


@router.post("/seek", response_model=MediaInfoResponse)
async def seek_media_position(payload: SeekModel) -> MediaInfoResponse:
    if sys.platform == "win32":
        await _control_media_win32("seek", position_sec=payload.position_sec)
    await asyncio.sleep(0.1)
    return await get_media_info()