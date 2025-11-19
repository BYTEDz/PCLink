# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import base64
import logging
import platform
from io import BytesIO
from typing import List, Dict

import psutil
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# Conditional imports for Windows-specific icon extraction.
if platform.system() == "Windows":
    try:
        import win32gui
        import win32ui

        IS_WINDOWS_ICON_SUPPORT = True
    except ImportError:
        IS_WINDOWS_ICON_SUPPORT = False
else:
    IS_WINDOWS_ICON_SUPPORT = False

log = logging.getLogger(__name__)


class ProcessInfo(BaseModel):
    """Represents information about a running process."""
    pid: int
    name: str
    username: str | None
    cpu_percent: float
    memory_mb: float
    icon_base64: str | None = None


class KillPayload(BaseModel):
    """Payload model for the kill process endpoint."""
    pid: int


router = APIRouter()


def _get_icon_base64(exe_path: str) -> str | None:
    """
    Extracts the icon from a Windows executable and returns it as a base64 encoded PNG.
    This function will only run if Windows-specific libraries were successfully imported.
    """
    if not IS_WINDOWS_ICON_SUPPORT or not exe_path or not exe_path.lower().endswith(".exe"):
        return None
        
    try:
        large, small = win32gui.ExtractIconEx(exe_path, 0, 1)
        icon_to_use = large[0] if large else (small[0] if small else None)
        if not icon_to_use:
            return None

        hdc = win32ui.CreateDCFromHandle(win32gui.GetDC(0))
        hbmp = win32ui.CreateBitmap()
        hbmp.CreateCompatibleBitmap(hdc, 32, 32)
        hdc_mem = hdc.CreateCompatibleDC()
        hdc_mem.SelectObject(hbmp)
        hdc_mem.DrawIcon((0, 0), icon_to_use)

        bmpinfo = hbmp.GetInfo()
        bmpstr = hbmp.GetBitmapBits(True)
        try:
            from PIL import Image
            pil_img = Image.frombuffer(
                "RGBA", (bmpinfo["bmWidth"], bmpinfo["bmHeight"]), bmpstr, "raw", "BGRA", 0, 1
            )

            buffered = BytesIO()
            pil_img.save(buffered, format="PNG")
            base64_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
        except ImportError:
            # Fallback: return empty string if PIL not available
            base64_str = ""

        win32gui.DestroyIcon(icon_to_use)
        win32gui.DeleteObject(hbmp.GetHandle())
        hdc_mem.DeleteDC()
        hdc.DeleteDC()
        return base64_str
    except Exception:
        # Log the error but don't crash if an icon can't be extracted.
        # log.debug(f"Could not extract icon for {exe_path}: {e}")
        return None


@router.get("/processes", response_model=List[ProcessInfo])
async def get_running_processes() -> List[ProcessInfo]:
    """
    Retrieves a list of running processes with details. Optimized for performance and cross-platform compatibility.
    """
    processes_data: List[ProcessInfo] = []
    # Get total CPU usage over a small interval to make process CPU percentages more accurate.
    psutil.cpu_percent(interval=0.1)

    attrs = ["pid", "name", "username", "cpu_percent", "memory_info"]
    if IS_WINDOWS_ICON_SUPPORT:
        attrs.append("exe")

    for proc in psutil.process_iter(attrs=attrs):
        try:
            proc_info = proc.info
            # Skip system idle processes or processes without a name
            if not proc_info.get("name"):
                continue

            icon_b64 = _get_icon_base64(proc_info["exe"]) if IS_WINDOWS_ICON_SUPPORT and proc_info.get("exe") else None
            memory_mb = round(proc_info["memory_info"].rss / (1024 * 1024), 2) if proc_info.get("memory_info") else 0.0
            
            # cpu_percent can be None on the first call
            cpu = proc_info.get("cpu_percent") or 0.0

            processes_data.append(
                ProcessInfo(
                    pid=proc_info["pid"],
                    name=proc_info["name"],
                    username=proc_info.get("username", "N/A"),
                    cpu_percent=round(cpu, 2),
                    memory_mb=memory_mb,
                    icon_base64=icon_b64,
                )
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        except Exception as e:
            log.warning(f"Could not process PID {proc.pid if proc else 'N/A'}: {e}")
            continue
    return processes_data


@router.post("/processes/kill")
async def kill_process(payload: KillPayload) -> Dict[str, str]:
    """Terminates a process by its PID."""
    try:
        process = psutil.Process(payload.pid)
        process_name = process.name()
        process.kill()
        return {
            "status": "success",
            "message": f"Process {payload.pid} ({process_name}) terminated.",
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