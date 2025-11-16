"""
PCLink - Remote PC Control Server - Utils API Module
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
import subprocess
import sys
from io import BytesIO

import mss
import pyperclip
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

log = logging.getLogger(__name__)
router = APIRouter()


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
    pyperclip.copy(payload.text)
    return {"status": "Clipboard updated"}


@router.get("/clipboard")
async def get_clipboard():
    """Gets the system clipboard text."""
    return {"text": pyperclip.paste()}


@router.get("/screenshot")
async def get_screenshot():
    """Captures and returns a screenshot of the primary monitor."""
    with mss.mss() as sct:
        sct_img = sct.grab(sct.monitors[1])
        try:
            from PIL import Image
            img = Image.frombytes("RGB", sct_img.size, sct_img.rgb)
            buffer = BytesIO()
            img.save(buffer, format="PNG")
            return Response(content=buffer.getvalue(), media_type="image/png")
        except ImportError:
            # Fallback: return error if PIL not available
            raise HTTPException(status_code=500, detail="PIL not available for screenshot functionality")