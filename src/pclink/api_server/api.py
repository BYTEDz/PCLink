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
import platform
import re
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Dict, List, Optional

import keyboard
import mss
import psutil
import pyperclip
from fastapi import (Depends, FastAPI, Header, HTTPException, Query, Request,
                     WebSocket, WebSocketDisconnect)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from PIL import Image
from pydantic import BaseModel
from pynput.keyboard import Controller as KeyboardController
from pynput.keyboard import Key
from pynput.mouse import Button, Controller as MouseController

from ..core import constants
from ..core.device_manager import device_manager
from ..core.state import api_signal_emitter
from ..core.utils import get_cert_fingerprint
from ..core.validators import (ValidationError, sanitize_log_input,
                             validate_api_key)
from .file_browser import router as file_browser_router
from .file_browser import upload_router, download_router
from .process_manager import router as process_manager_router
from .terminal import create_terminal_router

log = logging.getLogger(__name__)

# --- Lightweight Controllers ---
mouse = MouseController()
keyboard_controller = KeyboardController()
button_map = {"left": Button.left, "right": Button.right, "middle": Button.middle}
key_map = {
    'enter': Key.enter, 'esc': Key.esc, 'shift': Key.shift, 'ctrl': Key.ctrl,
    'alt': Key.alt, 'cmd': Key.cmd, 'win': Key.cmd, 'backspace': Key.backspace,
    'delete': Key.delete, 'tab': Key.tab, 'space': Key.space, 'up': Key.up,
    'down': Key.down, 'left': Key.left, 'right': Key.right,
    'f1': Key.f1, 'f2': Key.f2, 'f3': Key.f3, 'f4': Key.f4,
    'f5': Key.f5, 'f6': Key.f6, 'f7': Key.f7, 'f8': Key.f8,
    'f9': Key.f9, 'f10': Key.f10, 'f11': Key.f11, 'f12': Key.f12
}

def get_key(key_str: str):
    """Returns a pynput Key enum or the character itself."""
    return key_map.get(key_str.lower(), key_str)

# --- Pydantic Models ---
class ClipboardModel(BaseModel):
    text: str

class MediaActionModel(BaseModel):
    action: str

class AnnouncePayload(BaseModel):
    name: str
    local_ip: Optional[str] = None

class KeyboardInputModel(BaseModel):
    text: Optional[str] = None
    key: Optional[str] = None
    modifiers: List[str] = []

class QrPayload(BaseModel):
    protocol: str
    ip: str
    port: int
    apiKey: str
    certFingerprint: Optional[str]

class PairingRequestPayload(BaseModel):
    device_name: str
    device_id: Optional[str] = None
    device_fingerprint: Optional[str] = None
    client_version: Optional[str] = None
    platform: Optional[str] = None


class ReconnectionPayload(BaseModel):
    device_id: str
    device_fingerprint: Optional[str] = None
    reconnection: bool = True


class IPChangePayload(BaseModel):
    device_id: str
    old_ip: Optional[str] = None
    new_ip: str
    timestamp: Optional[str] = None

# --- Pairing State ---
pairing_events: Dict[str, asyncio.Event] = {}
pairing_results: Dict[str, bool] = {}

# --- WebSocket Command Handlers ---
def handle_mouse_command(data: Dict[str, Any]):
    action = data.get("action")
    log.info(f"Received mouse command: {action}")
    try:
        button = button_map.get(data.get("button", "left"), Button.left)
        if action == "move":
            mouse.move(data.get("dx", 0), data.get("dy", 0))
        elif action == "click":
            mouse.click(button, 1)
        elif action == "double_click":
            mouse.click(button, 2)
        elif action == "down":
            mouse.press(button)
        elif action == "up":
            mouse.release(button)
        elif action == "scroll":
            mouse.scroll(data.get("dx", 0), data.get("dy", 0))
    except Exception as e:
        log.error(f"Error executing mouse command '{action}': {e}")

def handle_keyboard_command(data: Dict[str, Any]):
    log.info(f"Received keyboard command: {data.get('key') or data.get('text')}")
    try:
        if text := data.get("text"):
            keyboard_controller.type(text)
        elif key_str := data.get("key"):
            modifiers = data.get("modifiers", [])
            for mod_str in modifiers:
                keyboard_controller.press(get_key(mod_str))
            
            main_key = get_key(key_str)
            keyboard_controller.press(main_key)
            keyboard_controller.release(main_key)

            for mod_str in reversed(modifiers):
                keyboard_controller.release(get_key(mod_str))
    except Exception as e:
        log.error(f"Error executing keyboard command: {e}")

