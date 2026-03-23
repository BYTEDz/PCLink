# src/pclink/api_server/routers/devices.py
import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query, Request

from ...core.device_manager import device_manager
from ...core.config import config_manager
from ..ws_manager import mobile_manager
from .dependencies import WEB_AUTH

log = logging.getLogger(__name__)
router = APIRouter(prefix="/ui/devices", tags=["Devices"], dependencies=[WEB_AUTH])


@router.get("")
async def get_connected_devices(request: Request):
    """List all paired devices and their online status."""
    devices = []

    # 1. Fetch approved devices from DB
    for device in device_manager.get_all_devices():
        if device.is_approved:
            devices.append(
                {
                    "id": device.device_id,
                    "name": device.device_name,
                    "ip": device.current_ip,
                    "platform": device.platform,
                    "client_version": device.client_version,
                    "last_seen": device.last_seen.isoformat(),
                    "permissions": ",".join(device.permissions),
                    "is_approved": True,
                }
            )

    return {"devices": devices}


@router.post("/remove-all")
async def remove_all_devices(request: Request):
    """Revoke access for all approved devices and purge connection cache."""
    connected_devices = getattr(request.app.state, "connected_devices", {})
    try:
        removed_count = 0
        for device in device_manager.get_all_devices():
            if device.is_approved:
                device_manager.revoke_device(device.device_id)
                await mobile_manager.disconnect_device(device.device_id)
                removed_count += 1
        connected_devices.clear()
        log.info(f"Removed {removed_count} devices via web UI")
        return {"status": "success", "removed_count": removed_count}
    except Exception as e:
        log.error(f"Failed to remove all devices: {e}")
        raise HTTPException(status_code=500, detail="Failed to remove devices")


@router.post("/revoke")
async def revoke_single_device(
    request: Request,
    device_id: str = Query(
        ..., description="The ID of the device to revoke access for"
    ),
):
    """Revoke specific device access and force disconnect."""
    connected_devices = getattr(request.app.state, "connected_devices", {})
    try:
        device = device_manager.get_device_by_id(device_id)
        device_ip = device.current_ip if device else None

        if device_manager.revoke_device(device_id):
            await mobile_manager.disconnect_device(device_id)

            # Cleanup legacy IP-based cache
            for ip, data in list(connected_devices.items()):
                cached_id = data.get("device_id")
                if cached_id == device_id or (
                    device_ip and ip == device_ip and not cached_id
                ):
                    del connected_devices[ip]

            log.info(f"Device {device_id} revoked via web UI.")
            return {"status": "success", "message": "Device access revoked"}

        raise HTTPException(status_code=404, detail="Device not found")
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to revoke device {device_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ban")
async def ban_device_permanently(
    device_id: str = Query(...), reason: str = Query("Manual ban")
):
    """Permanently ban hardware ID and revoke current access."""
    try:
        device = device_manager.get_device_by_id(device_id)
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")

        hardware_id = device.hardware_id
        if not hardware_id:
            device_manager.revoke_device(device_id)
            await mobile_manager.disconnect_device(device_id)
            return {
                "status": "success",
                "message": "Device revoked; HW ban skipped (no ID).",
            }

        if device_manager.ban_hardware(hardware_id, reason):
            await mobile_manager.disconnect_device(device_id)
            return {
                "status": "success",
                "message": f"Device {device.device_name} (HW: {hardware_id}) banned.",
            }

        raise HTTPException(status_code=500, detail="Internal failure during ban")
    except Exception as e:
        log.error(f"Failed to ban device {device_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/blacklist")
async def get_banned_list():
    """List all hardware-banned IDs."""
    return {"blacklist": device_manager.get_blacklist()}


@router.post("/unban")
async def unban_hardware_id(hardware_id: str = Query(...)):
    """Remove hardware ID from blacklist."""
    if device_manager.unban_hardware(hardware_id):
        return {"status": "success", "message": f"Hardware ID {hardware_id} unbanned."}
    raise HTTPException(status_code=404, detail="Hardware ID not found in blacklist.")


@router.get("/settings/defaults/permissions")
async def get_default_permissions():
    """Retrieve the list of permissions assigned to new devices by default."""
    return {"permissions": config_manager.get("default_device_permissions", [])}


@router.post("/settings/defaults/permissions")
async def update_default_permissions(payload: Dict[str, Any]):
    """Update the global default permission set."""
    perms = payload.get("permissions", [])
    config_manager.set("default_device_permissions", perms)
    return {"status": "success"}


@router.post("/{device_id}/permissions")
async def update_device_permissions(device_id: str, payload: Dict[str, Any]):
    """Update specific permissions for a single device (Web UI toggles)."""
    perm = payload.get("permission")
    enabled = payload.get("enabled", False)

    device = device_manager.get_device_by_id(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    current_perms = set(device.permissions)
    if enabled:
        current_perms.add(perm)
    else:
        current_perms.discard(perm)
    device.permissions = list(current_perms)
    device_manager._save_device(device)

    # Notify device
    await mobile_manager.send_to_device(
        device_id,
        {
            "type": "UPDATE_STATE",
            "services": config_manager.get("services", {}),
            "permissions": device.permissions,
        },
    )
    return {"status": "success", "permissions": device.permissions}


@router.post("/{device_id}/permissions/bulk")
async def update_device_permissions_bulk(device_id: str, payload: Dict[str, Any]):
    """Update all permissions for a single device in bulk (CLI/Roles)."""
    perms = payload.get("permissions", [])
    device = device_manager.get_device_by_id(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    device.permissions = perms
    device_manager._save_device(device)

    log.info(f"Updated bulk permissions for {device.device_name}")

    # Proactively notify the device via WebSocket
    await mobile_manager.send_to_device(
        device_id,
        {
            "type": "UPDATE_STATE",
            "services": config_manager.get("services", {}),
            "permissions": device.permissions,
        },
    )

    return {"status": "success", "permissions": device.permissions}
