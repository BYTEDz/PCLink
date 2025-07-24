"""
PCLink - Remote PC Control Server - Process Manager API Module
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

import base64
import platform
from io import BytesIO
from typing import List

import psutil
from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

if platform.system() == "Windows":
    import win32con
    import win32gui
    import win32ui
    from PIL import Image


class ProcessInfo(BaseModel):
    pid: int
    name: str
    username: str | None
    cpu_percent: float
    memory_mb: float
    icon_base64: str | None = None


class KillPayload(BaseModel):
    pid: int


router = APIRouter()


def _get_icon_base64(exe_path: str) -> str | None:
    if not exe_path or not exe_path.lower().endswith(".exe"):
        return None
    try:
        large, small = win32gui.ExtractIconEx(exe_path, 0, 1)
        icon_to_use = large[0] if large else (small[0] if small else None)

        if not icon_to_use:
            return None

        hdc = win32ui.CreateDCFromHandle(win32gui.GetDC(0))
        hbmp = win32ui.CreateBitmap()
        hbmp.CreateCompatibleBitmap(hdc, 32, 32)
        hdc = hdc.CreateCompatibleDC()
        hdc.SelectObject(hbmp)

        hdc.DrawIcon((0, 0), icon_to_use)

        bmpinfo = hbmp.GetInfo()
        bmpstr = hbmp.GetBitmapBits(True)
        pil_img = Image.frombuffer(
            "RGBA",
            (bmpinfo["bmWidth"], bmpinfo["bmHeight"]),
            bmpstr,
            "raw",
            "BGRA",
            0,
            1,
        )

        buffered = BytesIO()
        pil_img.save(buffered, format="PNG")

        base64_str = base64.b64encode(buffered.getvalue()).decode("utf-8")

        win32gui.DestroyIcon(icon_to_use)
        win32gui.DeleteObject(hbmp.GetHandle())
        hdc.DeleteDC()

        return base64_str
    except Exception:
        return None


@router.get("/processes", response_model=List[ProcessInfo])
async def get_running_processes():
    processes = []
    is_windows = platform.system() == "Windows"
    psutil.cpu_percent(interval=None)

    for proc in psutil.process_iter(
        ["pid", "name", "username", "cpu_percent", "memory_info", "exe"]
    ):
        try:
            icon_b64 = None
            if is_windows:
                icon_b64 = _get_icon_base64(proc.info["exe"])

            processes.append(
                ProcessInfo(
                    pid=proc.info["pid"],
                    name=proc.info["name"],
                    username=proc.info["username"],
                    cpu_percent=round(proc.info["cpu_percent"], 2),
                    memory_mb=round(proc.info["memory_info"].rss / (1024 * 1024), 2),
                    icon_base64=icon_b64,
                )
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return processes


@router.post("/processes/kill")
async def kill_process(payload: KillPayload):
    try:
        process = psutil.Process(payload.pid)
        process.kill()
        return {
            "status": "success",
            "message": f"Process {payload.pid} ({process.name()}) terminated.",
        }
    except psutil.NoSuchProcess:
        raise HTTPException(
            status_code=404, detail=f"Process with PID {payload.pid} not found."
        )
    except psutil.AccessDenied:
        raise HTTPException(
            status_code=403,
            detail=f"Permission denied to terminate process {payload.pid}.",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to kill process: {e}")
