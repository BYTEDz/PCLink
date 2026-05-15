# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import logging
import time
from collections import deque
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator

from ...services import input_service

log = logging.getLogger(__name__)


# --- Dependencies ---
def verify_input_available():
    """Dependency to ensure input control is active."""
    if not input_service.is_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Input control not available",
        )


# NOTE: Ensure you add your authentication dependency here (e.g., dependencies=[Depends(verify_token), Depends(verify_input_available)])
router = APIRouter(dependencies=[Depends(verify_input_available)])


# --- Models ---
class KeyboardInputModel(BaseModel):
    text: Optional[str] = Field(
        None, max_length=2000, description="Max 2000 chars per payload"
    )
    key: Optional[str] = Field(None, max_length=20)
    modifiers: List[str] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def check_text_or_key(self):
        if not self.text and not self.key:
            raise ValueError("Either 'text' or 'key' must be provided.")
        return self


class MouseMoveModel(BaseModel):
    dx: int = Field(..., ge=-5000, le=5000)
    dy: int = Field(..., ge=-5000, le=5000)


class MouseClickModel(BaseModel):
    button: str = Field(default="left", pattern="^(left|right|middle)$")
    clicks: int = Field(default=1, ge=1, le=50)  # Stop arbitrary high-click freezing


class MouseScrollModel(BaseModel):
    dx: int = Field(..., ge=-1000, le=1000)
    dy: int = Field(..., ge=-1000, le=1000)


# --- Rate Limiter ---
class RateLimiter:
    def __init__(self, max_calls: int, period: float):
        self.max_calls = max_calls
        self.period = period
        self.calls = deque()

    def allow(self) -> bool:
        now = time.monotonic()  # Safe from system clock changes
        # O(1) removals from the left side instead of O(N) list rebuilds
        while self.calls and now - self.calls[0] >= self.period:
            self.calls.popleft()

        if len(self.calls) >= self.max_calls:
            return False

        self.calls.append(now)
        return True


mouse_move_limiter = RateLimiter(max_calls=60, period=1.0)
mouse_scroll_limiter = RateLimiter(max_calls=60, period=1.0)


# --- Endpoints ---
@router.post("/keyboard")
async def send_keyboard_input(payload: KeyboardInputModel):
    try:
        if payload.text:
            await asyncio.to_thread(input_service.keyboard_type, payload.text)
        elif payload.key:
            await asyncio.to_thread(
                input_service.keyboard_press_key, payload.key, payload.modifiers
            )
    except Exception as e:
        log.error(f"Keyboard input failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Input execution failed",
        )

    return {"status": "input sent"}


@router.post("/mouse/move")
async def move_mouse(payload: MouseMoveModel):
    if not mouse_move_limiter.allow():
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded"
        )

    try:
        await asyncio.to_thread(input_service.mouse_move, payload.dx, payload.dy)
        return {"status": "moved"}
    except Exception as e:
        log.error(f"Mouse move failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Move execution failed",
        )


@router.post("/mouse/click")
async def click_mouse(payload: MouseClickModel):
    try:
        await asyncio.to_thread(
            input_service.mouse_click, payload.button, payload.clicks
        )
        return {"status": "clicked"}
    except Exception as e:
        log.error(f"Mouse click failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Click execution failed",
        )


@router.post("/mouse/scroll")
async def scroll_mouse(payload: MouseScrollModel):
    if not mouse_scroll_limiter.allow():
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded"
        )

    try:
        await asyncio.to_thread(input_service.mouse_scroll, payload.dx, payload.dy)
        return {"status": "scrolled"}
    except Exception as e:
        log.error(f"Mouse scroll failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Scroll execution failed",
        )
