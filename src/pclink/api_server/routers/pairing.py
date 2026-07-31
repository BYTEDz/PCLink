# src/pclink/api_server/routers/pairing.py
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...core.constants import CERT_FILE
from ...core.device_manager import device_manager
from ...core.utils import get_cert_fingerprint
from ...core.validators import ValidationError
from ...services.pairing_service import pairing_service

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
    client_ip = request.client.host if request.client else "127.0.0.1"

    # Extract decoupled callbacks and objects from app.state
    ui_manager = getattr(request.app.state, "ui_manager", None)
    controller = getattr(request.app.state, "controller", None)
    tray = getattr(request.app.state, "tray_manager", None)

    ui_broadcaster = ui_manager.broadcast if ui_manager else None
    has_active_ui_connections = bool(ui_manager and ui_manager.active_connections)
    tray_notifier = tray.show_pairing_notification if tray else None
    web_ui_url = (
        controller.get_web_ui_url()
        if (controller and hasattr(controller, "get_web_ui_url"))
        else None
    )

    try:
        result = await pairing_service.handle_pairing_request(
            device_name=payload.device_name,
            client_ip=client_ip,
            device_id=payload.device_id,
            device_fingerprint=payload.device_fingerprint,
            client_version=payload.client_version,
            platform_name=payload.platform,
            hardware_id=payload.hardware_id,
            ui_broadcaster=ui_broadcaster,
            has_active_ui_connections=has_active_ui_connections,
            tray_notifier=tray_notifier,
            web_ui_url=web_ui_url,
        )

        status = result.get("status")
        if status == "approved":
            return result
        elif status == "denied":
            raise HTTPException(status_code=403, detail="PAIRING_DENIED")
        elif status == "timeout":
            raise HTTPException(status_code=408, detail="PAIRING_TIMEOUT")
        else:
            raise HTTPException(status_code=403, detail="PAIRING_FAILED")

    except ValidationError as e:
        log.warning(f"Registration validation error during pairing: {e}")
        raise HTTPException(status_code=403, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error completing device registration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Device registration failed: {e}")


@mobile_router.post("/reconnect")
async def pairing_reconnect(request: Request, payload: ReconnectPayload):
    """Silent reconnect for already-paired devices (no UI approval needed)."""
    api_key = request.headers.get("x-api-key") or request.headers.get("X-Api-Key")
    if not api_key:
        raise HTTPException(status_code=401, detail="MISSING_API_KEY")

    try:
        device = device_manager.get_device_by_api_key(api_key)
    except Exception as e:
        log.error(f"Error looking up device by api_key during reconnect: {e}")
        raise HTTPException(status_code=500, detail="Database lookup error")

    if not device:
        raise HTTPException(status_code=401, detail="INVALID_API_KEY")
    if not device.is_approved:
        raise HTTPException(status_code=403, detail="DEVICE_NOT_APPROVED")

    client_ip = request.client.host if request.client else "127.0.0.1"
    device_manager.update_device_ip(device.device_id, client_ip)
    device_manager.update_device_last_seen(device.device_id)

    log.info(f"Silent reconnect: device '{device.device_name}' from {client_ip}")
    return {
        "status": "ok",
        "device_id": device.device_id,
        "cert_fingerprint": get_cert_fingerprint(CERT_FILE),
    }


@mobile_router.post("/ip-change")
async def notify_ip_change(request: Request, payload: IpChangePayload):
    """Device notifies server of its own IP change (informational)."""
    api_key = request.headers.get("x-api-key") or request.headers.get("X-Api-Key")
    if not api_key:
        raise HTTPException(status_code=401, detail="MISSING_API_KEY")

    try:
        device = device_manager.get_device_by_api_key(api_key)
    except Exception as e:
        log.error(f"Error looking up device by api_key during ip-change: {e}")
        raise HTTPException(status_code=500, detail="Database lookup error")

    if not device or not device.is_approved:
        raise HTTPException(status_code=403, detail="UNAUTHORIZED")

    new_ip = request.client.host if request.client else payload.new_ip
    device_manager.update_device_ip(device.device_id, new_ip)
    log.info(
        f"IP change logged for '{device.device_name}': {payload.old_ip} → {new_ip}"
    )
    return {"status": "ok"}


@mgmt_router.post("/approve")
async def approve_pairing(request: Request, pairing_id: Optional[str] = None):
    """Signal approval for a pending pairing request (triggered by Web UI or CLI)."""
    if pairing_id is None:
        try:
            data = await request.json()
            pairing_id = data.get("pairing_id")
        except Exception:
            pass

    if pairing_id is None:
        pairing_id = request.query_params.get("pairing_id")

    if pairing_id and pairing_service.approve_pairing(pairing_id):
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

    if pairing_id and pairing_service.deny_pairing(pairing_id):
        return {"status": "success"}

    raise HTTPException(status_code=404, detail="Request not found or ID missing")
