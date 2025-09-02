# filename: src/pclink/api_server/media_router.py
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
from datetime import timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .services import get_media_info_data

router = APIRouter()
log = logging.getLogger(__name__)

SEEK_AMOUNT_SECONDS = 10

class MediaActionModel(BaseModel):
    action: str

class SeekModel(BaseModel):
    position_sec: int

async def _control_media_win32(action: str, position_sec: int = 0):
    from winsdk.windows.media import MediaPlaybackAutoRepeatMode
    from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as MediaManager
    
    manager = await MediaManager.request_async()
    session = manager.get_current_session()
    
    if not session:
        # Fallback to keyboard simulation if no session is found
        import keyboard
        key_map = {
            "play_pause": "play/pause media", "next_track": "next track",
            "prev_track": "previous track", "stop": "stop media",
        }
        if key := key_map.get(action):
            keyboard.send(key)
        return

    # If a session exists, use direct control
    if action == "play_pause": await session.try_toggle_play_pause_async()
    elif action == "next_track": await session.try_skip_next_async()
    elif action == "prev_track": await session.try_skip_previous_async()
    elif action == "stop": await session.try_stop_async()
    elif action == "seek":
        await session.try_change_playback_position_async(position_sec * 10_000_000)
    elif action == "seek_forward":
        timeline = session.get_timeline_properties()
        new_pos = timeline.position + timedelta(seconds=SEEK_AMOUNT_SECONDS)
        if new_pos > timeline.end_time: new_pos = timeline.end_time
        await session.try_change_playback_position_async(int(new_pos.total_seconds() * 1_000_000_0))
    elif action == "seek_backward":
        timeline = session.get_timeline_properties()
        new_pos = timeline.position - timedelta(seconds=SEEK_AMOUNT_SECONDS)
        if new_pos < timedelta(seconds=0): new_pos = timedelta(seconds=0)
        await session.try_change_playback_position_async(int(new_pos.total_seconds() * 1_000_000_0))
    elif action == "toggle_shuffle":
        playback_info = session.get_playback_info()
        await session.try_change_shuffle_active_async(not playback_info.is_shuffle_active)
    elif action == "toggle_repeat":
        playback_info = session.get_playback_info()
        current_mode = playback_info.auto_repeat_mode
        next_mode = MediaPlaybackAutoRepeatMode.LIST if current_mode == MediaPlaybackAutoRepeatMode.NONE else \
                    MediaPlaybackAutoRepeatMode.TRACK if current_mode == MediaPlaybackAutoRepeatMode.LIST else \
                    MediaPlaybackAutoRepeatMode.NONE
        await session.try_change_auto_repeat_mode_async(next_mode)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported media action: {action}")


@router.get("/")
async def get_media_info():
    return await get_media_info_data()

@router.post("/command")
async def media_command(payload: MediaActionModel):
    action = payload.action
    
    if action in ["volume_up", "volume_down", "mute_toggle"]:
        import keyboard
        key_map = {"volume_up": "volume up", "volume_down": "volume down", "mute_toggle": "volume mute"}
        keyboard.send(key_map[action])
    elif sys.platform == "win32":
        await _control_media_win32(action)
    else:
        # Fallback for other platforms
        import keyboard
        key_map = {
            "play_pause": "play/pause media", "next_track": "next track",
            "prev_track": "previous track", "stop": "stop media",
        }
        if key := key_map.get(action):
            keyboard.send(key)

    await asyncio.sleep(0.3)
    return await get_media_info_data()

@router.post("/seek")
async def seek_media_position(payload: SeekModel):
    """Sets the media playback position to a specific time."""
    if sys.platform == "win32":
        await _control_media_win32("seek", position_sec=payload.position_sec)
    # Add other platform logic here if needed (e.g., playerctl)
    
    await asyncio.sleep(0.1)
    return await get_media_info_data()