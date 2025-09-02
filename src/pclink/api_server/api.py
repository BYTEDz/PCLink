# filename: src/pclink/api_server/api.py
"""
PCLink - Remote PC Control Server - Main API Module
Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published
by the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import (Depends, FastAPI, Header, HTTPException, Query, Request,
                     WebSocket, WebSocketDisconnect)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ..core import constants
from ..core.device_manager import device_manager
from ..core.state import api_signal_emitter
from ..core.utils import get_cert_fingerprint
from ..core.validators import ValidationError, validate_api_key
from .file_browser import download_router, router as file_browser_router, upload_router
from .info_router import router as info_router
from .input_router import router as input_router
from .media_router import router as media_router
from .process_manager import router as process_manager_router
from .services import (NetworkMonitor, button_map, get_media_info_data,
                       get_system_info_data, keyboard_controller,
                       mouse_controller)
from .system_router import router as system_router
from .terminal import create_terminal_router
from .utils_router import router as utils_router

log = logging.getLogger(__name__)

# --- Pydantic Models ---
class AnnouncePayload(BaseModel): name: str; local_ip: Optional[str] = None
class QrPayload(BaseModel): protocol: str; ip: str; port: int; apiKey: str; certFingerprint: Optional[str]
class PairingRequestPayload(BaseModel): device_name: str; device_id: Optional[str] = None; device_fingerprint: Optional[str] = None; client_version: Optional[str] = None; platform: Optional[str] = None

# --- Pairing State ---
pairing_events: Dict[str, asyncio.Event] = {}
pairing_results: Dict[str, dict] = {}

# --- WebSocket Command Handlers ---
def handle_mouse_command(data: Dict[str, Any]):
    action = data.get("action")
    try:
        button = button_map.get(data.get("button", "left"))
        if action == "move": mouse_controller.move(data.get("dx", 0), data.get("dy", 0))
        elif action == "click": mouse_controller.click(button, 1)
        elif action == "double_click": mouse_controller.click(button, 2)
        elif action == "down": mouse_controller.press(button)
        elif action == "up": mouse_controller.release(button)
        elif action == "scroll": mouse_controller.scroll(data.get("dx", 0), data.get("dy", 0))
    except Exception as e: log.error(f"Error executing mouse command '{action}': {e}")
def handle_keyboard_command(data: Dict[str, Any]):
    try:
        if text := data.get("text"):
            keyboard_controller.type(text)
        elif key_str := data.get("key"):
            from .services import get_key
            modifiers = data.get("modifiers", [])
            for mod_str in modifiers: keyboard_controller.press(get_key(mod_str))
            main_key = get_key(key_str)
            keyboard_controller.press(main_key); keyboard_controller.release(main_key)
            for mod_str in reversed(modifiers): keyboard_controller.release(get_key(mod_str))
    except Exception as e: log.error(f"Error executing keyboard command: {e}")

# --- WebSocket Connection Manager ---
class ConnectionManager:
    def __init__(self): self.active_connections: List[WebSocket] = []
    async def connect(self, websocket: WebSocket): await websocket.accept(); self.active_connections.append(websocket)
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections: self.active_connections.remove(websocket)
    async def broadcast(self, message: Dict[str, Any]):
        for connection in self.active_connections[:]:
            try: await connection.send_json(message)
            except Exception: self.disconnect(connection)

# --- FastAPI App Factory ---
def create_api_app(api_key: str, signal_emitter, connected_devices: Dict, allow_insecure_shell: bool) -> FastAPI:
    app = FastAPI(title="PCLink API", version="8.9.0", docs_url=None, redoc_url=None)
    manager = ConnectionManager()
    server_api_key = validate_api_key(api_key)
    network_monitor = NetworkMonitor()

    async def verify_api_key(x_api_key: str = Header(None), request: Request = None):
        if not x_api_key: raise HTTPException(status_code=403, detail="Missing API Key")
        try:
            if validate_api_key(x_api_key) == server_api_key: return True
        except ValidationError: pass
        device = device_manager.get_device_by_api_key(x_api_key)
        if not device or not device.is_approved: raise HTTPException(status_code=403, detail="Invalid API Key")
        if request and request.client:
            client_ip = request.client.host
            if device.current_ip != client_ip: device_manager.update_device_ip(device.device_id, client_ip)
            else: device_manager.update_device_last_seen(device.device_id)
        return True

    PROTECTED = Depends(verify_api_key)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    
    # Include all routers
    terminal_router = create_terminal_router(server_api_key, allow_insecure_shell)
    app.include_router(system_router, dependencies=[PROTECTED])
    app.include_router(file_browser_router, prefix="/files", dependencies=[PROTECTED])
    app.include_router(upload_router, prefix="/files/upload", dependencies=[PROTECTED])
    app.include_router(download_router, prefix="/files/download", dependencies=[PROTECTED])
    app.include_router(process_manager_router, prefix="/system", dependencies=[PROTECTED])
    app.include_router(info_router, prefix="/info", dependencies=[PROTECTED])
    app.include_router(input_router, prefix="/input", dependencies=[PROTECTED])
    app.include_router(media_router, prefix="/media", dependencies=[PROTECTED])
    app.include_router(utils_router, prefix="/utils", dependencies=[PROTECTED])
    app.include_router(terminal_router, prefix="/terminal")
    
    app.state.allow_insecure_shell = allow_insecure_shell
    app.state.api_key = server_api_key

    @app.on_event("startup")
    async def startup_event(): asyncio.create_task(broadcast_updates_task(manager, app.state, network_monitor))

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket, token: str = Query(None)):
        if not token: await websocket.close(code=1008, reason="Missing API Key"); return
        authenticated = False
        try:
            if validate_api_key(token) == server_api_key: authenticated = True
        except ValidationError: pass
        if not authenticated:
            device = device_manager.get_device_by_api_key(token)
            if device and device.is_approved: authenticated = True; device_manager.update_device_last_seen(device.device_id)
        if not authenticated: await websocket.close(code=1008, reason="Invalid API Key"); return
        await manager.connect(websocket)
        try:
            while True:
                data = await websocket.receive_json()
                if (msg_type := data.get("type")) == "mouse_control": handle_mouse_command(data)
                elif msg_type == "keyboard_control": handle_keyboard_command(data)
        except WebSocketDisconnect: pass
        except (json.JSONDecodeError, KeyError): pass
        finally: manager.disconnect(websocket)

    @app.post("/pairing/request")
    async def request_pairing(payload: PairingRequestPayload, request: Request):
        pairing_id = str(uuid.uuid4())
        try:
            event = asyncio.Event(); pairing_events[pairing_id] = event
            client_ip = request.client.host if request.client else "unknown"
            device_id = payload.device_id or str(uuid.uuid4())
            if not payload.device_name or not payload.device_name.strip(): raise HTTPException(status_code=400, detail="Device name is required.")
            device = device_manager.register_device(device_id=device_id, device_name=payload.device_name, device_fingerprint=payload.device_fingerprint or "", platform=payload.platform or "", client_version=payload.client_version or "", current_ip=client_ip)
            pairing_results[pairing_id] = {"device": device, "approved": False}
            api_signal_emitter.pairing_request.emit(pairing_id, payload.device_name, device_id)
            try: await asyncio.wait_for(event.wait(), timeout=60.0)
            except asyncio.TimeoutError: raise HTTPException(status_code=408, detail="Pairing request timed out.")
            if pairing_results.get(pairing_id, {}).get("approved", False):
                device_manager.approve_device(device.device_id)
                fingerprint = get_cert_fingerprint(constants.CERT_FILE)
                return {"api_key": device.api_key, "cert_fingerprint": fingerprint, "device_id": device.device_id}
            else:
                device_manager.revoke_device(device.device_id)
                raise HTTPException(status_code=403, detail="Pairing request denied by user.")
        finally:
            pairing_events.pop(pairing_id, None)
            pairing_results.pop(pairing_id, None)

    @app.get("/")
    def read_root(): return {"message": "PCLink API is running."}

    @app.get("/ping", dependencies=[PROTECTED])
    async def ping(): return {"status": "pong"}

    @app.get("/qr-payload", response_model=QrPayload, dependencies=[PROTECTED])
    async def get_qr_payload():
        fingerprint = get_cert_fingerprint(constants.CERT_FILE)
        return QrPayload(protocol="https", ip=app.state.host_ip, port=app.state.host_port, apiKey=app.state.api_key, certFingerprint=fingerprint)

    @app.post("/announce", dependencies=[PROTECTED])
    async def announce_device(request: Request, payload: AnnouncePayload):
        client_ip = request.client.host
        is_new = client_ip not in connected_devices
        connected_devices[client_ip] = {"last_seen": time.time(), "name": payload.name, "ip": client_ip}
        signal_emitter.device_list_updated.emit()
        if is_new:
            log.info(f"New device connected: {payload.name} ({client_ip})")
            notification_payload = {"type": "notification", "data": {"title": "Device Connected", "message": f"{payload.name} ({client_ip}) has connected.", "timestamp": datetime.now(timezone.utc).isoformat()}}
            await manager.broadcast(notification_payload)
        return {"status": "announced"}
        
    return app

async def broadcast_updates_task(manager: ConnectionManager, state: Any, network_monitor: NetworkMonitor):
    while True:
        try:
            system_data = await get_system_info_data(network_monitor)
            media_data = await get_media_info_data()
            system_data["allow_insecure_shell"] = state.allow_insecure_shell
            payload = {"type": "update", "data": {"system": system_data, "media": media_data}}
            await manager.broadcast(payload)
        except Exception as e:
            log.error(f"Error in broadcast task: {e}")
        await asyncio.sleep(1)