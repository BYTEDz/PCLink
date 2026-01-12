# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from ..services.utility_service import utility_service

log = logging.getLogger(__name__)
router = APIRouter()

class ClipboardModel(BaseModel):
    text: str

class CommandModel(BaseModel):
    command: str

@router.post("/command")
async def run_command(payload: CommandModel):
    """Executes a shell command on the server."""
    if not payload.command:
        raise HTTPException(status_code=400, detail="Command cannot be empty.")
    try:
        await utility_service.run_command_detached(payload.command)
        return {"status": "command sent"}
    except Exception as e:
        log.error(f"Command execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/clipboard")
async def set_clipboard(payload: ClipboardModel):
    """Sets the system clipboard text."""
    await utility_service.set_clipboard(payload.text)
    return {"status": "Clipboard updated"}

@router.get("/clipboard")
async def get_clipboard():
    """Gets the system clipboard text."""
    return {"text": await utility_service.get_clipboard()}

@router.get("/screenshot")
async def get_screenshot():
    """Captures and returns a screenshot of the primary monitor."""
    try:
        data = await utility_service.get_screenshot()
        return Response(content=data, media_type="image/png")
    except ImportError:
        raise HTTPException(status_code=500, detail="Required libraries (PIL) not available.")
    except Exception as e:
        log.error(f"Screenshot failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
