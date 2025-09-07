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
from typing import Dict, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# Import platform-specific media info retrieval functions.
from .services import get_media_info_data

router = APIRouter()
log = logging.getLogger(__name__)

# Define default seek amount in seconds.
SEEK_AMOUNT_SECONDS = 10


class MediaActionModel(BaseModel):
    """Model for media control actions."""

    action: str


class SeekModel(BaseModel):
    """Model for seeking to a specific position in media playback."""

    position_sec: int


async def _control_media_win32(action: str, position_sec: int = 0):
    """
    Controls media playback on Windows using the Windows SDK.

    If a media session is not found, it falls back to simulating keyboard shortcuts.

    Args:
        action: The media control action to perform (e.g., 'play_pause', 'seek').
        position_sec: The desired position in seconds for seek actions.
    """
    try:
        # Import Windows SDK components only when needed on Windows.
        from winsdk.windows.media import MediaPlaybackAutoRepeatMode
        from winsdk.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as MediaManager,
        )

        manager = await MediaManager.request_async()
        session = manager.get_current_session()

        if not session:
            # Fallback to keyboard simulation if no active media session is detected.
            log.warning("No active media session found, falling back to keyboard simulation.")
            import keyboard

            key_map = {
                "play_pause": "play/pause media",
                "next_track": "next track",
                "prev_track": "previous track",
                "stop": "stop media",
            }
            if key := key_map.get(action):
                keyboard.send(key)
            else:
                log.warning(f"Unsupported fallback action: {action}")
            return

        # Control media directly through the active session.
        if action == "play_pause":
            await session.try_toggle_play_pause_async()
        elif action == "next_track":
            await session.try_skip_next_async()
        elif action == "prev_track":
            await session.try_skip_previous_async()
        elif action == "stop":
            await session.try_stop_async()
        elif action == "seek":
            # Change playback position to a specific time.
            # Convert seconds to 100-nanosecond intervals.
            await session.try_change_playback_position_async(position_sec * 10_000_000)
        elif action == "seek_forward":
            # Seek forward by SEEK_AMOUNT_SECONDS.
            timeline = session.get_timeline_properties()
            new_pos = timeline.position + timedelta(seconds=SEEK_AMOUNT_SECONDS)
            # Ensure new position does not exceed duration.
            if new_pos > timeline.end_time:
                new_pos = timeline.end_time
            await session.try_change_playback_position_async(int(new_pos.total_seconds() * 1_000_000_0))
        elif action == "seek_backward":
            # Seek backward by SEEK_AMOUNT_SECONDS.
            timeline = session.get_timeline_properties()
            new_pos = timeline.position - timedelta(seconds=SEEK_AMOUNT_SECONDS)
            # Ensure new position does not go below zero.
            if new_pos < timedelta(seconds=0):
                new_pos = timedelta(seconds=0)
            await session.try_change_playback_position_async(int(new_pos.total_seconds() * 1_000_000_0))
        elif action == "toggle_shuffle":
            playback_info = session.get_playback_info()
            await session.try_change_shuffle_active_async(not playback_info.is_shuffle_active)
        elif action == "toggle_repeat":
            playback_info = session.get_playback_info()
            current_mode = playback_info.auto_repeat_mode
            # Cycle through repeat modes: NONE -> ALL -> ONE -> NONE.
            if current_mode == MediaPlaybackAutoRepeatMode.NONE:
                next_mode = MediaPlaybackAutoRepeatMode.LIST
            elif current_mode == MediaPlaybackAutoRepeatMode.LIST:
                next_mode = MediaPlaybackAutoRepeatMode.TRACK
            else:  # MediaPlaybackAutoRepeatMode.TRACK
                next_mode = MediaPlaybackAutoRepeatMode.NONE
            await session.try_change_auto_repeat_mode_async(next_mode)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported media action: {action}")

    except ImportError:
        # Handle cases where winsdk is not installed.
        log.error("winsdk not installed. Media control on Windows requires it.")
        raise HTTPException(
            status_code=501, detail="Media control requires winsdk to be installed."
        )
    except Exception as e:
        # Catch any other exceptions during media control.
        log.error(f"Error controlling media on Windows: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to control media: {e}")


@router.get("/")
async def get_media_info() -> Dict[str, Any]:
    """
    Retrieves current media playback information.

    Returns:
        A dictionary containing details about the currently playing media.
    """
    return await get_media_info_data()


@router.post("/command")
async def media_command(payload: MediaActionModel) -> Dict[str, Any]:
    """
    Executes a media control command.

    Supports volume controls universally via keyboard simulation and other
    commands via platform-specific methods or keyboard simulation fallback.

    Args:
        payload: A MediaActionModel containing the action to perform.

    Returns:
        The updated media information after executing the command.
    """
    action = payload.action

    if action in ["volume_up", "volume_down", "mute_toggle"]:
        # Volume controls are universally handled via keyboard simulation.
        try:
            import keyboard
            key_map = {"volume_up": "volume up", "volume_down": "volume down", "mute_toggle": "volume mute"}
            keyboard.send(key_map[action])
        except ImportError:
            log.error("Keyboard library not installed. Cannot control volume.")
            raise HTTPException(status_code=501, detail="Keyboard library not installed.")
    elif sys.platform == "win32":
        # Use Windows SDK for other media controls if on Windows.
        await _control_media_win32(action)
    else:
        # Fallback for other platforms using keyboard simulation.
        try:
            import keyboard
            key_map = {
                "play_pause": "play/pause media",
                "next_track": "next track",
                "prev_track": "previous track",
                "stop": "stop media",
            }
            if key := key_map.get(action):
                keyboard.send(key)
            else:
                log.warning(f"Unsupported media action for non-Windows platform: {action}")
        except ImportError:
            log.error("Keyboard library not installed. Cannot control media.")
            raise HTTPException(status_code=501, detail="Keyboard library not installed.")

    # Short delay to allow the media player to process the command.
    await asyncio.sleep(0.3)
    return await get_media_info_data()


@router.post("/seek")
async def seek_media_position(payload: SeekModel) -> Dict[str, Any]:
    """
    Sets the media playback position to a specific time.

    Args:
        payload: A SeekModel containing the target position in seconds.

    Returns:
        The updated media information after seeking.
    """
    if sys.platform == "win32":
        await _control_media_win32("seek", position_sec=payload.position_sec)
    else:
        # Add platform-specific logic for seeking on other OS if needed.
        # For example, using playerctl on Linux.
        log.warning(f"Seeking not explicitly implemented for platform: {sys.platform}")
        # As a basic fallback, could try sending keyboard shortcuts if playerctl isn't available
        # or if specific apps don't respond to SDKs.
        try:
            import keyboard
            # This is a very basic simulation and might not work for all players/platforms.
            # A more robust solution would involve platform-specific tools like playerctl.
            if payload.position_sec > 0:
                 log.info("Attempting seek via keyboard simulation (may not be precise).")
                 # Simulating Ctrl+Shift+Seek might be complex and player-dependent.
                 # Direct time setting is often not exposed via simple keys.
                 # Consider adding playerctl integration for Linux if needed.
            else:
                 log.warning("Seeking to 0 seconds is not directly supported via simple keyboard simulation.")

        except ImportError:
             log.error("Keyboard library not installed. Cannot simulate seek.")
             raise HTTPException(status_code=501, detail="Keyboard library not installed.")


    # Short delay to allow the media player to process the seek command.
    await asyncio.sleep(0.1)
    return await get_media_info_data()