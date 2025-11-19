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



KNOWN_LEGACY_PLAYERS = {
    # Desktop Media Players
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
    
    # Music Players
    "spotify.exe": "Spotify",
    "itunes.exe": "iTunes",
    "foobar2000.exe": "foobar2000",
    "aimp.exe": "AIMP",
    "musicbee.exe": "MusicBee",
    "winamp.exe": "Winamp",
    "clementine.exe": "Clementine",
    
    # Browsers (for web players)
    "chrome.exe": "Chrome",
    "firefox.exe": "Firefox",
    "msedge.exe": "Edge",
    "opera.exe": "Opera",
    "brave.exe": "Brave",
}

# Common patterns to remove from window titles
TITLE_CLEANUP_PATTERNS = [
    " - YouTube",
    " - Spotify",
    " - SoundCloud",
    " - Twitch",
    "[Paused]",
    "[Stopped]",
]

def _clean_media_title(title: str, app_name: str) -> tuple[Optional[str], Optional[str]]:
    """
    Clean and parse media title from window title.
    Returns: (song_title, artist) or (None, None) if invalid
    """
    if not title or title.strip() == app_name:
        return None, None
    
    clean_title = title
    
    # Remove app name from end (e.g., "Song - VLC media player")
    for suffix in [f" - {app_name}", f" — {app_name}", f"- {app_name}"]:
        if clean_title.endswith(suffix):
            clean_title = clean_title[:-len(suffix)]
    
    # Remove app name from anywhere
    clean_title = clean_title.replace(app_name, "").strip()
    
    # Remove common patterns
    for pattern in TITLE_CLEANUP_PATTERNS:
        clean_title = clean_title.replace(pattern, "")
    
    clean_title = clean_title.strip(" -—|")
    
    if not clean_title or len(clean_title) < 2:
        return None, None
    
    # Parse Artist - Title or Title - Artist
    artist = None
    song_title = clean_title
    
    # Try different separators
    for separator in [" - ", " — ", " – "]:
        if separator in clean_title:
            parts = clean_title.split(separator, 1)
            # Heuristic: shorter part is usually artist
            if len(parts[0]) < len(parts[1]):
                artist = parts[0].strip()
                song_title = parts[1].strip()
            else:
                song_title = parts[0].strip()
                artist = parts[1].strip()
            break
    
    return song_title, artist

def _get_legacy_media_info() -> Optional[Dict[str, Any]]:
    """
    Scrapes window titles of known media players to find what's playing.
    Supports a wide range of media players and browsers.
    """
    if not LEGACY_SUPPORT_AVAILABLE:
        return None

    found_media = None
    best_match_priority = -1  # Higher priority = better match

    def enum_window_callback(hwnd, _):
        nonlocal found_media, best_match_priority

        if not win32gui.IsWindowVisible(hwnd):
            return

        try:
            length = win32gui.GetWindowTextLength(hwnd)
            if length == 0:
                return
            
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            try:
                proc = psutil.Process(pid)
                proc_name = proc.name().lower()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return

            if proc_name not in KNOWN_LEGACY_PLAYERS:
                return
            
            app_name = KNOWN_LEGACY_PLAYERS[proc_name]
            title = win32gui.GetWindowText(hwnd)
            
            # Clean and parse title
            song_title, artist = _clean_media_title(title, app_name)
            
            if not song_title:
                return
            
            # Priority system: dedicated music/video players > browsers
            priority = 10 if proc_name not in ["chrome.exe", "firefox.exe", "msedge.exe", "opera.exe", "brave.exe"] else 5
            
            # Only update if this is a better match
            if priority > best_match_priority:
                best_match_priority = priority
                found_media = {
                    "status": MediaStatus.PLAYING,  # Assume playing if window is active
                    "control_level": "basic",
                    "title": song_title,
                    "artist": artist or "",
                    "album_title": None,
                    "duration_sec": 0,
                    "position_sec": 0,
                    "source_app": f"{app_name} (Legacy)"
                }
        except Exception as e:
            log.debug(f"Error processing window: {e}")

    try:
        win32gui.EnumWindows(enum_window_callback, None)
    except Exception as e:
        log.debug(f"Error enumerating windows: {e}")
    
    return found_media




