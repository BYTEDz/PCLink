# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import platform
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .services import get_key, keyboard_controller, PYNPUT_AVAILABLE

router = APIRouter()


class KeyboardInputModel(BaseModel):
    """
    Model for keyboard input commands.
    Can specify text to type or a single key press with optional modifiers.
    """

    text: Optional[str] = None
    key: Optional[str] = None
    modifiers: List[str] = []


def _map_platform_key(key_name: str) -> str:
    """Translates generic key names to platform-specific ones for pynput."""
    key_map = {
        "meta": {
            "Windows": "win",
            "Darwin": "cmd",
            "Linux": "super",
        }
    }
    
    lower_key = key_name.lower()
    if lower_key in key_map:
        platform_specific_map = key_map[lower_key]
        return platform_specific_map.get(platform.system(), lower_key)

    return key_name


@router.post("/keyboard")
async def send_keyboard_input(payload: KeyboardInputModel):
    """
    Sends keyboard input to the system.

    Can either type a string of text or press a single key with optional modifiers.

    Args:
        payload: A KeyboardInputModel containing the input details.

    Returns:
        A status message indicating the input was sent.

    Raises:
        HTTPException: If the payload is invalid or an error occurs during input simulation.
    """
    if not PYNPUT_AVAILABLE:
        raise HTTPException(status_code=503, detail="Input control not available - pynput not installed")
    
    try:
        if payload.text:
            keyboard_controller.type(payload.text)
        elif payload.key:
            mapped_modifiers = [_map_platform_key(mod) for mod in payload.modifiers]
            mapped_key = _map_platform_key(payload.key)

            for mod in mapped_modifiers:
                keyboard_controller.press(get_key(mod))

            key = get_key(mapped_key)
            keyboard_controller.press(key)
            keyboard_controller.release(key)

            for mod in reversed(mapped_modifiers):
                keyboard_controller.release(get_key(mod))
        else:
            raise HTTPException(status_code=400, detail="Either 'text' or 'key' must be provided.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Keyboard input failed: {e}")
    return {"status": "input sent"}