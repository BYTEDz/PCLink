# src/pclink/services/utility_service.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import logging
import subprocess
import sys
import time
from io import BytesIO
from typing import Dict, Optional

import mss
import pyperclip

from ..core.wayland_utils import (
    clipboard_get_wayland,
    clipboard_set_wayland,
    is_wayland,
    screenshot_portal,
)

log = logging.getLogger(__name__)


def _process_image(
    img,
    max_width: Optional[int] = None,
    max_height: Optional[int] = None,
    quality: int = 80,
    format: str = "webp",
) -> bytes:
    """Resizes and compresses a PIL Image into specified format and quality."""
    from PIL import Image

    fmt = format.upper()
    if fmt == "JPG":
        fmt = "JPEG"

    # Constrain dimensions while preserving aspect ratio
    if max_width or max_height:
        w, h = img.size
        target_w = max_width or w
        target_h = max_height or h
        if target_w < w or target_h < h:
            img.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)

    # Convert alpha channel if saving to JPEG
    if fmt == "JPEG" and img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")

    clamped_quality = max(10, min(100, quality))
    buffer = BytesIO()

    try:
        if fmt in ("JPEG", "WEBP"):
            img.save(buffer, format=fmt, quality=clamped_quality, optimize=True)
        else:
            img.save(buffer, format="PNG", optimize=True)
    except Exception as e:
        log.warning(f"Encoding as {fmt} failed ({e}), falling back to PNG")
        buffer = BytesIO()
        img.save(buffer, format="PNG")

    return buffer.getvalue()


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
        now = time.time()
        if command in self._recent_commands:
            if now - self._recent_commands[command] < self._COMMAND_COOLDOWN:
                log.warning(f"Duplicate command blocked (cooldown): {command[:50]}...")
                return
        self._recent_commands[command] = now

        self._recent_commands = {
            k: v for k, v in self._recent_commands.items() if now - v < 60
        }

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
                if text is not None:
                    return text
            except Exception:
                pass

        try:
            return pyperclip.paste()
        except Exception as e:
            log.warning(f"Clipboard paste failed: {e}")
            return ""

    async def set_clipboard(self, text: str):
        if self._check_wayland():
            try:
                success = await asyncio.to_thread(clipboard_set_wayland, text)
                if success:
                    return
            except Exception:
                pass

        try:
            pyperclip.copy(text)
        except Exception as e:
            log.warning(f"Clipboard copy failed: {e}")

    async def get_screenshot(
        self,
        max_width: Optional[int] = None,
        max_height: Optional[int] = None,
        quality: int = 80,
        format: str = "webp",
        monitor: int = 1,
    ) -> bytes:
        from PIL import Image

        if self._check_wayland():
            data = await asyncio.to_thread(screenshot_portal)
            if data:

                def _process_wayland():
                    raw_img = Image.open(BytesIO(data))
                    return _process_image(
                        raw_img, max_width, max_height, quality, format
                    )

                return await asyncio.to_thread(_process_wayland)

        def _grab():
            with mss.mss() as sct:
                mon_idx = monitor if 0 <= monitor < len(sct.monitors) else 1
                sct_img = sct.grab(sct.monitors[mon_idx])
                img = Image.frombytes("RGB", sct_img.size, sct_img.rgb)
                return _process_image(img, max_width, max_height, quality, format)

        return await asyncio.to_thread(_grab)


# Global instance
utility_service = UtilityService()