# --- WebSocket Connection Manager ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: Dict[str, Any]):
        for connection in self.active_connections[:]:
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)

    async def broadcast_notification(self, title: str, message: str):
        payload = {
            "type": "notification",
            "data": {
                "title": title,
                "message": message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }
        await self.broadcast(payload)

# --- Data Providers ---
def get_media_info_data():
    return {"title": "Nothing Playing", "artist": "", "status": "STOPPED"}

async def get_system_info_data():
    mem = psutil.virtual_memory()
    cpu_freq = psutil.cpu_freq()
    return {
        "os": f"{platform.system()} {platform.release()}",
        "hostname": socket.gethostname(),
        "cpu": {
            "percent": psutil.cpu_percent(interval=None),
            "physical_cores": psutil.cpu_count(logical=False),
            "total_cores": psutil.cpu_count(logical=True),
            "current_freq_mhz": cpu_freq.current if cpu_freq else 0,
        },
        "ram": {
            "percent": mem.percent,
            "total_gb": round(mem.total / (1024**3), 2),
            "used_gb": round(mem.used / (1024**3), 2),
        },
    }

# --- FastAPI App Factory ---
def create_api_app(
    api_key: str,
    signal_emitter,
    connected_devices: Dict,
    is_https_enabled: bool,
    allow_insecure_shell: bool,
) -> FastAPI:
    app = FastAPI(title="PCLink API", version="8.9.0", docs_url=None, redoc_url=None)
    manager = ConnectionManager()
    server_api_key = validate_api_key(api_key)

    async def verify_api_key(x_api_key: str = Header(None), request: Request = None):
        if not x_api_key:
            raise HTTPException(status_code=403, detail="Missing API Key")
        
        # Check if it's the server API key (for backward compatibility)
        try:
            if validate_api_key(x_api_key) == server_api_key:
                return True
        except ValidationError:
            pass
        
        # Check device-based authentication
        device = device_manager.get_device_by_api_key(x_api_key)
        if not device or not device.is_approved:
            log.warning(f"Invalid API key attempt: {sanitize_log_input(x_api_key[:8])}...")
            raise HTTPException(status_code=403, detail="Invalid API Key")
        
        # Update device IP and last seen
        if request and request.client:
            client_ip = request.client.host
            if device.current_ip != client_ip:
                device_manager.update_device_ip(device.device_id, client_ip)
            else:
                # Just update last seen time
                device_manager.update_device_last_seen(device.device_id)
        
        return True

    PROTECTED = Depends(verify_api_key)

    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    terminal_router = create_terminal_router(server_api_key, allow_insecure_shell)
    app.include_router(file_browser_router, prefix="/files", dependencies=[PROTECTED])
    app.include_router(upload_router, prefix="/files/upload", dependencies=[PROTECTED])
    app.include_router(download_router, prefix="/files/download", dependencies=[PROTECTED])
    app.include_router(process_manager_router, prefix="/system", dependencies=[PROTECTED])
    app.include_router(terminal_router, prefix="/terminal")
    app.state.is_https_enabled = is_https_enabled
    app.state.allow_insecure_shell = allow_insecure_shell
    app.state.api_key = server_api_key

    @app.on_event("startup")
    async def startup_event():
        asyncio.create_task(broadcast_updates_task(manager, app.state))

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket, token: str = Query(None)):
        if not token:
            await websocket.close(code=1008, reason="Missing API Key")
            return
        
        # Use the same authentication logic as REST endpoints
        authenticated = False
        
        # Check if it's the server API key (for backward compatibility)
        try:
            if validate_api_key(token) == server_api_key:
                authenticated = True
        except ValidationError:
            pass
        
        # Check device-based authentication
        if not authenticated:
            device = device_manager.get_device_by_api_key(token)
            if device and device.is_approved:
                authenticated = True
                # Update device last seen
                device_manager.update_device_last_seen(device.device_id)
        
        if not authenticated:
            log.warning(f"WebSocket connection rejected for token '{sanitize_log_input(token[:8])}...': Invalid API Key")
            await websocket.close(code=1008, reason="Invalid API Key")
            return

        await manager.connect(websocket)
        try:
            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type")
                if msg_type == "mouse_control":
                    handle_mouse_command(data)
                elif msg_type == "keyboard_control":
                    handle_keyboard_command(data)
        except WebSocketDisconnect:
            log.info(f"Client disconnected cleanly: {websocket.client.host}")
        except (json.JSONDecodeError, KeyError) as e:
            log.warning(f"Invalid WebSocket message received: {e}")
        finally:
            manager.disconnect(websocket)

    @app.post("/pairing/request")
    async def request_pairing(payload: PairingRequestPayload, request: Request):
        try:
            pairing_id = str(uuid.uuid4())
            event = asyncio.Event()
            pairing_events[pairing_id] = event
            
            client_ip = request.client.host if request.client else "unknown"
            device_id = payload.device_id or str(uuid.uuid4())
            
            log.info(f"Received pairing request from device '{payload.device_name}' ({device_id[:8]}...) at {client_ip}")
            
            # Validate payload
            if not payload.device_name or not payload.device_name.strip():
                log.warning(f"Pairing request {pairing_id} has empty device name")
                raise HTTPException(status_code=400, detail="Device name is required.")
            
            # Register device (pending approval)
            device = device_manager.register_device(
                device_id=device_id,
                device_name=payload.device_name,
                device_fingerprint=payload.device_fingerprint or "",
                platform=payload.platform or "",
                client_version=payload.client_version or "",
                current_ip=client_ip
            )
            
            # Store pairing info for the approval process
            pairing_events[pairing_id] = event
            pairing_results[pairing_id] = {"device": device, "approved": False}
            
            # Emit pairing request signal with device info
            try:
                api_signal_emitter.pairing_request.emit(pairing_id, payload.device_name, device_id)
            except Exception as e:
                log.error(f"Failed to emit pairing request signal: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail="Failed to process pairing request.")

            # Wait for user response
            try:
                await asyncio.wait_for(event.wait(), timeout=60.0)
            except asyncio.TimeoutError:
                log.warning(f"Pairing request {pairing_id} timed out after 60 seconds")
                raise HTTPException(status_code=408, detail="Pairing request timed out.")
            
            # Check user response
            pairing_result = pairing_results.get(pairing_id, {})
            if pairing_result.get("approved", False):
                # Approve the device
                device_manager.approve_device(device.device_id)
                log.info(f"Pairing request {pairing_id} accepted by user.")
                
                # Get certificate fingerprint if HTTPS is enabled
                fingerprint = None
                if app.state.is_https_enabled:
                    fingerprint = get_cert_fingerprint(constants.CERT_FILE)
                    if not fingerprint:
                        log.error(f"Failed to get certificate fingerprint for pairing {pairing_id}")
                        log.warning("Continuing pairing without certificate fingerprint")
                
                response_data = {
                    "api_key": device.api_key, 
                    "cert_fingerprint": fingerprint,
                    "device_id": device.device_id
                }
                log.info(f"Pairing {pairing_id} successful, returning device API key")
                return response_data
            else:
                log.info(f"Pairing request {pairing_id} denied by user.")
                # Remove the device since it wasn't approved
                device_manager.revoke_device(device.device_id)
                raise HTTPException(status_code=403, detail="Pairing request denied by user.")
                
        except HTTPException:
            raise
        except Exception as e:
            log.error(f"Unexpected error in request_pairing: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Internal server error during pairing.")
        finally:
            # Clean up pairing state
            pairing_events.pop(pairing_id, None)
            pairing_results.pop(pairing_id, None)

    @app.get("/")
    def read_root():
        return {"message": "PCLink API is running."}

    @app.get("/ping", dependencies=[PROTECTED])
    async def ping():
        return {"status": "pong"}

    @app.get("/qr-payload", response_model=QrPayload, dependencies=[PROTECTED])
    async def get_qr_payload(request: Request):
        try:
            fingerprint = None
            if app.state.is_https_enabled:
                fingerprint = get_cert_fingerprint(constants.CERT_FILE)
                if not fingerprint:
                    log.error(f"Failed to get certificate fingerprint from {constants.CERT_FILE}")
                    # Check if certificate file exists
                    if not constants.CERT_FILE.exists():
                        log.error(f"Certificate file does not exist: {constants.CERT_FILE}")
                        raise HTTPException(status_code=500, detail="Server certificate file not found.")
                    else:
                        log.error(f"Certificate file exists but fingerprint calculation failed")
                        raise HTTPException(status_code=500, detail="Could not process server certificate.")
            
            # Validate required state variables
            if not hasattr(app.state, 'host_ip') or not app.state.host_ip:
                log.error("app.state.host_ip is not set")
                raise HTTPException(status_code=500, detail="Server host IP not configured.")
            
            if not hasattr(app.state, 'host_port') or not app.state.host_port:
                log.error("app.state.host_port is not set")
                raise HTTPException(status_code=500, detail="Server host port not configured.")
            
            if not hasattr(app.state, 'api_key') or not app.state.api_key:
                log.error("app.state.api_key is not set")
                raise HTTPException(status_code=500, detail="Server API key not configured.")
            
            log.info(f"QR payload requested - Protocol: {'https' if app.state.is_https_enabled else 'http'}, IP: {app.state.host_ip}, Port: {app.state.host_port}")
            
            return QrPayload(
                protocol="https" if app.state.is_https_enabled else "http",
                ip=app.state.host_ip, 
                port=app.state.host_port,
                apiKey=app.state.api_key, 
                certFingerprint=fingerprint,
            )
        except HTTPException:
            raise
        except Exception as e:
            log.error(f"Unexpected error in get_qr_payload: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Internal server error during QR payload generation.")

    @app.post("/pairing/reconnect")
    async def silent_reconnection(payload: ReconnectionPayload, request: Request, x_api_key: str = Header(None)):
        """Handle silent reconnection for devices with changed IPs"""
        if not x_api_key:
            raise HTTPException(status_code=403, detail="Missing API Key")
        
        try:
            # Find device by API key and device ID
            device = device_manager.get_device_by_api_key(x_api_key)
            if not device or device.device_id != payload.device_id or not device.is_approved:
                log.warning(f"Reconnection attempt failed for device {payload.device_id[:8]}...")
                raise HTTPException(status_code=404, detail="Device not found or not approved")
            
            # Validate device fingerprint if provided
            if payload.device_fingerprint and device.device_fingerprint:
                if payload.device_fingerprint != device.device_fingerprint:
                    log.warning(f"Device fingerprint mismatch for {device.device_name}")
                    raise HTTPException(status_code=403, detail="Device fingerprint mismatch")
            
            # Update IP address silently
            client_ip = request.client.host if request.client else ""
            device_manager.update_device_ip(device.device_id, client_ip)
            
            log.info(f"Silent reconnection successful for {device.device_name} ({device.device_id[:8]}...)")
            return {"status": "success", "message": "Reconnection successful"}
            
        except HTTPException:
            raise
        except Exception as e:
            log.error(f"Error in silent reconnection: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Internal server error")

    @app.post("/device/ip-change", dependencies=[PROTECTED])
    async def handle_ip_change(payload: IPChangePayload, request: Request, x_api_key: str = Header(None)):
        """Handle IP change notification from devices"""
        if not x_api_key:
            raise HTTPException(status_code=403, detail="Missing API Key")
        
        try:
            # Find device by API key
            device = device_manager.get_device_by_api_key(x_api_key)
            if not device or device.device_id != payload.device_id or not device.is_approved:
                raise HTTPException(status_code=404, detail="Device not found or not approved")
            
            # Update device IP
            device_manager.update_device_ip(device.device_id, payload.new_ip)
            
            log.info(f"IP change notification from {device.device_name}: {payload.old_ip} -> {payload.new_ip}")
            return {"status": "success"}
            
        except HTTPException:
            raise
        except Exception as e:
            log.error(f"Error handling IP change: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Internal server error")

    @app.post("/announce", dependencies=[PROTECTED])
    async def announce_device(request: Request, payload: AnnouncePayload):
        client_ip = request.client.host
        is_new = client_ip not in connected_devices
        connected_devices[client_ip] = {"last_seen": time.time(), "name": payload.name, "ip": client_ip}
        signal_emitter.device_list_updated.emit()
        if is_new:
            log.info(f"New device connected: {payload.name} ({client_ip})")
            await manager.broadcast_notification("Device Connected", f"{payload.name} ({client_ip}) has connected.")
        return {"status": "announced", "ip": client_ip, "name": payload.name}

    @app.get("/info/system", dependencies=[PROTECTED])
    async def get_system_info_endpoint(request: Request):
        info = await get_system_info_data()
        info["allow_insecure_shell"] = request.app.state.allow_insecure_shell
        return info

    @app.get("/info/media", dependencies=[PROTECTED])
    async def get_media_info_endpoint():
        return get_media_info_data()

    @app.get("/info/disks", dependencies=[PROTECTED])
    async def get_disks_info():
        disks = []
        for p in psutil.disk_partitions(all=False):
            if "cdrom" in p.opts or not p.fstype: continue
            try:
                usage = psutil.disk_usage(p.mountpoint)
                if usage.total > 0:
                    disks.append({
                        "device": p.mountpoint, "total": f"{usage.total/(1024**3):.2f} GB",
                        "used": f"{usage.used/(1024**3):.2f} GB", "free": f"{usage.free/(1024**3):.2f} GB",
                        "percent": round(usage.percent),
                    })
            except Exception as e:
                log.warning(f"Could not get disk usage for {p.mountpoint}: {e}")
        return {"disks": disks}

    @app.post("/power/{command}", dependencies=[PROTECTED])
    async def power_command(command: str):
        cmd_map = {
            "win32": {"shutdown": ["shutdown", "/s", "/t", "1"], "reboot": ["shutdown", "/r", "/t", "1"], "lock": ["rundll32.exe", "user32.dll,LockWorkStation"]},
            "linux": {"shutdown": ["shutdown", "now"], "reboot": ["reboot"], "lock": ["xdg-screensaver", "lock"]},
            "darwin": {"shutdown": ["osascript", "-e", 'tell app "System Events" to shut down'], "reboot": ["osascript", "-e", 'tell app "System Events" to restart'], "lock": ["osascript", "-e", 'tell app "loginwindow" to  «event aevtrlok»']},
        }
        current_os = sys.platform
        if command not in cmd_map.get(current_os, {}):
            raise HTTPException(status_code=404, detail=f"Unsupported power command '{command}'")
        try:
            subprocess.run(cmd_map[current_os][command], check=True, capture_output=True)
            return {"status": f"{command} command sent"}
        except Exception as e:
            log.error(f"Power command '{command}' failed: {e}")
            raise HTTPException(status_code=500, detail="Failed to execute power command.")

    @app.post("/media", dependencies=[PROTECTED])
    async def media_command(payload: MediaActionModel):
        action_map = {"play_pause": "play/pause media", "next_track": "next track", "prev_track": "previous track"}
        if not (key := action_map.get(payload.action)):
            raise HTTPException(status_code=400, detail="Invalid media action")
        keyboard.send(key)
        return {"status": f"'{payload.action}' command sent"}

    @app.get("/volume", dependencies=[PROTECTED])
    async def get_volume():
        try:
            if sys.platform == "win32":
                from comtypes import CLSCTX_ALL
                from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
                devices = AudioUtilities.GetSpeakers()
                interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                volume = interface.QueryInterface(IAudioEndpointVolume)
                return {"level": round(volume.GetMasterVolumeLevelScalar() * 100)}
            elif sys.platform == "darwin":
                result = subprocess.run(['osascript', '-e', 'output volume of (get volume settings)'],
                                      capture_output=True, text=True)
                return {"level": int(result.stdout.strip())}
            else:  # Linux
                result = subprocess.run(['amixer', 'sget', 'Master'], capture_output=True, text=True)
                match = re.search(r'\[(\d+)%\]', result.stdout)
                return {"level": int(match.group(1)) if match else 50}
        except Exception as e:
            log.error(f"Volume retrieval failed: {e}")
            raise HTTPException(status_code=500, detail="Failed to get volume level")

    @app.post("/volume/set/{level}", dependencies=[PROTECTED])
    async def set_volume(level: int):
        if not 0 <= level <= 100:
            raise HTTPException(status_code=400, detail="Volume level must be between 0 and 100")
        
        try:
            if sys.platform == "win32":
                from comtypes import CLSCTX_ALL
                from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
                devices = AudioUtilities.GetSpeakers()
                interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                volume = interface.QueryInterface(IAudioEndpointVolume)
                volume.SetMasterVolumeLevelScalar(level / 100, None)
            elif sys.platform == "darwin":
                subprocess.run(['osascript', '-e', f'set volume output volume {level}'], check=True)
            else:  # Linux
                subprocess.run(['amixer', 'set', 'Master', f'{level}%'], check=True)
            
            log.info(f"Volume changed to {level}%")
            return {"status": f"Volume set to {level}%", "muted": level == 0}
        except subprocess.CalledProcessError as e:
            log.error(f"Volume set failed: {e}")
            raise HTTPException(status_code=500, detail="Failed to set volume")
        except Exception as e:
            log.error(f"Volume set error: {e}")
            raise HTTPException(status_code=500, detail="Volume control failed")

    @app.post("/utils/clipboard", dependencies=[PROTECTED])
    async def set_clipboard(payload: ClipboardModel):
        pyperclip.copy(payload.text)
        return {"status": "Clipboard updated"}

    @app.get("/utils/clipboard", dependencies=[PROTECTED])
    async def get_clipboard():
        return {"text": pyperclip.paste()}

    @app.get("/utils/screenshot", dependencies=[PROTECTED])
    async def get_screenshot():
        with mss.mss() as sct:
            sct_img = sct.grab(sct.monitors[1])
            img = Image.frombytes("RGB", sct_img.size, sct_img.rgb)
            buffer = BytesIO()
            img.save(buffer, format="PNG")
            return Response(content=buffer.getvalue(), media_type="image/png")

    @app.post("/input/keyboard", dependencies=[PROTECTED])
    async def send_keyboard_input(payload: KeyboardInputModel):
        try:
            if payload.text:
                keyboard_controller.type(payload.text)
            elif payload.key:
                for mod_str in payload.modifiers:
                    keyboard_controller.press(get_key(mod_str))
                
                main_key = get_key(payload.key)
                keyboard_controller.press(main_key)
                keyboard_controller.release(main_key)
                
                for mod_str in reversed(payload.modifiers):
                    keyboard_controller.release(get_key(mod_str))
            else:
                raise HTTPException(status_code=400, detail="Either 'text' or 'key' must be provided.")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to send keyboard input: {e}")
        return {"status": "input sent"}

    @app.get("/devices", dependencies=[PROTECTED])
    async def get_devices():
        """Get all registered devices"""
        devices = device_manager.get_all_devices()
        return {
            "devices": [
                {
                    "device_id": d.device_id[:8] + "...",  # Truncate for privacy
                    "device_name": d.device_name,
                    "platform": d.platform,
                    "current_ip": d.current_ip,
                    "last_seen": d.last_seen.isoformat(),
                    "is_approved": d.is_approved,
                    "is_online": (datetime.now(timezone.utc) - d.last_seen).total_seconds() < 300  # 5 minutes
                }
                for d in devices
            ]
        }

    @app.post("/devices/{device_id}/revoke", dependencies=[PROTECTED])
    async def revoke_device(device_id: str):
        """Revoke device access"""
        success = device_manager.revoke_device(device_id)
        if success:
            return {"status": "success", "message": "Device access revoked"}
        else:
            raise HTTPException(status_code=404, detail="Device not found")

    @app.get("/devices/{device_id}/ip-history", dependencies=[PROTECTED])
    async def get_device_ip_history(device_id: str, limit: int = Query(50, le=100)):
        """Get IP change history for a device"""
        history = device_manager.get_ip_change_history(device_id, limit)
        return {
            "device_id": device_id[:8] + "...",
            "ip_changes": [
                {
                    "old_ip": change.old_ip,
                    "new_ip": change.new_ip,
                    "timestamp": change.timestamp.isoformat()
                }
                for change in history
            ]
        }

    return app

async def broadcast_updates_task(manager: ConnectionManager, state: Any):
    while True:
        try:
            system_data = await get_system_info_data()
            media_data = get_media_info_data()
            system_data["allow_insecure_shell"] = state.allow_insecure_shell
            payload = {"type": "update", "data": {"system": system_data, "media": media_data}}
            await manager.broadcast(payload)
        except Exception as e:
            log.error(f"Error in broadcast task: {e}")
        await asyncio.sleep(2)