# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import ctypes
import gettext
import logging
import shutil
import sys
import time
from typing import Any, Dict

log = logging.getLogger(__name__)
_ = gettext.gettext

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

# Windows virtual key codes and flags
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3
VK_LEFT = 0x25
VK_RIGHT = 0x27

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002

_MEDIA_CACHE_TTL = 1.0
_LEGACY_STATE_RETENTION = 5.0


class MediaService:
    def __init__(self):
        self._cache = {
            "data": DEFAULT_MEDIA_INFO,
            "timestamp": 0,
            "last_valid_data": None,
            "last_valid_time": 0,
            "command_lock_target": None,
            "command_lock_until": 0,
        }
        self._has_playerctl = shutil.which("playerctl") is not None

    def _win32_key_tap(self, vk_code: int):
        user32 = ctypes.windll.user32
        # Must include KEYEVENTF_EXTENDEDKEY so Windows kernel routes media keys correctly
        user32.keybd_event(vk_code, 0, KEYEVENTF_EXTENDEDKEY, 0)
        time.sleep(0.02)
        user32.keybd_event(vk_code, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)

    async def media_command(self, action: str):
        action_map = {
            "toggle_play": "play_pause",
            "play": "play_pause",
            "pause": "play_pause",
            "next_track": "next",
            "prev_track": "previous",
            "prev": "previous",
            "vol_up": "volume_up",
            "vol_down": "volume_down",
            "mute": "mute_toggle",
        }
        norm_action = action_map.get(action, action)
        log.info(
            f"Processing media command: {action} (normalized: {norm_action}) on {sys.platform}"
        )

        executed = False

        if sys.platform == "win32":
            executed = await self._control_media_win32(norm_action)
        elif sys.platform.startswith("linux"):
            executed = await self._control_media_linux(norm_action)
        elif sys.platform == "darwin":
            executed = await self._control_media_darwin(norm_action)

        if not executed:
            await self._fallback_key_simulation(norm_action)

        await self._apply_heuristics(norm_action)

    async def _control_media_win32(self, action: str) -> bool:
        # 1. WinRT System Media Transport Controls
        try:
            from winrt.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as MediaManager,
            )

            manager = await MediaManager.request_async()
            session = manager.get_current_session()
            if session:
                if action == "play_pause":
                    await session.try_toggle_play_pause_async()
                    return True
                elif action == "next":
                    await session.try_skip_next_async()
                    return True
                elif action == "previous":
                    await session.try_skip_previous_async()
                    return True
                elif action == "stop":
                    await session.try_stop_async()
                    return True
        except Exception as e:
            log.debug(f"WinRT SMTC command error: {e}")

        # 2. Native Windows virtual keycode with extended key flag
        vk_map = {
            "play_pause": VK_MEDIA_PLAY_PAUSE,
            "next": VK_MEDIA_NEXT_TRACK,
            "previous": VK_MEDIA_PREV_TRACK,
            "volume_up": VK_VOLUME_UP,
            "volume_down": VK_VOLUME_DOWN,
            "mute_toggle": VK_VOLUME_MUTE,
            "seek_fwd": VK_RIGHT,
            "seek_bwd": VK_LEFT,
        }

        if action in vk_map:
            try:
                await asyncio.to_thread(self._win32_key_tap, vk_map[action])
                return True
            except Exception as e:
                log.debug(f"Win32 keybd_event error: {e}")

        return False

    async def _control_media_linux(self, action: str) -> bool:
        # 1. Native MPRIS D-Bus via playerctl
        if self._has_playerctl:
            playerctl_map = {
                "play_pause": ["playerctl", "-a", "play-pause"],
                "next": ["playerctl", "-a", "next"],
                "previous": ["playerctl", "-a", "previous"],
                "stop": ["playerctl", "-a", "stop"],
            }
            if action in playerctl_map:
                try:
                    import subprocess

                    res = await asyncio.to_thread(
                        subprocess.run,
                        playerctl_map[action],
                        capture_output=True,
                        timeout=1.0,
                    )
                    if res.returncode == 0:
                        return True
                except Exception as e:
                    log.debug(f"Linux playerctl execution failed: {e}")

        # 2. Hardware-level uinput/evdev injection
        try:
            from .input_service import input_service

            if input_service.use_evdev and input_service.evdev:
                from evdev import ecodes

                evdev_map = {
                    "play_pause": ecodes.KEY_PLAYPAUSE,
                    "next": ecodes.KEY_NEXTSONG,
                    "previous": ecodes.KEY_PREVIOUSSONG,
                    "volume_up": ecodes.KEY_VOLUMEUP,
                    "volume_down": ecodes.KEY_VOLUMEDOWN,
                    "mute_toggle": ecodes.KEY_MUTE,
                    "seek_fwd": ecodes.KEY_RIGHT,
                    "seek_bwd": ecodes.KEY_LEFT,
                }
                if action in evdev_map:
                    input_service.evdev.emit_key_tap(evdev_map[action])
                    return True
        except Exception as e:
            log.debug(f"Linux uinput key injection error: {e}")

        return False

    async def _control_media_darwin(self, action: str) -> bool:
        script_map = {
            "play_pause": 'tell application "System Events" to key code 16 using {option down}',
            "next": 'tell application "System Events" to key code 17 using {option down}',
            "previous": 'tell application "System Events" to key code 18 using {option down}',
        }
        if action in script_map:
            try:
                from .system_service import system_service

                await system_service.run_command(
                    ["osascript", "-e", script_map[action]], timeout=1.0
                )
                return True
            except Exception as e:
                log.debug(f"Darwin AppleScript error: {e}")
        return False

    async def _fallback_key_simulation(self, action: str):
        try:
            from pynput.keyboard import Controller, Key

            kb = Controller()
            key_map = {
                "play_pause": Key.media_play_pause,
                "next": Key.media_next,
                "previous": Key.media_previous,
                "volume_up": Key.media_volume_up,
                "volume_down": Key.media_volume_down,
                "mute_toggle": Key.media_volume_mute,
                "seek_fwd": Key.right,
                "seek_bwd": Key.left,
            }
            if action in key_map:
                kb.press(key_map[action])
                await asyncio.sleep(0.05)
                kb.release(key_map[action])
        except Exception:
            pass

    async def seek_media(self, position_sec: int):
        if sys.platform == "win32":
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
                log.debug(f"WinRT seek error: {e}")
        elif sys.platform.startswith("linux") and self._has_playerctl:
            try:
                from .system_service import system_service

                await system_service.run_command(
                    ["playerctl", "-a", "position", str(position_sec)], timeout=1.0
                )
            except Exception as e:
                log.debug(f"playerctl seek error: {e}")

    async def _apply_heuristics(self, action: str):
        if self._cache["last_valid_data"]:
            current = self._cache["last_valid_data"].copy()
            if action in ["play_pause", "toggle_play"]:
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

    async def get_media_info(self) -> Dict[str, Any]:
        now = time.time()
        if (
            self._cache["data"].get("title") != "Nothing Playing"
            and now - self._cache["timestamp"] < _MEDIA_CACHE_TTL
        ):
            return self._cache["data"]

        if sys.platform == "win32":
            data = await self._get_media_info_win32()
        elif sys.platform.startswith("linux"):
            data = await self._get_media_info_linux()
        else:
            data = DEFAULT_MEDIA_INFO.copy()

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
                return {
                    "title": info.title or "Unknown Media",
                    "artist": info.artist or "",
                    "album_title": info.album_title or "",
                    "status": status_map.get(playback.playback_status, "STOPPED"),
                    "position_sec": int(timeline.position.total_seconds())
                    if timeline
                    else 0,
                    "duration_sec": int(timeline.end_time.total_seconds())
                    if timeline
                    else 0,
                    "control_level": "full",
                    "source_app": "System Media",
                }
        except Exception:
            pass
        return DEFAULT_MEDIA_INFO.copy()

    async def _get_media_info_linux(self) -> Dict[str, Any]:
        if not self._has_playerctl:
            return DEFAULT_MEDIA_INFO.copy()

        try:
            from .system_service import system_service

            status = await system_service.run_command(
                ["playerctl", "status"], timeout=1.0
            )
            status = status.strip().upper() if status else "STOPPED"

            if status in ["PLAYING", "PAUSED"]:
                title = await system_service.run_command(
                    ["playerctl", "metadata", "title"], timeout=1.0
                )
                artist = await system_service.run_command(
                    ["playerctl", "metadata", "artist"], timeout=1.0
                )

                return {
                    "title": title.strip() if title else "Unknown",
                    "artist": artist.strip() if artist else "",
                    "album_title": "",
                    "status": status,
                    "position_sec": 0,
                    "duration_sec": 0,
                    "control_level": "full",
                    "source_app": "MPRIS",
                }
        except Exception:
            pass

        return DEFAULT_MEDIA_INFO.copy()


media_service = MediaService()
