# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

from typing import Any, Dict, List

from fastapi import APIRouter

from ..core.version import __version__
from ..services import media_service, system_service

router = APIRouter()


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
