"""
PCLink - Remote PC Control Server - Media API Module
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

class MediaActionModel(BaseModel):
    action: str

class SeekModel(BaseModel):
    position_sec: int

async def _control_media_win32(action: str, position_sec: int = 0):
    try:
        from winsdk.windows.media import MediaPlaybackAutoRepeatMode
        from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as MediaManager

        manager = await MediaManager.request_async()
        session = manager.get_current_session()

        if not session:
            log.warning("No active media session found, falling back to keyboard simulation.")
            import keyboard
            key_map = {
                "play_pause": "play/pause media", "next": "next track",
                "previous": "previous track", "stop": "stop media",
            }
            if key := key_map.get(action): keyboard.send(key)
            else: log.warning(f"Unsupported fallback action: {action}")
            return

        if action == "play_pause": await session.try_toggle_play_pause_async()
        elif action == "next": await session.try_skip_next_async()
        elif action == "previous": await session.try_skip_previous_async()
        elif action == "stop": await session.try_stop_async()
        elif action == "seek": await session.try_change_playback_position_async(position_sec * 10_000_000)
        elif action == "seek_forward":
            timeline = session.get_timeline_properties()
            new_pos = min(timeline.position + timedelta(seconds=SEEK_AMOUNT_SECONDS), timeline.end_time)
            await session.try_change_playback_position_async(int(new_pos.total_seconds() * 1_000_000_0))
        elif action == "seek_backward":
            timeline = session.get_timeline_properties()
            new_pos = max(timeline.position - timedelta(seconds=SEEK_AMOUNT_SECONDS), timedelta(seconds=0))
            await session.try_change_playback_position_async(int(new_pos.total_seconds() * 1_000_000_0))
        elif action == "toggle_shuffle":
            playback_info = session.get_playback_info()
            await session.try_change_shuffle_active_async(not playback_info.is_shuffle_active)
        elif action == "toggle_repeat":
            playback_info = session.get_playback_info()
            current_mode = playback_info.auto_repeat_mode
            if current_mode == MediaPlaybackAutoRepeatMode.NONE:
                next_mode = MediaPlaybackAutoRepeatMode.LIST
            elif current_mode == MediaPlaybackAutoRepeatMode.LIST:
                next_mode = MediaPlaybackAutoRepeatMode.TRACK
            else:
                next_mode = MediaPlaybackAutoRepeatMode.NONE
            await session.try_change_auto_repeat_mode_async(next_mode)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported media action: {action}")

    except ImportError:
        log.error("winsdk not installed. Media control on Windows requires it.")
        raise HTTPException(status_code=501, detail="Media control requires winsdk.")
    except Exception as e:
        log.error(f"Error controlling media on Windows: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to control media: {e}")

@router.get("/", response_model=MediaInfoResponse)
async def get_media_info() -> MediaInfoResponse:
    server_time = time.time()

    if sys.platform != "win32":
        return MediaInfoResponse(status=MediaStatus.NO_SESSION, control_level="basic", server_timestamp=server_time)

    try:
        from winsdk.windows.media import MediaPlaybackAutoRepeatMode
        from winsdk.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as MediaManager,
            GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
        )

        manager = await MediaManager.request_async()
        session = manager.get_current_session()

        if not session:
            return MediaInfoResponse(status=MediaStatus.NO_SESSION, control_level="basic", server_timestamp=server_time)

        playback_info = session.get_playback_info()
        status_map = {
            PlaybackStatus.PLAYING: MediaStatus.PLAYING,
            PlaybackStatus.PAUSED: MediaStatus.PAUSED,
            PlaybackStatus.STOPPED: MediaStatus.STOPPED,
        }
        status = status_map.get(playback_info.playback_status, MediaStatus.INACTIVE)

        if status == MediaStatus.INACTIVE:
            return MediaInfoResponse(status=MediaStatus.NO_SESSION, control_level="basic", server_timestamp=server_time)

        props = await session.get_media_properties_async()
        timeline = session.get_timeline_properties()
        
        repeat_map = {
            MediaPlaybackAutoRepeatMode.NONE: "none",
            MediaPlaybackAutoRepeatMode.TRACK: "one",
            MediaPlaybackAutoRepeatMode.LIST: "all",
        }
        repeat_mode = repeat_map.get(playback_info.auto_repeat_mode)

        return MediaInfoResponse(
            status=status,
            control_level="full",
            title=props.title,
            artist=props.artist,
            album_title=props.album_artist,
            duration_sec=int(timeline.end_time.total_seconds()),
            position_sec=int(timeline.position.total_seconds()),
            server_timestamp=server_time,
            is_shuffle_active=playback_info.is_shuffle_active,
            repeat_mode=repeat_mode,
        )
    except ImportError:
        return MediaInfoResponse(status=MediaStatus.NO_SESSION, control_level="basic", server_timestamp=server_time)
    except Exception as e:
        log.error(f"Failed to get media info: {e}", exc_info=True)
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
                "previous": "previous track", "stop": "stop media",
                "volume_up": "volume up", "volume_down": "volume down", "mute_toggle": "volume mute",
            }
            if key := key_map.get(action): keyboard.send(key)
            else: log.warning(f"Unsupported media action for this platform: {action}")
        except ImportError:
            log.error("Keyboard library not installed. Cannot control media.")
            raise HTTPException(status_code=501, detail="Keyboard library not installed.")

    await asyncio.sleep(0.3)
    return await get_media_info()


@router.post("/seek", response_model=MediaInfoResponse)
async def seek_media_position(payload: SeekModel) -> MediaInfoResponse:
    if sys.platform == "win32":
        await _control_media_win32("seek", position_sec=payload.position_sec)
    else:
        raise HTTPException(status_code=501, detail=f"Seeking not supported on {sys.platform}")

    await asyncio.sleep(0.1)
    return await get_media_info()