def _control_volume_win32(action: str):
    if not PYCAW_AVAILABLE:
        import keyboard
        key_map = {"volume_up": "volume up", "volume_down": "volume down", "mute_toggle": "volume mute"}
        if key := key_map.get(action): keyboard.send(key)
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
        try:
            import keyboard
            key_map = {"volume_up": "volume up", "volume_down": "volume down", "mute_toggle": "volume mute"}
            if key := key_map.get(action): keyboard.send(key)
        except: pass
    finally:
        if PYCAW_AVAILABLE: CoUninitialize()

async def _control_media_win32(action: str, position_sec: int = 0):
    # Command mapping: handle client variations
    action_map = {
        "prev_track": "previous",
        "next_track": "next",
    }
    action = action_map.get(action, action)
    
    if action in ["volume_up", "volume_down", "mute_toggle"]:
        await asyncio.to_thread(_control_volume_win32, action)
        return

    # Try SMTC first
    try:
        from winsdk.windows.media import MediaPlaybackAutoRepeatMode
        from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as MediaManager

        manager = await MediaManager.request_async()
        session = manager.get_current_session()

        if session:
            if action == "play_pause": await session.try_toggle_play_pause_async()
            elif action == "next": await session.try_skip_next_async()
            elif action == "previous": await session.try_skip_previous_async()
            elif action == "stop": await session.try_stop_async()
            elif action == "seek": await session.try_change_playback_position_async(int(position_sec * 10_000_000))
            elif action == "seek_forward":
                timeline = session.get_timeline_properties()
                new_pos = min(timeline.position + timedelta(seconds=SEEK_AMOUNT_SECONDS), timeline.end_time)
                await session.try_change_playback_position_async(int(new_pos.total_seconds() * 10_000_000))
            elif action == "seek_backward":
                timeline = session.get_timeline_properties()
                new_pos = max(timeline.position - timedelta(seconds=SEEK_AMOUNT_SECONDS), timedelta(seconds=0))
                await session.try_change_playback_position_async(int(new_pos.total_seconds() * 10_000_000))
            elif action == "toggle_shuffle":
                playback_info = session.get_playback_info()
                await session.try_change_shuffle_active_async(not playback_info.is_shuffle_active)
            elif action == "toggle_repeat":
                playback_info = session.get_playback_info()
                current = playback_info.auto_repeat_mode
                next_mode = MediaPlaybackAutoRepeatMode.LIST if current == MediaPlaybackAutoRepeatMode.NONE else \
                            MediaPlaybackAutoRepeatMode.TRACK if current == MediaPlaybackAutoRepeatMode.LIST else \
                            MediaPlaybackAutoRepeatMode.NONE
                await session.try_change_auto_repeat_mode_async(next_mode)
            return
    except ImportError:
        pass # Fallback to keyboard
    except Exception as e:
        log.debug(f"SMTC Control failed: {e}")

    # Fallback to Keyboard
    log.info(f"Fallback to keyboard for action: {action}")
    import keyboard
    key_map = {
        "play_pause": "play/pause media", "next": "next track",
        "previous": "previous track", "stop": "stop media",
    }
    if key := key_map.get(action): keyboard.send(key)


