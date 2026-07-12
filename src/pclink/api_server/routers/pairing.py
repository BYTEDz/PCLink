# src/pclink/api_server/routers/pairing.py
import asyncio
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...core import constants
from ...core.config import config_manager
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


class ReconnectPayload(BaseModel):
    device_id: Optional[str] = None
    device_fingerprint: Optional[str] = None
    reconnection: bool = True


class IpChangePayload(BaseModel):
    device_id: str
    old_ip: str
    new_ip: str


@mobile_router.post("/request")
async def pairing_request(request: Request, payload: PairingRequestPayload):
    """Handle incoming pairing requests from mobile devices."""
    results = getattr(request.app.state, "pairing_results", {})
    events = getattr(request.app.state, "pairing_events", {})

    client_ip = request.client.host

    # --- hardware_id-based re-auth (app reinstall path) ---
    # If hw_id matches an existing approved device and setting allows it,
    # skip UI dialog and return the existing api_key directly.
    if payload.hardware_id:
        allow_hw_reauth = config_manager.get("allow_hardware_id_reauth", True)
        if allow_hw_reauth:
            for existing in device_manager.get_approved_devices():
                if existing.hardware_id and existing.hardware_id == payload.hardware_id:
                    log.info(
                        f"hardware_id re-auth: device '{existing.device_name}' "
                        f"matched by hardware_id, issuing existing api_key"
                    )
                    # Update metadata in case name/version changed
                    existing.device_name = payload.device_name
                    existing.platform = payload.platform or existing.platform
                    existing.client_version = (
                        payload.client_version or existing.client_version
                    )
                    existing.current_ip = client_ip
                    device_manager._save_device(existing)
                    return {
                        "status": "approved",
                        "api_key": existing.api_key,
                        "cert_fingerprint": get_cert_fingerprint(constants.CERT_FILE),
                    }

    # --- Resolve device_id: prefer explicit, fall back to hardware_id, then random ---
    resolved_device_id = payload.device_id or payload.hardware_id or str(uuid.uuid4())

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

    # 3. Wait for UI Response (30s timeout)
    try:
        await asyncio.wait_for(events[pairing_id].wait(), timeout=30.0)
        if results[pairing_id]["approved"]:
            # 4. Register/update device
            device = device_manager.register_device(
                device_id=resolved_device_id,
                device_name=payload.device_name,
                device_fingerprint=payload.device_fingerprint or "",
                platform=payload.platform or "",
                client_version=payload.client_version or "",
                current_ip=client_ip,
                hardware_id=payload.hardware_id or "",
            )

            # Auto-approve as manual confirmation just happened via UI
            device_manager.approve_device(resolved_device_id)

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


@mobile_router.post("/reconnect")
async def pairing_reconnect(request: Request, payload: ReconnectPayload):
    """Silent reconnect for already-paired devices (no UI approval needed).

    Client sends its existing api_key via x-api-key header. Server validates
    and updates IP. Returns 200 if device is still approved, 401/403 otherwise.
    """
    api_key = request.headers.get("x-api-key") or request.headers.get("X-Api-Key")
    if not api_key:
        raise HTTPException(status_code=401, detail="MISSING_API_KEY")

    device = device_manager.get_device_by_api_key(api_key)
    if not device:
        raise HTTPException(status_code=401, detail="INVALID_API_KEY")
    if not device.is_approved:
        raise HTTPException(status_code=403, detail="DEVICE_NOT_APPROVED")

    client_ip = request.client.host
    device_manager.update_device_ip(device.device_id, client_ip)
    device_manager.update_device_last_seen(device.device_id)

    log.info(f"Silent reconnect: device '{device.device_name}' from {client_ip}")
    return {
        "status": "ok",
        "device_id": device.device_id,
        "cert_fingerprint": get_cert_fingerprint(constants.CERT_FILE),
    }


@mobile_router.post("/ip-change")
async def notify_ip_change(request: Request, payload: IpChangePayload):
    """Device notifies server of its own IP change (informational)."""
    api_key = request.headers.get("x-api-key") or request.headers.get("X-Api-Key")
    if not api_key:
        raise HTTPException(status_code=401, detail="MISSING_API_KEY")

    device = device_manager.get_device_by_api_key(api_key)
    if not device or not device.is_approved:
        raise HTTPException(status_code=403, detail="UNAUTHORIZED")

    new_ip = request.client.host  # trust actual socket addr, not payload
    device_manager.update_device_ip(device.device_id, new_ip)
    log.info(
        f"IP change logged for '{device.device_name}': {payload.old_ip} → {new_ip}"
    )
    return {"status": "ok"}


@mgmt_router.post("/approve")
async def approve_pairing(request: Request, pairing_id: Optional[str] = None):
    """Signal approval for a pending pairing request (triggered by Web UI or CLI)."""
    # 1. Try to get pairing_id from JSON body
    if pairing_id is None:
        try:
            data = await request.json()
            pairing_id = data.get("pairing_id")
        except Exception:
            pass

    # 2. Try to get from query params if still None
    if pairing_id is None:
        pairing_id = request.query_params.get("pairing_id")

    results = getattr(request.app.state, "pairing_results", {})
    events = getattr(request.app.state, "pairing_events", {})

    if pairing_id and pairing_id in results:
        results[pairing_id]["approved"] = True
        results[pairing_id]["user_decided"] = True
        if event := events.get(pairing_id):
            event.set()
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="Request not found or ID missing")


@mgmt_router.post("/deny")
async def deny_pairing(request: Request, pairing_id: Optional[str] = None):
    """Signal rejection for a pending pairing request (triggered by Web UI or CLI)."""
    if pairing_id is None:
        try:
            data = await request.json()
            pairing_id = data.get("pairing_id")
        except Exception:
            pass

    if pairing_id is None:
        pairing_id = request.query_params.get("pairing_id")

    results = getattr(request.app.state, "pairing_results", {})
    events = getattr(request.app.state, "pairing_events", {})

    if pairing_id and pairing_id in results:
        results[pairing_id]["approved"] = False
        results[pairing_id]["user_decided"] = True
        if event := events.get(pairing_id):
            event.set()
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="Request not found or ID missing")
