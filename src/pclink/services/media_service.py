# src/pclink/services/media_service.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import logging
import sys
import time
from typing import Any, Dict, Optional

import psutil

log = logging.getLogger(__name__)

# Default state
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
    "source_app": None,
}

# Win32 Specifics
try:
    import win32gui
    import win32process

    LEGACY_SUPPORT_AVAILABLE = True
except ImportError:
    LEGACY_SUPPORT_AVAILABLE = False

KNOWN_LEGACY_PLAYERS = {
    "vlc.exe": "VLC",
    "mpc-hc.exe": "MPC-HC",
    "spotify.exe": "Spotify",
    "chrome.exe": "Chrome",
    "firefox.exe": "Firefox",
    "msedge.exe": "Edge",
}

TITLE_CLEANUP_PATTERNS = [" - YouTube", " - Spotify", " - VLC media player"]
SEEK_AMOUNT_SECONDS = 10

_MEDIA_CACHE_TTL = 1.0
_LEGACY_STATE_RETENTION = 5.0


class MediaService:
    """Logic for media metadata and playback status."""

    def __init__(self):
        self._cache = {
            "data": DEFAULT_MEDIA_INFO,
            "timestamp": 0,
            "last_valid_data": None,
            "last_valid_time": 0,
            "command_lock_target": None,
            "command_lock_until": 0,
        }
        self._has_playerctl = None
        self._keyboard = None

    @property
    def keyboard(self):
        """Lazy load pynput controller to avoid X11 focus grab on startup."""
        if self._keyboard is None:
            try:
                from pynput.keyboard import Controller

                self._keyboard = Controller()
            except ImportError:
                log.warning("pynput not available - universal media control disabled")
        return self._keyboard

    async def _tap(self, key):
        """Simulates a key tap with a small delay for OS reliability."""
        kb = self.keyboard
        if not kb:
            return False
        try:
            kb.press(key)
            await asyncio.sleep(0.05)
            kb.release(key)
            return True
        except Exception as e:
            log.error(f"Failed to tap media key: {e}")
            return False

    async def media_command(self, action: str):
        """Executes a media control command universally using OS hardware keys via pynput."""
        from pynput.keyboard import Key

        # Normalize incoming actions mapping
        action_map = {
            "toggle_play": "play_pause",
            "play": "play_pause",  # Hardware media keys use a single toggle button
            "pause": "play_pause",
            "next_track": "next",
            "prev_track": "previous",
            "prev": "previous",
            "vol_up": "volume_up",
            "vol_down": "volume_down",
            "mute": "mute_toggle",
        }

        norm_action = action_map.get(action, action)

        # Map directly to pynput OS-level keyboard keys
        key_map = {
            "play_pause": Key.media_play_pause,
            "next": Key.media_next,
            "previous": Key.media_previous,
            "volume_up": Key.media_volume_up,
            "volume_down": Key.media_volume_down,
            "mute_toggle": Key.media_volume_mute,
            "seek_fwd": Key.right,  # Note: Arrow keys only work if media player is the actively focused window
            "seek_bwd": Key.left,
        }

        # Use universal keyboard emulation for standard play/volume functions
        if norm_action in key_map:
            await self._tap(key_map[norm_action])
        else:
            # Fallback for exact backend-level actions like seeking specific seconds
            if sys.platform == "win32":
                await self._control_media_win32_cmd(action)
            elif sys.platform.startswith("linux"):
                await self._control_media_linux(action)
            elif sys.platform == "darwin":
                await self._control_media_darwin(action)

        await self._apply_heuristics(action)

    async def seek_media(self, position_sec: int):
        """Seeks to a specific position using OS native APIs."""
        if sys.platform == "win32":
            await self._control_media_win32_cmd("seek", position_sec)
        elif sys.platform.startswith("linux"):
            await self._control_media_linux("seek", position_sec)
        elif sys.platform == "darwin":
            await self._control_media_darwin("seek", position_sec)

    async def _apply_heuristics(self, action: str):
        """Injects state tracking for non-feedback legacy players."""
        if self._cache["last_valid_data"]:
            current = self._cache["last_valid_data"].copy()
            if action in ["play_pause", "toggle_play", "play", "pause"]:
                curr_status = current.get("status", "STOPPED").upper()
                new_status = "PAUSED" if curr_status == "PLAYING" else "PLAYING"
                current["status"] = new_status
                self._cache.update(
                    {
                        "last_valid_data": current,
                        "last_valid_time": time.time(),
                        "data": current,
                        "timestamp": time.time(),
                        "command_lock_target": new_status,
                        "command_lock_until": time.time() + 3.0,
                    }
                )

    async def _control_media_win32_cmd(self, action: str, position_sec: int = 0):
        """Handles Windows-specific commands not covered by hardware keys (e.g., exact seeking)."""
        if action == "seek":
            try:
                from winrt.windows.media.control import (
                    GlobalSystemMediaTransportControlsSessionManager as MediaManager,
                )

                manager = await MediaManager.request_async()
                session = manager.get_current_session()
                if session:
                    await session.try_change_playback_position_async(
                        int(position_sec * 10_000_000)
                    )
            except Exception as e:
                log.debug(f"Windows SMTC seek failed: {e}")

    async def _control_media_linux(self, action: str, position_sec: int = 0):
        """Handles Linux-specific commands not covered by hardware keys."""
        if action == "seek":
            try:
                from .system_service import system_service

                # Using -a to apply to all active compatible players
                await system_service.run_command(
                    ["playerctl", "-a", "position", str(position_sec)]
                )
            except Exception as e:
                log.debug(f"Linux playerctl seek failed: {e}")

    async def _control_media_darwin(self, action: str, position_sec: int = 0):
        pass  # Placeholder

    async def get_media_info(self) -> Dict[str, Any]:
        """Caches and returns the current media playback state."""
        # Info fetching MUST use native OS APIs (winrt/playerctl) because keys cannot read state
        now = time.time()
        if (
            self._cache["data"].get("title") != "Nothing Playing"
            and now - self._cache["timestamp"] < _MEDIA_CACHE_TTL
        ):
            return self._cache["data"]

        if sys.platform == "win32":
            data = await self._get_media_info_win32()
        elif sys.platform == "darwin":
            data = await self._get_media_info_darwin()
        elif sys.platform.startswith("linux"):
            data = await self._get_media_info_linux()
        else:
            data = DEFAULT_MEDIA_INFO.copy()

        # State Persistence
        is_empty = data.get("status") in ["STOPPED", "NO_SESSION"] or data.get(
            "title"
        ) in ["Nothing Playing", ""]

        if (
            is_empty
            and self._cache["last_valid_data"]
            and (now - self._cache["last_valid_time"] < _LEGACY_STATE_RETENTION)
        ):
            data = self._cache["last_valid_data"].copy()
            data["status"] = "PAUSED"

        self._cache["data"] = data
        self._cache["timestamp"] = now
        if not is_empty:
            self._cache["last_valid_data"] = data
            self._cache["last_valid_time"] = now

        return data

    async def _get_media_info_win32(self) -> Dict[str, Any]:
        smtc_data = None
        try:
            from winrt.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as MediaManager,
            )

            manager = await MediaManager.request_async()
            session = manager.get_current_session()
            if session:
                info = await session.try_get_media_properties_async()
                playback = session.get_playback_info()
                timeline = session.get_timeline_properties()
                status_map = {0: "STOPPED", 1: "PAUSED", 4: "PLAYING"}
                smtc_data = {
                    "title": info.title or "Unknown Media",
                    "artist": info.artist or "",
                    "status": status_map.get(playback.playback_status, "STOPPED"),
                    "position_sec": int(timeline.position.total_seconds()),
                    "duration_sec": int(timeline.end_time.total_seconds()),
                    "control_level": "full",
                    "source_app": "System Media",
                }
        except Exception:
            pass

        legacy_data = await asyncio.to_thread(self._get_legacy_media_info_sync)
        if (
            legacy_data
            and smtc_data
            and smtc_data["title"].lower() in legacy_data["title"].lower()
        ):
            legacy_data.update(smtc_data)  # Merge
            return legacy_data

        return smtc_data if smtc_data else (legacy_data or DEFAULT_MEDIA_INFO.copy())

    def _get_legacy_media_info_sync(self) -> Optional[Dict[str, Any]]:
        if not LEGACY_SUPPORT_AVAILABLE:
            return None
        found_media = None

        def enum_window_callback(hwnd, _):
            nonlocal found_media
            if not win32gui.IsWindowVisible(hwnd):
                return
            try:
                text = win32gui.GetWindowText(hwnd)
                if not text:
                    return
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                proc = psutil.Process(pid)
                if proc.name().lower() in KNOWN_LEGACY_PLAYERS:
                    found_media = {
                        "title": text,
                        "status": "PLAYING",
                        "source_app": "Legacy",
                    }
            except Exception:
                pass

        win32gui.EnumWindows(enum_window_callback, None)
        return found_media

    async def _get_media_info_linux(self) -> Dict[str, Any]:
        if self._has_playerctl is False:
            return DEFAULT_MEDIA_INFO.copy()

        try:
            from .system_service import system_service

            status = await system_service.run_command(
                ["playerctl", "status"], timeout=1.0
            )
            self._has_playerctl = True

            status = status.strip().upper() if status else "STOPPED"

            if status in ["PLAYING", "PAUSED"]:
                title = await system_service.run_command(
                    ["playerctl", "metadata", "title"]
                )
                artist = await system_service.run_command(
                    ["playerctl", "metadata", "artist"]
                )

                return {
                    "title": title.strip() if title else "Unknown",
                    "artist": artist.strip() if artist else "",
                    "status": status,
                    "source_app": "Mpris",
                }
        except Exception as e:
            if isinstance(e, FileNotFoundError):
                self._has_playerctl = False

        return DEFAULT_MEDIA_INFO.copy()

    async def _get_media_info_darwin(self) -> Dict[str, Any]:
        return DEFAULT_MEDIA_INFO.copy()


# Global instance
media_service = MediaService()
