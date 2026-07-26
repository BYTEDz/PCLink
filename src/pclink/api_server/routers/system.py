# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import gettext
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services import media_service, process_service, system_service
from ...services.process_service import ProcessInfo

log = logging.getLogger(__name__)
_ = gettext.gettext

system_router = APIRouter()
info_router = APIRouter()


class KillPayload(BaseModel):
    pid: int


# --- System Info Endpoints ---


@info_router.get("/system")
async def get_system_info() -> Dict[str, Any]:
    """Provides general system information."""
    return await system_service.get_system_info()


@info_router.get("/disks")
async def get_disk_info() -> Dict[str, List[Dict[str, Any]]]:
    """Provides information about all mounted disk partitions."""
    return await system_service.get_disks_info()


@info_router.get("/media")
async def get_media_info() -> Dict[str, Any]:
    """Provides information about the currently playing media."""
    return await media_service.get_media_info()


# --- Process Management Endpoints ---


@system_router.get("/processes", response_model=List[ProcessInfo])
async def get_running_processes() -> List[ProcessInfo]:
    """List active processes with system metrics."""
    try:
        return await process_service.get_processes()
    except Exception as e:
        log.error(f"Failed to fetch processes: {e}")
        raise HTTPException(
            status_code=500, detail=_("Failed to fetch processes: {}").format(e)
        )


@system_router.post("/processes/kill")
async def kill_process(payload: KillPayload) -> Dict[str, str]:
    """Kill process by PID."""
    try:
        msg = await process_service.kill_process(payload.pid)
        return {"status": "success", "message": msg}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        log.error(f"Failed to kill process {payload.pid}: {e}")
        raise HTTPException(
            status_code=500, detail=_("Failed to kill process: {}").format(e)
        )


# --- Power, Volume, and WOL Endpoints ---


@system_router.post("/power/{command}")
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


@system_router.get("/volume")
async def get_volume():
    """Gets the current master volume level and mute status."""
    try:
        return await system_service.get_volume()
    except Exception as e:
        log.error(f"Failed to get volume: {e}")
        raise HTTPException(
            status_code=500, detail=_("Failed to get volume: {}").format(e)
        )


@system_router.post("/volume/set/{level}")
async def set_volume(level: int):
    """Sets the master volume level (0-100)."""
    try:
        await system_service.set_volume(level)
        return {"status": "volume set"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error(f"Failed to set volume: {e}")
        raise HTTPException(
            status_code=500, detail=_("Failed to set volume: {}").format(e)
        )


@system_router.get("/wake-on-lan/info")
async def get_wake_on_lan_info():
    """Retrieves Wake-on-LAN capability and MAC address."""
    return await system_service.get_wol_info()
