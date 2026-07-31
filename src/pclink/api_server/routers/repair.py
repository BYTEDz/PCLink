# src/pclink/api_server/routers/repair.py
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.repair_service import repair_service

router = APIRouter(tags=["Repair Center"])


class RepairRequest(BaseModel):
    action: Optional[str] = None
    password: Optional[str] = None
    new_port: Optional[int] = None


@router.get("/diagnose")
async def diagnose():
    """Run all diagnostic checks concurrently."""
    return await repair_service.run_diagnostics()


@router.get("/causes")
async def detect_causes():
    """Run root-cause analysis to detect server pressure or reachability issues."""
    return repair_service.detect_instability_causes()


@router.post("/auto-heal")
async def auto_heal():
    """Execute automated self-healing procedures."""
    return repair_service.auto_heal()


@router.post("/force")
async def force_repair():
    """Force a factory reset of config and database."""
    return repair_service.force_repair()


@router.post("/run/{issue_id}")
async def run_repair(issue_id: str, payload: RepairRequest = None):
    """Run a specific repair action."""
    if issue_id == "db":
        return repair_service.fix_db()
    elif issue_id == "config":
        return repair_service.fix_config()
    elif issue_id == "firewall":
        password = payload.password if payload else None
        return repair_service.fix_firewall(password)
    elif issue_id == "port":
        if not payload or not payload.action:
            raise HTTPException(
                status_code=400,
                detail="Action required for port repair (change_port/kill_process).",
            )
        return repair_service.fix_port(payload.action, payload.new_port)
    else:
        raise HTTPException(status_code=400, detail="Invalid issue ID.")
