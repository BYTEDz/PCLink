# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
from fastapi import APIRouter, HTTPException
from ..services import system_service

router = APIRouter()
log = logging.getLogger(__name__)


@router.post("/power/{command}")
async def power_command(command: str, hybrid: bool = True):
    """Handles power commands via SystemService."""
    try:
        await system_service.power_command(command, hybrid)
        return {"status": "command sent"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.error(f"Power command error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/volume")
async def get_volume():
    """Gets the current master volume level and mute status."""
    try:
        return await system_service.get_volume()
    except Exception as e:
        log.error(f"Failed to get volume: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get volume: {e}")


@router.post("/volume/set/{level}")
async def set_volume(level: int):
    """Sets the master volume level (0-100)."""
    try:
        await system_service.set_volume(level)
        return {"status": "volume set"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error(f"Failed to set volume: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to set volume: {e}")


@router.get("/wake-on-lan/info")
async def get_wake_on_lan_info():
    """Retrieves Wake-on-LAN capability and MAC address."""
    return await system_service.get_wol_info()