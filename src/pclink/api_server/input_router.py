# filename: src/pclink/api_server/input_router.py
"""
PCLink - Remote PC Control Server - Input API Module
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
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .services import get_key, keyboard_controller

router = APIRouter()


class KeyboardInputModel(BaseModel):
    text: Optional[str] = None
    key: Optional[str] = None
    modifiers: List[str] = []


@router.post("/keyboard")
async def send_keyboard_input(payload: KeyboardInputModel):
    """Receives and executes keyboard input commands."""
    try:
        if payload.text:
            keyboard_controller.type(payload.text)
        elif payload.key:
            for mod in payload.modifiers:
                keyboard_controller.press(get_key(mod))
            
            key = get_key(payload.key)
            keyboard_controller.press(key)
            keyboard_controller.release(key)
            
            for mod in reversed(payload.modifiers):
                keyboard_controller.release(get_key(mod))
        else:
            raise HTTPException(status_code=400, detail="Either 'text' or 'key' must be provided.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Keyboard input failed: {e}")
    return {"status": "input sent"}