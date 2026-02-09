# src/pclink/services/utility_service.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import logging
import subprocess
import sys
import time
from io import BytesIO
from typing import Dict
import platform
import pyperclip
import mss

from ..core.wayland_utils import (
    is_wayland, screenshot_portal,
    clipboard_get_wayland, clipboard_set_wayland
)

log = logging.getLogger(__name__)

class UtilityService:
    """Logic for shell commands, clipboard, and screenshots."""
    
    def __init__(self):
        self._is_wayland_session = None
        # Command deduplication to prevent rapid duplicate executions
        self._recent_commands: Dict[str, float] = {}
        self._COMMAND_COOLDOWN = 2.0  # 2 seconds

    def _check_wayland(self) -> bool:
        if self._is_wayland_session is None:
            self._is_wayland_session = is_wayland()
        return self._is_wayland_session

    async def run_command_detached(self, command: str):
        """Runs a command without waiting, detached for GUI apps."""
        # Deduplicate rapid-fire duplicate commands
        now = time.time()
        if command in self._recent_commands:
            if now - self._recent_commands[command] < self._COMMAND_COOLDOWN:
                log.warning(f"Duplicate command blocked (cooldown): {command[:50]}...")
                return
        self._recent_commands[command] = now
        
        # Cleanup old entries to prevent memory growth
        self._recent_commands = {k: v for k, v in self._recent_commands.items() if now - v < 60}
        
        def _execute():
            flags = 0
            if sys.platform == "win32":
                flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
            subprocess.Popen(command, shell=True, creationflags=flags)
        
        await asyncio.to_thread(_execute)

    async def get_clipboard(self) -> str:
        if self._check_wayland():
            try:
                text = await asyncio.to_thread(clipboard_get_wayland)
                if text is not None: return text
            except Exception: pass
        
        try:
            return pyperclip.paste()
        except Exception as e:
            log.warning(f"Clipboard paste failed: {e}")
            return ""

    async def set_clipboard(self, text: str):
        if self._check_wayland():
            try:
                success = await asyncio.to_thread(clipboard_set_wayland, text)
                if success: return
            except Exception: pass
        
        try:
            pyperclip.copy(text)
        except Exception as e:
            log.warning(f"Clipboard copy failed: {e}")

    async def get_screenshot(self) -> bytes:
        if self._check_wayland():
            data = await asyncio.to_thread(screenshot_portal)
            if data: return data
        
        def _grab():
            with mss.mss() as sct:
                sct_img = sct.grab(sct.monitors[1])
                from PIL import Image
                img = Image.frombytes("RGB", sct_img.size, sct_img.rgb)
                buffer = BytesIO()
                img.save(buffer, format="PNG")
                return buffer.getvalue()
        
        return await asyncio.to_thread(_grab)

# Global instance
utility_service = UtilityService()
