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
from typing import Dict, Any, List

# Import necessary utility functions and classes.
from .services import NetworkMonitor, get_media_info_data, get_system_info_data

router = APIRouter()
# Initialize the NetworkMonitor to track network speed.
network_monitor = NetworkMonitor()


def _format_bytes(byte_count: int) -> str:
    """
    Formats a byte count into a human-readable string (e.g., '1.5 GB', '500 MB').

    Args:
        byte_count: The number of bytes to format.

    Returns:
        A string representing the byte count in GB or MB.
    """
    if byte_count >= 1024**3:
        # Format as Gigabytes with one decimal place if count is large enough.
        return f"{byte_count / (1024**3):.1f} GB"
    else:
        # Format as Megabytes with no decimal places otherwise.
        return f"{byte_count / (1024**2):.0f} MB"


@router.get("/system")
async def get_system_info() -> Dict[str, Any]:
    """
    Provides general system information.

    Includes OS details, CPU utilization and cores, RAM usage, and current network speed.

    Returns:
        A dictionary containing system information.
    """
    return await get_system_info_data(network_monitor)


@router.get("/disks")
async def get_disk_info() -> Dict[str, List[Dict[str, Any]]]:
    """
    Provides information about all mounted disk partitions.

    Filters out optical drives and partitions that are not ready.

    Returns:
        A dictionary containing a list of disk information objects.
    """
    disks_info: List[Dict[str, Any]] = []
    for part in psutil.disk_partitions():
        # Skip optical drives and partitions with no filesystem type (e.g., unmounted).
        if 'cdrom' in part.opts or part.fstype == '':
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disks_info.append({
                "device": part.mountpoint,  # Use mountpoint as the identifier.
                "total": _format_bytes(usage.total),
                "used": _format_bytes(usage.used),
                "free": _format_bytes(usage.free),
                "percent": int(usage.percent),
            })
        except (PermissionError, FileNotFoundError):
            # Ignore partitions that cannot be accessed due to permissions or being unavailable.
            continue
    return {"disks": disks_info}


@router.get("/media")
async def get_media_info() -> Dict[str, Any]:
    """
    Provides information about the currently playing media.

    Returns:
        A dictionary containing media playback details.
    """
    return await get_media_info_data()