# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import psutil
from fastapi import APIRouter
from typing import Dict, Any, List

# Import necessary utility functions and classes.
from .services import NetworkMonitor, get_media_info_data, get_system_info_data
from ..core.version import __version__

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


@router.get("/version")
async def get_server_version():
    """Returns the current version of the PCLink server."""
    return {"version": __version__}