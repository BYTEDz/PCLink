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
import keyboard
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .services import get_media_info_data

router = APIRouter()

class MediaActionModel(BaseModel):
    action: str


@router.get("/")
async def get_media_info():
    """Provides information about the currently playing media."""
    return get_media_info_data()


@router.post("/")
async def media_command(payload: MediaActionModel):
    """Executes media commands like play/pause, next, and previous."""
    action_map = {
        "play_pause": "play/pause media",
        "next_track": "next track",
        "prev_track": "previous track",
    }
    if not (key := action_map.get(payload.action)):
        raise HTTPException(status_code=400, detail="Invalid media action")
    keyboard.send(key)
    return {"status": "command sent"}