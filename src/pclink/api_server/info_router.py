# filename: src/pclink/api_server/info_router.py
"""
PCLink - Remote PC Control Server - System Info API Module
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

import psutil
from fastapi import APIRouter

from .services import NetworkMonitor, get_media_info_data, get_system_info_data

router = APIRouter()
network_monitor = NetworkMonitor()

def _format_bytes(byte_count: int) -> str:
    """Formats bytes into a human-readable string (GB or MB)."""
    if byte_count >= 1024**3:
        # Format as Gigabytes with one decimal place
        return f"{byte_count / (1024**3):.1f} GB"
    else:
        # Format as Megabytes with no decimal places
        return f"{byte_count / (1024**2):.0f} MB"


@router.get("/system")
async def get_system_info():
    """Provides general system information like OS, CPU, RAM, and network speed."""
    return await get_system_info_data(network_monitor)


@router.get("/disks")
async def get_disk_info():
    """Provides information about all mounted disk partitions."""
    disks = []
    for part in psutil.disk_partitions():
        # Skip optical drives and other removable media that might not be ready
        if 'cdrom' in part.opts or part.fstype == '':
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disks.append({
                "device": part.mountpoint, # Use mountpoint as the primary identifier
                "total": _format_bytes(usage.total),
                "used": _format_bytes(usage.used),
                "free": _format_bytes(usage.free),
                "percent": int(usage.percent),
            })
        except (PermissionError, FileNotFoundError):
            continue
    return {"disks": disks}


@router.get("/media")
async def get_media_info():
    """Provides information about the currently playing media."""
    return await get_media_info_data()