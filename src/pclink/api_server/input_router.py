# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
import time
from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..services import input_service

router = APIRouter()
log = logging.getLogger(__name__)

# --- Models ---

class KeyboardInputModel(BaseModel):
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
    def __init__(self, max_calls: int, period: float):
        self.max_calls = max_calls
        self.period = period
        self.calls = []

    def allow(self) -> bool:
        now = time.time()
        self.calls = [t for t in self.calls if now - t < self.period]
        if len(self.calls) >= self.max_calls: return False
        self.calls.append(now)
        return True

mouse_move_limiter = RateLimiter(max_calls=60, period=1.0)
mouse_scroll_limiter = RateLimiter(max_calls=60, period=1.0)

# --- Endpoints ---

@router.post("/keyboard")
async def send_keyboard_input(payload: KeyboardInputModel):
    if not input_service.is_available():
        raise HTTPException(status_code=503, detail="Input control not available")
    try:
        if payload.text:
            input_service.keyboard_type(payload.text)
        elif payload.key:
            input_service.keyboard_press_key(payload.key, payload.modifiers)
        else:
            raise HTTPException(status_code=400, detail="Either 'text' or 'key' must be provided.")
    except Exception as e:
        log.error(f"Keyboard input failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "input sent"}

@router.post("/mouse/move")
async def move_mouse(payload: MouseMoveModel):
    if not input_service.is_available(): raise HTTPException(status_code=503, detail="Input control not available")
    if not mouse_move_limiter.allow(): return {"status": "dropped"}
    try:
        input_service.mouse_move(payload.dx, payload.dy)
        return {"status": "moved"}
    except Exception as e:
        log.error(f"Mouse move failed: {e}"); raise HTTPException(status_code=500, detail=str(e))

@router.post("/mouse/click")
async def click_mouse(payload: MouseClickModel):
    if not input_service.is_available(): raise HTTPException(status_code=503, detail="Input control not available")
    try:
        input_service.mouse_click(payload.button, payload.clicks)
        return {"status": "clicked"}
    except Exception as e:
        log.error(f"Mouse click failed: {e}"); raise HTTPException(status_code=500, detail=str(e))

@router.post("/mouse/scroll")
async def scroll_mouse(payload: MouseScrollModel):
    if not input_service.is_available(): raise HTTPException(status_code=503, detail="Input control not available")
    if not mouse_scroll_limiter.allow(): return {"status": "dropped"}
    try:
        input_service.mouse_scroll(payload.dx, payload.dy)
        return {"status": "scrolled"}
    except Exception as e:
        log.error(f"Mouse scroll failed: {e}"); raise HTTPException(status_code=500, detail=str(e))