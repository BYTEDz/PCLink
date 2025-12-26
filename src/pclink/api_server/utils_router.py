# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import logging
import subprocess
import sys
from io import BytesIO

import mss
import pyperclip
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from ..core.wayland_utils import (
    is_wayland,
    screenshot_portal,
    clipboard_get_wayland,
    clipboard_set_wayland,
)

log = logging.getLogger(__name__)
router = APIRouter()

# Cache Wayland detection result
_is_wayland_session = None

def _check_wayland() -> bool:
    """Check if running under Wayland (cached)."""
    global _is_wayland_session
    if _is_wayland_session is None:
        _is_wayland_session = is_wayland()
        if _is_wayland_session:
            log.info("Detected Wayland session - using Wayland-compatible backends")
        else:
            log.info("Detected X11 session - using standard backends")
    return _is_wayland_session


class ClipboardModel(BaseModel):
    text: str

class CommandModel(BaseModel):
    command: str


def _run_command_fire_and_forget(command: str):
    """
    Synchronously runs a command without waiting for it to complete.
    This is ideal for launching GUI applications.
    """
    try:
        flags = 0
        # On Windows, use flags to detach the process and hide the console window
        if sys.platform == "win32":
            flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
        
        # shell=True is used to correctly interpret commands like a user would in a terminal.
        # This is acceptable here as the API is authenticated.
        subprocess.Popen(command, shell=True, creationflags=flags)
        log.info(f"Successfully executed command: {command}")
    except Exception as e:
        log.error(f"Failed to execute command '{command}': {e}")
        # This function doesn't re-raise because it's fire-and-forget,
        # but we log the error for debugging.

@router.post("/command")
async def run_command(payload: CommandModel):
    """
    Executes a shell command on the server without waiting for output.
    This is useful for launching applications or running background scripts.
    """
    if not payload.command:
        raise HTTPException(status_code=400, detail="Command cannot be empty.")
    
    try:
        # Run the command in a separate thread to avoid blocking the server's event loop.
        await asyncio.to_thread(_run_command_fire_and_forget, payload.command)
        return {"status": "command sent"}
    except Exception as e:
        log.error(f"Failed to spawn thread for command '{payload.command}': {e}")
        raise HTTPException(status_code=500, detail=f"Failed to run command: {e}")


@router.post("/clipboard")
async def set_clipboard(payload: ClipboardModel):
    """Sets the system clipboard text."""
    if _check_wayland():
        success = await asyncio.to_thread(clipboard_set_wayland, payload.text)
        if not success:
            # Fallback to pyperclip if wl-copy fails
            log.warning("Wayland clipboard failed, trying pyperclip fallback")
            pyperclip.copy(payload.text)
    else:
        pyperclip.copy(payload.text)
    return {"status": "Clipboard updated"}


@router.get("/clipboard")
async def get_clipboard():
    """Gets the system clipboard text."""
    if _check_wayland():
        text = await asyncio.to_thread(clipboard_get_wayland)
        if text is not None:
            return {"text": text}
        # Fallback to pyperclip if wl-paste fails
        log.warning("Wayland clipboard failed, trying pyperclip fallback")
    return {"text": pyperclip.paste()}


@router.get("/screenshot")
async def get_screenshot():
    """Captures and returns a screenshot of the primary monitor."""
    
    # Try Wayland screenshot first if on Wayland
    if _check_wayland():
        log.info("Using Wayland screenshot method")
        screenshot_data = await asyncio.to_thread(screenshot_portal)
        if screenshot_data:
            return Response(content=screenshot_data, media_type="image/png")
        log.warning("Wayland screenshot failed, falling back to mss")
    
    # X11 / fallback: use mss
    try:
        with mss.mss() as sct:
            sct_img = sct.grab(sct.monitors[1])
            try:
                from PIL import Image
                img = Image.frombytes("RGB", sct_img.size, sct_img.rgb)
                buffer = BytesIO()
                img.save(buffer, format="PNG")
                return Response(content=buffer.getvalue(), media_type="image/png")
            except ImportError:
                raise HTTPException(status_code=500, detail="PIL not available for screenshot functionality")
    except Exception as e:
        log.error(f"Screenshot failed: {e}")
        raise HTTPException(status_code=500, detail=f"Screenshot failed: {e}")
