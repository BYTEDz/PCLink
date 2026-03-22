# src/pclink/api_server/routers/pairing.py
import asyncio
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...core import constants
from ...core.device_manager import device_manager
from ...core.utils import get_cert_fingerprint
from ..ws_manager import ui_manager

log = logging.getLogger(__name__)
mgmt_router = APIRouter(prefix="/ui/pairing", tags=["Pairing Management"])
mobile_router = APIRouter(prefix="/pairing", tags=["Mobile Pairing"])


class PairingRequestPayload(BaseModel):
    device_name: str
    device_id: Optional[str] = None
    device_fingerprint: Optional[str] = None
    client_version: Optional[str] = None
    platform: Optional[str] = None
    hardware_id: Optional[str] = None


@mobile_router.post("/request")
async def pairing_request(request: Request, payload: PairingRequestPayload):
    """Handle incoming pairing requests from mobile devices."""
    results = getattr(request.app.state, "pairing_results", {})
    events = getattr(request.app.state, "pairing_events", {})

    client_ip = request.client.host
    pairing_id = str(uuid.uuid4())

    # 1. State setup
    events[pairing_id] = asyncio.Event()
    results[pairing_id] = {
        "approved": False,
        "user_decided": False,
        "device_name": payload.device_name,
        "ip": client_ip,
        "platform": payload.platform,
    }

    # 2. Notify Web UI (Browser)
    await ui_manager.broadcast(
        {
            "type": "pairing_request",
            "data": {
                "pairing_id": pairing_id,
                "device_name": payload.device_name,
                "ip": client_ip,
                "platform": payload.platform,
                "hardware_id": payload.hardware_id,
            },
        }
    )

    # 3. Wait for UI Response (60s timeout)
    try:
        await asyncio.wait_for(events[pairing_id].wait(), timeout=60.0)
        if results[pairing_id]["approved"]:
            # 4. Generate device-specific identities
            device_id = payload.device_id or str(uuid.uuid4())
            device = device_manager.register_device(
                device_id=device_id,
                device_name=payload.device_name,
                device_fingerprint=payload.device_fingerprint or "",
                platform=payload.platform or "",
                client_version=payload.client_version or "",
                current_ip=client_ip,
                hardware_id=payload.hardware_id or "",
            )

            # Auto-approve as manual confirmation just happened via UI
            device_manager.approve_device(device_id)

            return {
                "status": "approved",
                "api_key": device.api_key,
                "cert_fingerprint": get_cert_fingerprint(constants.CERT_FILE),
            }

        raise HTTPException(status_code=403, detail="PAIRING_DENIED")

    except asyncio.TimeoutError:
        raise HTTPException(status_code=408, detail="PAIRING_TIMEOUT")
    finally:
        # Cleanup
        events.pop(pairing_id, None)
        results.pop(pairing_id, None)


@mgmt_router.post("/approve")
async def approve_pairing(request: Request):
    """Signal approval for a pending pairing request (triggered by Web UI)."""
    data = await request.json()
    pairing_id = data.get("pairing_id")
    results = getattr(request.app.state, "pairing_results", {})
    events = getattr(request.app.state, "pairing_events", {})

    if pairing_id in results:
        results[pairing_id]["approved"] = True
        results[pairing_id]["user_decided"] = True
        if event := events.get(pairing_id):
            event.set()
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="Request not found")


@mgmt_router.post("/deny")
async def deny_pairing(request: Request):
    """Signal rejection for a pending pairing request (triggered by Web UI)."""
    data = await request.json()
    pairing_id = data.get("pairing_id")
    results = getattr(request.app.state, "pairing_results", {})
    events = getattr(request.app.state, "pairing_events", {})

    if pairing_id in results:
        results[pairing_id]["approved"] = False
        results[pairing_id]["user_decided"] = True
        if event := events.get(pairing_id):
            event.set()
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="Request not found")