@router.get("/", response_model=MediaInfoResponse)
async def get_media_info() -> MediaInfoResponse:
    server_time = time.time()
    if sys.platform != "win32":
        return MediaInfoResponse(status=MediaStatus.NO_SESSION, control_level="basic", server_timestamp=server_time)

    smtc_info = None
    smtc_valid = False

    # Try Modern Windows SDK (SMTC)
    try:
        from winsdk.windows.media import MediaPlaybackAutoRepeatMode
        from winsdk.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as MediaManager,
            GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
        )

        manager = await MediaManager.request_async()
        session = manager.get_current_session()

        if session:
            playback_info = session.get_playback_info()
            status_map = {
                PlaybackStatus.PLAYING: MediaStatus.PLAYING,
                PlaybackStatus.PAUSED: MediaStatus.PAUSED,
                PlaybackStatus.STOPPED: MediaStatus.STOPPED,
            }
            status = status_map.get(playback_info.playback_status, MediaStatus.INACTIVE)


            props = await session.try_get_media_properties_async()
            timeline = session.get_timeline_properties()
            
            repeat_map = {
                MediaPlaybackAutoRepeatMode.NONE: "none",
                MediaPlaybackAutoRepeatMode.TRACK: "one",
                MediaPlaybackAutoRepeatMode.LIST: "all",
            }
            
            title = props.title if props else ""
            artist = props.artist if props else ""
            
            # Determine if this SMTC info is "useful"
            # It's useful if it has a Title AND (it is Playing OR Paused)
            # If it's "Stopped" or "Unknown" title, we might want to check legacy
            has_title = bool(title and title.lower() not in ["unknown", ""])
            has_artist = bool(artist and artist.lower() not in ["unknown", ""])
            
            smtc_info = {
                "status": status,
                "control_level": "full",
                "title": title or "Unknown",
                "artist": artist or "",
                "album_title": props.album_artist if props else None,
                "duration_sec": int(timeline.end_time.total_seconds()) if timeline else 0,
                "position_sec": int(timeline.position.total_seconds()) if timeline else 0,
                "server_timestamp": server_time,
                "is_shuffle_active": playback_info.is_shuffle_active,
                "repeat_mode": repeat_map.get(playback_info.auto_repeat_mode),
                "source_app": "Windows Media Control"
            }
            
            # Consider SMTC valid if it's playing OR if it has a valid title
            if status == MediaStatus.PLAYING or (has_title and has_artist):
                smtc_valid = True

    except Exception as e:
        if "AttributeError" not in str(e):
             log.debug(f"Modern media info failed: {e}")
    
    # Try Legacy Window Scraping
    legacy_info = await asyncio.to_thread(_get_legacy_media_info)
    

    
    # If both exist, prefer the one that is PLAYING
    if smtc_valid and legacy_info:
        if smtc_info["status"] == MediaStatus.PLAYING:
            return MediaInfoResponse(**smtc_info)
        elif legacy_info["status"] == MediaStatus.PLAYING:
            legacy_info["server_timestamp"] = server_time
            return MediaInfoResponse(**legacy_info)
        else:
            # Both paused/stopped, prefer SMTC as it has more info (duration, etc)
            return MediaInfoResponse(**smtc_info)
            
    # If only SMTC exists and it's valid (or we have nothing else)
    if smtc_valid:
        return MediaInfoResponse(**smtc_info)
        
    # If only Legacy exists
    if legacy_info:
        legacy_info["server_timestamp"] = server_time
        return MediaInfoResponse(**legacy_info)
        
    # If we have an "Invalid" SMTC session (e.g. generic "Unknown" stopped session) 
    # and no legacy info, just return the SMTC info to show *something* or empty
    if smtc_info:
        return MediaInfoResponse(**smtc_info)

    return MediaInfoResponse(status=MediaStatus.NO_SESSION, control_level="basic", server_timestamp=server_time)


@router.post("/command", response_model=MediaInfoResponse)
async def media_command(payload: MediaActionModel) -> MediaInfoResponse:
    action = payload.action
    if sys.platform == "win32":
        await _control_media_win32(action)
    else:
        try:
            import keyboard
            key_map = {
                "play_pause": "play/pause media", "next": "next track",
                "previous": "previous track", "prev_track": "previous track", "next_track": "next track",
                "stop": "stop media",
                "volume_up": "volume up", "volume_down": "volume down", "mute_toggle": "volume mute",
            }
            if key := key_map.get(action): keyboard.send(key)
        except ImportError: pass

    await asyncio.sleep(0.3)
    return await get_media_info()


@router.post("/seek", response_model=MediaInfoResponse)
async def seek_media_position(payload: SeekModel) -> MediaInfoResponse:
    if sys.platform == "win32":
        await _control_media_win32("seek", position_sec=payload.position_sec)
    await asyncio.sleep(0.1)
    return await get_media_info()