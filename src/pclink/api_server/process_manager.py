# src/pclink/api_server/process_manager.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
from typing import Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services.process_service import process_service, ProcessInfo

log = logging.getLogger(__name__)

class KillPayload(BaseModel):
    """Payload model for the kill process endpoint."""
    pid: int

router = APIRouter()

@router.get("/processes", response_model=List[ProcessInfo])
async def get_running_processes() -> List[ProcessInfo]:
    """List active processes with system metrics."""
    try:
        return await process_service.get_processes()
    except Exception as e:
        log.error(f"Failed to fetch processes: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch processes")

@router.post("/processes/kill")
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
        raise HTTPException(status_code=500, detail=str(e))