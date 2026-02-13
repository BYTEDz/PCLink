# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

from fastapi import APIRouter
from typing import Dict, Any, List
from ..services import system_service, media_service
from ..core.version import __version__

router = APIRouter()


@router.get("/ping")
async def ping():
    """Lightweight endpoint for heartbeat checks."""
    from ..services.discovery_service import DiscoveryService
    return {
        "status": "ok", 
        "version": __version__,
        "server_id": DiscoveryService.generate_server_id()
    }


@router.get("/heartbeat")
async def heartbeat():
    """Ultra-lightweight heartbeat for status checks."""
    import time
    from ..services.discovery_service import DiscoveryService
    return {
        "status": "ok", 
        "time": time.time(),
        "server_id": DiscoveryService.generate_server_id()
    }


@router.get("/system")
async def get_system_info() -> Dict[str, Any]:
    """Provides general system information."""
    return await system_service.get_system_info()


@router.get("/disks")
async def get_disk_info() -> Dict[str, List[Dict[str, Any]]]:
    """Provides information about all mounted disk partitions."""
    return await system_service.get_disks_info()


@router.get("/media")
async def get_media_info() -> Dict[str, Any]:
    """Provides information about the currently playing media."""
    return await media_service.get_media_info()


@router.get("/version")
async def get_server_version():
    """Returns the current version of the PCLink server."""
    from ..services.discovery_service import DiscoveryService
    return {
        "version": __version__,
        "server_id": DiscoveryService.generate_server_id()
    }