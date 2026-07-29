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
from ...core.validators import ValidationError
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

    client_ip = request.client.host if request.client else "127.0.0.1"

    # --- hardware_id-based re-auth (app reinstall path) ---
    if payload.hardware_id:
        allow_hw_reauth = config_manager.get("allow_hardware_id_reauth", True)
        if allow_hw_reauth:
            try:
                for existing in device_manager.get_approved_devices():
                    if (
                        existing.hardware_id
                        and existing.hardware_id == payload.hardware_id
                    ):
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
                            "cert_fingerprint": get_cert_fingerprint(
                                constants.CERT_FILE
                            ),
                        }
            except Exception as e:
                log.error(f"Hardware ID re-auth check error: {e}", exc_info=True)

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
    try:
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
    except Exception as e:
        log.error(f"Error broadcasting pairing request to Web UI: {e}")

    # 3. If no browser tab is open, fire a tray notification so the user
    #    knows to open the web UI and approve the request.
    if not ui_manager.active_connections:
        try:
            controller = getattr(request.app.state, "controller", None)
            tray = getattr(request.app.state, "tray_manager", None)
            if tray is not None and controller is not None:
                web_ui_url = controller.get_web_ui_url()
                # run in executor — notifier calls may block briefly
                asyncio.get_event_loop().run_in_executor(
                    None,
                    tray.show_pairing_notification,
                    payload.device_name,
                    web_ui_url,
                )
        except Exception as _e:
            log.debug(f"Pairing notification skipped: {_e}")

    # 4. Wait for UI Response (30s timeout)
    try:
        await asyncio.wait_for(events[pairing_id].wait(), timeout=30.0)
        if results.get(pairing_id, {}).get("approved"):
            try:
                # Register/update device
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
            except ValidationError as e:
                log.warning(f"Registration validation error during pairing: {e}")
                raise HTTPException(status_code=403, detail=str(e))
            except Exception as e:
                log.error(f"Error completing device registration: {e}", exc_info=True)
                raise HTTPException(
                    status_code=500, detail=f"Device registration failed: {e}"
                )

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
        "cert_fingerprint": get_cert_fingerprint(constants.CERT_FILE),
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
