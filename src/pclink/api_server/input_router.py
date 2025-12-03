# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
import platform
import time
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# Added mouse_controller and button_map imports
from .services import get_key, keyboard_controller, mouse_controller, button_map, PYNPUT_AVAILABLE

router = APIRouter()
log = logging.getLogger(__name__)

# --- Models ---

class KeyboardInputModel(BaseModel):
    """
    Model for keyboard input commands.
    Can specify text to type or a single key press with optional modifiers.
    """
    text: Optional[str] = None
    key: Optional[str] = None
    modifiers: List[str] = []

class MouseMoveModel(BaseModel):
    dx: int
    dy: int

class MouseClickModel(BaseModel):
    button: str = "left"
    clicks: int = 1

class MouseScrollModel(BaseModel):
    dx: int
    dy: int

# --- Rate Limiter ---

class RateLimiter:
    """
    Simple rate limiter to drop excessive requests (e.g. mouse movements).
    """
    def __init__(self, max_calls: int, period: float):
        self.max_calls = max_calls
        self.period = period
        self.calls = []

    def allow(self) -> bool:
        now = time.time()
        # Remove timestamps older than the period
        self.calls = [t for t in self.calls if now - t < self.period]
        
        if len(self.calls) >= self.max_calls:
            return False
            
        self.calls.append(now)
        return True

# Limit mouse moves to 60Hz to prevent server overload
mouse_move_limiter = RateLimiter(max_calls=60, period=1.0)
# Scroll can also be high frequency
mouse_scroll_limiter = RateLimiter(max_calls=60, period=1.0)


# --- Helpers ---

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


# --- Endpoints ---

@router.post("/keyboard")
async def send_keyboard_input(payload: KeyboardInputModel):
    """
    Sends keyboard input to the system.
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
        log.error(f"Keyboard input failed: {e}")
        raise HTTPException(status_code=500, detail=f"Keyboard input failed: {e}")
    return {"status": "input sent"}


@router.post("/mouse/move")
async def move_mouse(payload: MouseMoveModel):
    """
    Moves the mouse cursor. Rate limited to 60Hz.
    """
    if not PYNPUT_AVAILABLE:
        raise HTTPException(status_code=503, detail="Input control not available")
    
    # Rate Limiting: Drop packets if too frequent
    if not mouse_move_limiter.allow():
        return {"status": "dropped"}

    try:
        mouse_controller.move(payload.dx, payload.dy)
        return {"status": "moved"}
    except Exception as e:
        log.error(f"Mouse move failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/mouse/click")
async def click_mouse(payload: MouseClickModel):
    """
    Clicks a mouse button.
    """
    if not PYNPUT_AVAILABLE:
        raise HTTPException(status_code=503, detail="Input control not available")
    
    try:
        btn = button_map.get(payload.button, button_map["left"])
        mouse_controller.click(btn, payload.clicks)
        return {"status": "clicked"}
    except Exception as e:
        log.error(f"Mouse click failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/mouse/scroll")
async def scroll_mouse(payload: MouseScrollModel):
    """
    Scrolls the mouse wheel. Rate limited.
    """
    if not PYNPUT_AVAILABLE:
        raise HTTPException(status_code=503, detail="Input control not available")
        
    if not mouse_scroll_limiter.allow():
        return {"status": "dropped"}

    try:
        mouse_controller.scroll(payload.dx, payload.dy)
        return {"status": "scrolled"}
    except Exception as e:
        log.error(f"Mouse scroll failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))