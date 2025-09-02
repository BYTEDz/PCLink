# filename: src/pclink/api_server/utils_router.py
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
from io import BytesIO

import mss
import pyperclip
from fastapi import APIRouter
from fastapi.responses import Response
from PIL import Image
from pydantic import BaseModel

router = APIRouter()


class ClipboardModel(BaseModel):
    text: str


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
        img = Image.frombytes("RGB", sct_img.size, sct_img.rgb)
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        return Response(content=buffer.getvalue(), media_type="image/png")