# src/pclink/services/pairing_service.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import logging
import uuid
from typing import Any, Dict, List, Optional

from ..core import constants
from ..core.config import config_manager
from ..core.device_manager import device_manager
from ..core.utils import get_cert_fingerprint

log = logging.getLogger(__name__)


class PairingService:
    """Business logic for device pairing, hardware ID re-authentication, and state management."""

    def __init__(self):
        self.pairing_events: Dict[str, asyncio.Event] = {}
        self.pairing_results: Dict[str, dict] = {}

    def get_pending_requests(self) -> List[Dict[str, Any]]:
        """List all currently pending pairing requests."""
        pending = []
        for pid, data in self.pairing_results.items():
            pending.append(
                {
                    "pairing_id": pid,
                    "device_name": data.get("device_name"),
                    "ip": data.get("ip"),
                    "platform": data.get("platform"),
                }
            )
        return pending

    async def handle_pairing_request(
        self,
        device_name: str,
        client_ip: str,
        device_id: Optional[str] = None,
        device_fingerprint: Optional[str] = None,
        client_version: Optional[str] = None,
        platform_name: Optional[str] = None,
        hardware_id: Optional[str] = None,
        app_state: Any = None,
    ) -> Dict[str, Any]:
        """Handles incoming pairing requests from mobile devices, including hardware ID re-auth."""

        # 1. Hardware ID re-auth check (app reinstall path)
        if hardware_id:
            allow_hw_reauth = config_manager.get("allow_hardware_id_reauth", True)
            if allow_hw_reauth:
                try:
                    for existing in device_manager.get_approved_devices():
                        if existing.hardware_id and existing.hardware_id == hardware_id:
                            log.info(
                                f"hardware_id re-auth: device '{existing.device_name}' "
                                f"matched by hardware_id, issuing existing api_key"
                            )
                            existing.device_name = device_name
                            existing.platform = platform_name or existing.platform
                            existing.client_version = (
                                client_version or existing.client_version
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

        # 2. Resolve device_id: prefer explicit, fall back to hardware_id, then random UUID
        resolved_device_id = device_id or hardware_id or str(uuid.uuid4())
        pairing_id = str(uuid.uuid4())

        # 3. State setup
        self.pairing_events[pairing_id] = asyncio.Event()
        self.pairing_results[pairing_id] = {
            "approved": False,
            "user_decided": False,
            "device_name": device_name,
            "ip": client_ip,
            "platform": platform_name,
        }

        # 4. Notify Web UI (Browser)
        if app_state and hasattr(app_state, "ui_manager"):
            try:
                await app_state.ui_manager.broadcast(
                    {
                        "type": "pairing_request",
                        "data": {
                            "pairing_id": pairing_id,
                            "device_name": device_name,
                            "ip": client_ip,
                            "platform": platform_name,
                            "hardware_id": hardware_id,
                        },
                    }
                )
            except Exception as e:
                log.error(f"Error broadcasting pairing request to Web UI: {e}")

            # 5. Tray Notification if no active browser tab
            if not app_state.ui_manager.active_connections:
                try:
                    controller = getattr(app_state, "controller", None)
                    tray = getattr(app_state, "tray_manager", None)
                    if tray is not None and controller is not None:
                        web_ui_url = controller.get_web_ui_url()
                        asyncio.get_event_loop().run_in_executor(
                            None,
                            tray.show_pairing_notification,
                            device_name,
                            web_ui_url,
                        )
                except Exception as _e:
                    log.debug(f"Pairing notification skipped: {_e}")

        # 6. Wait for UI / CLI approval (30s timeout)
        try:
            await asyncio.wait_for(self.pairing_events[pairing_id].wait(), timeout=30.0)
            if self.pairing_results.get(pairing_id, {}).get("approved"):
                device = device_manager.register_device(
                    device_id=resolved_device_id,
                    device_name=device_name,
                    device_fingerprint=device_fingerprint or "",
                    platform=platform_name or "",
                    client_version=client_version or "",
                    current_ip=client_ip,
                    hardware_id=hardware_id or "",
                )

                device_manager.approve_device(resolved_device_id)

                return {
                    "status": "approved",
                    "api_key": device.api_key,
                    "cert_fingerprint": get_cert_fingerprint(constants.CERT_FILE),
                }

            return {"status": "denied"}

        except asyncio.TimeoutError:
            return {"status": "timeout"}
        finally:
            self.pairing_events.pop(pairing_id, None)
            self.pairing_results.pop(pairing_id, None)

    def approve_pairing(self, pairing_id: str) -> bool:
        """Signals approval for a pending pairing request."""
        if pairing_id and pairing_id in self.pairing_results:
            self.pairing_results[pairing_id]["approved"] = True
            self.pairing_results[pairing_id]["user_decided"] = True
            if event := self.pairing_events.get(pairing_id):
                event.set()
            return True
        return False

    def deny_pairing(self, pairing_id: str) -> bool:
        """Signals rejection for a pending pairing request."""
        if pairing_id and pairing_id in self.pairing_results:
            self.pairing_results[pairing_id]["approved"] = False
            self.pairing_results[pairing_id]["user_decided"] = True
            if event := self.pairing_events.get(pairing_id):
                event.set()
            return True
        return False


pairing_service = PairingService()
