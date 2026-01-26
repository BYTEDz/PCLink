# src/pclink/services/process_service.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import base64
import logging
import platform
import asyncio
from io import BytesIO
from typing import List, Dict, Optional, Any
from pydantic import BaseModel

import psutil

log = logging.getLogger(__name__)

# Conditional imports for Windows-specific icon extraction.
IS_WINDOWS = platform.system() == "Windows"
if IS_WINDOWS:
    try:
        import win32gui
        import win32ui
        IS_WINDOWS_ICON_SUPPORT = True
    except ImportError:
        IS_WINDOWS_ICON_SUPPORT = False
else:
    IS_WINDOWS_ICON_SUPPORT = False

class ProcessInfo(BaseModel):
    pid: int
    name: str
    username: Optional[str]
    cpu_percent: float
    memory_mb: float
    icon_base64: Optional[str] = None

class ProcessService:
    """Logic for process management and telemetry."""

    def _get_icon_base64(self, exe_path: str) -> Optional[str]:
        if not IS_WINDOWS_ICON_SUPPORT or not exe_path or not exe_path.lower().endswith(".exe"):
            return None
        try:
            large, small = win32gui.ExtractIconEx(exe_path, 0, 1)
            icon_to_use = large[0] if large else (small[0] if small else None)
            if not icon_to_use: return None

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
                pil_img = Image.frombuffer("RGBA", (bmpinfo["bmWidth"], bmpinfo["bmHeight"]), bmpstr, "raw", "BGRA", 0, 1)
                buffered = BytesIO()
                pil_img.save(buffered, format="PNG")
                base64_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
            except ImportError: base64_str = ""

            win32gui.DestroyIcon(icon_to_use)
            win32gui.DeleteObject(hbmp.GetHandle())
            hdc_mem.DeleteDC()
            hdc.DeleteDC()
            return base64_str
        except Exception: return None

    async def get_processes(self) -> List[ProcessInfo]:
        """List active processes with system metrics."""
        return await asyncio.to_thread(self._get_sync_processes)

    def _get_sync_processes(self) -> List[ProcessInfo]:
        processes_data = []
        psutil.cpu_percent(interval=0.1)
        attrs = ["pid", "name", "username", "cpu_percent", "memory_info"]
        if IS_WINDOWS_ICON_SUPPORT: attrs.append("exe")

        for proc in psutil.process_iter(attrs=attrs):
            try:
                p = proc.info
                if not p.get("name"): continue
                icon = self._get_icon_base64(p["exe"]) if IS_WINDOWS_ICON_SUPPORT and p.get("exe") else None
                mem = round(p["memory_info"].rss / (1024 * 1024), 2) if p.get("memory_info") else 0.0
                cpu = p.get("cpu_percent") or 0.0
                processes_data.append(ProcessInfo(
                    pid=p["pid"], name=p["name"], username=p.get("username", "N/A"),
                    cpu_percent=round(cpu, 2), memory_mb=mem, icon_base64=icon
                ))
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess): continue
            except Exception: continue
        return processes_data

    async def kill_process(self, pid: int) -> str:
        """Kill process by PID."""
        try:
            proc = psutil.Process(pid)
            name = proc.name()
            proc.kill()
            return f"Process {pid} ({name}) terminated."
        except psutil.NoSuchProcess: raise ValueError(f"Process {pid} not found.")
        except psutil.AccessDenied: raise PermissionError(f"Access denied for process {pid}.")

# Global instance
process_service = ProcessService()
