# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import json
import logging
import time
import uuid
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import (Depends, FastAPI, Header, HTTPException, Query, Request,
                     WebSocket, WebSocketDisconnect)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ..core import constants
from ..core.device_manager import device_manager
from ..core.utils import get_cert_fingerprint
from ..core.validators import ValidationError, validate_api_key
from ..core.web_auth import web_auth_manager
from ..web_ui.router import create_web_ui_router

# --- API Router Imports ---
from .file_browser import router as file_browser_router

# UPDATED: Import from the new transfers package
from .transfers import upload_router, download_router, restore_sessions, cleanup_stale_sessions

from .info_router import router as info_router
from .media_streaming import router as media_streaming_router
from .input_router import router as input_router
from .media_router import router as media_router
from .process_manager import router as process_manager_router
from .services import (NetworkMonitor, button_map, get_media_info_data,
                       get_system_info_data, keyboard_controller,
                       mouse_controller, PYNPUT_AVAILABLE)
from .system_router import router as system_router
from .terminal import create_terminal_router
from .utils_router import router as utils_router
from .macro_router import router as macro_router
from .applications_router import router as applications_router

log = logging.getLogger(__name__)

# --- Pydantic Models ---
class AnnouncePayload(BaseModel): name: str; local_ip: Optional[str] = None; platform: Optional[str] = None; client_version: Optional[str] = None; device_id: Optional[str] = None
class QrPayload(BaseModel): protocol: str; ip: str; port: int; apiKey: str; certFingerprint: Optional[str] = None
class PairingRequestPayload(BaseModel): device_name: str; device_id: Optional[str] = None; device_fingerprint: Optional[str] = None; client_version: Optional[str] = None; platform: Optional[str] = None

# Web Auth Models
class SetupPasswordPayload(BaseModel): password: str
class LoginPayload(BaseModel): password: str
class ChangePasswordPayload(BaseModel): old_password: str; new_password: str

# --- Pairing State ---
pairing_events: Dict[str, asyncio.Event] = {}
pairing_results: Dict[str, dict] = {}

# --- WebSocket Command Handlers ---
def handle_mouse_command(data: Dict[str, Any]):
    if not PYNPUT_AVAILABLE:
        log.warning("Mouse command ignored - pynput not available")
        return
    
    action = data.get("action")
    try:
        button = button_map.get(data.get("button", "left"))
        if action == "move": mouse_controller.move(data.get("dx", 0), data.get("dy", 0))
        elif action == "click": mouse_controller.click(button, data.get("clicks", 1))
        elif action == "double_click": mouse_controller.click(button, 2)
        elif action == "down": mouse_controller.press(button)
        elif action == "up": mouse_controller.release(button)
        elif action == "scroll": mouse_controller.scroll(data.get("dx", 0), data.get("dy", 0))
    except Exception as e: log.error(f"Error executing mouse command '{action}': {e}")

def handle_keyboard_command(data: Dict[str, Any]):
    if not PYNPUT_AVAILABLE:
        log.warning("Keyboard command ignored - pynput not available")
        return
    
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
def create_api_app(api_key: str, controller_instance, connected_devices: Dict, allow_insecure_shell: bool) -> FastAPI:
    app = FastAPI(
        title="PCLink API", 
        version="8.9.0", 
        docs_url=None, 
        redoc_url=None,
        generate_unique_id_function=lambda route: f"{route.tags[0]}-{route.name}" if route.tags else route.name
    )
    
    mobile_manager = ConnectionManager()
    ui_manager = ConnectionManager()
    
    server_api_key = validate_api_key(api_key)
    network_monitor = NetworkMonitor()
    controller = controller_instance

    async def verify_api_key(x_api_key: str = Header(None), request: Request = None):
        if not x_api_key: raise HTTPException(status_code=403, detail="Missing API Key")
        try:
            if secrets.compare_digest(validate_api_key(x_api_key), server_api_key): return True
        except ValidationError: pass
        device = device_manager.get_device_by_api_key(x_api_key)
        if not device or not device.is_approved: raise HTTPException(status_code=403, detail="Invalid API Key")
        if request and request.client:
            client_ip = request.client.host
            if device.current_ip != client_ip: device_manager.update_device_ip(device.device_id, client_ip)
            else: device_manager.update_device_last_seen(device.device_id)
        return True
    
    async def verify_web_session(request: Request):
        session_token = request.cookies.get("pclink_session")
        if not session_token: session_token = request.headers.get("X-Session-Token")
        if not session_token: raise HTTPException(status_code=401, detail="No session token")
        client_ip = request.client.host if request.client else None
        if not web_auth_manager.validate_session(session_token, client_ip): raise HTTPException(status_code=401, detail="Invalid or expired session")
        return True

    def verify_mobile_api_enabled():
        if not (controller and hasattr(controller, 'mobile_api_enabled') and controller.mobile_api_enabled):
            log.warning("Mobile API endpoint accessed but API is disabled. (Setup not complete?)")
            raise HTTPException(status_code=503, detail="Mobile API is currently disabled.")
        return True
    
    WEB_AUTH = Depends(verify_web_session)
    MOBILE_API = [Depends(verify_api_key), Depends(verify_mobile_api_enabled)]
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    
    @app.middleware("http")
    async def upload_optimization_middleware(request: Request, call_next):
        if request.url.path.startswith("/files/upload/"):
            response = await call_next(request)
            response.headers["content-encoding"] = "identity"
            return response
        return await call_next(request)
    
    terminal_router = create_terminal_router(server_api_key)
    
    try:
        web_ui_router = create_web_ui_router(app)
        app.include_router(web_ui_router, prefix="/ui")
        log.info("Web UI enabled at /ui/")
    except Exception as e:
        log.warning(f"Web UI could not be loaded: {e}")
        @app.get("/ui/")
        async def web_ui_fallback(): return {"message": "Web UI not available", "error": str(e)}
    
    # --- Register Routers (ORDER MATTERS) ---
    app.include_router(upload_router, prefix="/files/upload", tags=["Uploads"], dependencies=MOBILE_API)
    app.include_router(download_router, prefix="/files/download", tags=["Downloads"], dependencies=MOBILE_API)
    app.include_router(file_browser_router, prefix="/files", tags=["Files"], dependencies=MOBILE_API)
    
    app.include_router(system_router, prefix="/system", tags=["System"], dependencies=MOBILE_API)
    app.include_router(media_streaming_router, prefix="/files", tags=["Streaming"], dependencies=MOBILE_API)
    app.include_router(process_manager_router, prefix="/system", tags=["Processes"], dependencies=MOBILE_API)
    app.include_router(info_router, prefix="/info", tags=["Info"], dependencies=MOBILE_API)
    app.include_router(input_router, prefix="/input", tags=["Input"], dependencies=MOBILE_API)
    app.include_router(media_router, prefix="/media", tags=["Media"], dependencies=MOBILE_API)
    app.include_router(utils_router, prefix="/utils", tags=["Utils"], dependencies=MOBILE_API)
    app.include_router(terminal_router, prefix="/terminal", tags=["Terminal"])
    app.include_router(macro_router, prefix="/macro", tags=["Macros"], dependencies=MOBILE_API)
    app.include_router(applications_router, prefix="/applications", tags=["Apps"], dependencies=MOBILE_API)
    
    app.state.allow_insecure_shell = allow_insecure_shell
    app.state.api_key = server_api_key

    @app.on_event("startup")
    async def startup_event():
        try:
            result = await asyncio.to_thread(restore_sessions)
            log.info(f"Session restoration: {result['restored_uploads']} uploads, {result['restored_downloads']} downloads")
            
            async def periodic_cleanup():
                while True:
                    await asyncio.sleep(3600)
                    try:
                        from ..core.config import config_manager
                        threshold = config_manager.get("transfer_cleanup_threshold", 7)
                        await cleanup_stale_sessions(threshold_days=threshold)
                    except Exception as e:
                        log.error(f"Periodic cleanup failed: {e}")
            
            asyncio.create_task(periodic_cleanup())
            
        except Exception as e:
            log.error(f"Failed to restore sessions on startup: {e}")
        
        asyncio.create_task(broadcast_updates_task(mobile_manager, app.state, network_monitor))

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket, token: str = Query(None)):
        if not token: await websocket.close(code=1008, reason="Missing API Key"); return
        authenticated = False
        try:
            if secrets.compare_digest(validate_api_key(token), server_api_key): authenticated = True
        except ValidationError: pass
        if not authenticated:
            device = device_manager.get_device_by_api_key(token)
            if device and device.is_approved: authenticated = True; device_manager.update_device_last_seen(device.device_id)
        if not authenticated: await websocket.close(code=1008, reason="Invalid API Key"); return
        await mobile_manager.connect(websocket)
        try:
            while True:
                data = await websocket.receive_json()
                if (msg_type := data.get("type")) == "mouse_control": handle_mouse_command(data)
                elif msg_type == "keyboard_control": handle_keyboard_command(data)
        except WebSocketDisconnect: pass
        except (json.JSONDecodeError, KeyError): pass
        finally: mobile_manager.disconnect(websocket)

    @app.websocket("/ws/ui")
    async def websocket_ui_endpoint(websocket: WebSocket):
        try:
            await verify_web_session(websocket)
        except HTTPException:
            await websocket.close(code=4001, reason="Authentication failed")
            return
        
        await ui_manager.connect(websocket)
        log.info("Web UI client connected to WebSocket.")
        
        try:
            is_enabled = getattr(controller, 'mobile_api_enabled', False) if controller else False
            initial_status = "running" if is_enabled else "stopped"
            await websocket.send_json({"type": "server_status", "status": initial_status})
        except Exception as e:
            log.error(f"Failed to send initial status to UI client: {e}")
            
        try:
            while True: await websocket.receive_text()
        except WebSocketDisconnect: log.info("Web UI client disconnected from WebSocket.")
        finally: ui_manager.disconnect(websocket)

    @app.post("/pairing/request", dependencies=[Depends(verify_mobile_api_enabled)])
    async def request_pairing(payload: PairingRequestPayload, request: Request):
        pairing_id = str(uuid.uuid4())
        try:
            event = asyncio.Event(); pairing_events[pairing_id] = event
            client_ip = request.client.host if request.client else "unknown"
            device_id = payload.device_id or str(uuid.uuid4())
            if not payload.device_name or not payload.device_name.strip(): raise HTTPException(status_code=400, detail="Device name is required.")
            device = device_manager.register_device(device_id=device_id, device_name=payload.device_name, device_fingerprint=payload.device_fingerprint or "", platform=payload.platform or "", client_version=payload.client_version or "", current_ip=client_ip)
            pairing_results[pairing_id] = {"device": device, "approved": False}
            
            pairing_notification = { "type": "pairing_request", "data": { "pairing_id": pairing_id, "device_name": payload.device_name, "device_id": device_id, "ip": client_ip, "platform": payload.platform, "client_version": payload.client_version } }
            await mobile_manager.broadcast(pairing_notification)
            await ui_manager.broadcast(pairing_notification)
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
    def read_root():
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/ui/")

    @app.get("/api")
    def api_root(): return {"message": "PCLink API is running."}

    @app.get("/ping", dependencies=MOBILE_API)
    async def ping(): return {"status": "pong"}

    @app.get("/status")
    async def server_status():
        import sys
        from ..core.version import __version__
        mobile_api_enabled = getattr(controller, 'mobile_api_enabled', False) if controller else False
        return { "status": "running", "server_running": mobile_api_enabled, "web_ui_running": True, "mobile_api_enabled": mobile_api_enabled, "version": __version__, "port": app.state.host_port if hasattr(app.state, 'host_port') else 38080, "platform": sys.platform }
    
    @app.get("/auth/status")
    async def auth_status(): return web_auth_manager.get_session_info()
    
    @app.get("/auth/check")
    async def check_session(request: Request):
        session_token = request.cookies.get("pclink_session")
        client_ip = request.client.host if request.client else None
        if not session_token: return {"authenticated": False, "reason": "No session token"}
        if not web_auth_manager.validate_session(session_token, client_ip): return {"authenticated": False, "reason": "Invalid or expired session"}
        return {"authenticated": True, "session_valid": True}
    
    @app.post("/auth/setup")
    async def setup_password(payload: SetupPasswordPayload):
        if web_auth_manager.is_setup_completed(): raise HTTPException(status_code=400, detail="Setup already completed")
        if len(payload.password) < 8: raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
        if not web_auth_manager.setup_password(payload.password): raise HTTPException(status_code=400, detail="Failed to setup password")
        
        if not constants.API_KEY_FILE.exists():
            try:
                api_key = str(uuid.uuid4())
                constants.API_KEY_FILE.write_text(api_key)
                app.state.api_key = api_key
                log.info(f"Generated and saved API key after setup completion: {constants.API_KEY_FILE}")
            except Exception as e:
                log.error(f"Failed to save API key after setup: {e}")
        
        if controller and hasattr(controller, 'activate_secure_mode'):
            controller.activate_secure_mode()

        return {"status": "success", "message": "Password setup completed"}
    
    @app.post("/auth/login")
    async def login(payload: LoginPayload, request: Request):
        session_token = web_auth_manager.create_session(payload.password)
        if not session_token: raise HTTPException(status_code=401, detail="Invalid password")
        from fastapi.responses import JSONResponse
        response = JSONResponse({ "status": "success", "message": "Login successful", "session_token": session_token, "redirect": "/ui/" })
        response.set_cookie(key="pclink_session", value=session_token, max_age=24*60*60, httponly=True, secure=False, samesite="lax", path="/")
        return response
    
    @app.post("/auth/logout")
    async def logout(request: Request):
        session_token = request.cookies.get("pclink_session")
        if session_token: web_auth_manager.revoke_session(session_token)
        from fastapi.responses import JSONResponse
        response = JSONResponse({"status": "success", "message": "Logged out"})
        response.delete_cookie("pclink_session")
        return response
    
    @app.post("/auth/change-password", dependencies=[WEB_AUTH])
    async def change_password(payload: ChangePasswordPayload):
        if len(payload.new_password) < 8: raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
        if not web_auth_manager.change_password(payload.old_password, payload.new_password): raise HTTPException(status_code=400, detail="Invalid old password")
        return {"status": "success", "message": "Password changed successfully"}
    
    @app.get("/devices", dependencies=[WEB_AUTH])
    async def get_connected_devices():
        devices = []
        for device in device_manager.get_all_devices():
            if device.is_approved: devices.append({ "id": device.device_id, "name": device.device_name, "ip": device.current_ip, "platform": device.platform, "last_seen": device.last_seen.isoformat() if device.last_seen else "Never", "client_version": device.client_version })
        for ip, device_info in connected_devices.items():
            if not any(d["ip"] == ip for d in devices): devices.append({ "id": ip, "name": device_info.get("name", "Unknown Device"), "ip": ip, "platform": device_info.get("platform", "Unknown"), "last_seen": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(device_info.get("last_seen", 0))), "client_version": device_info.get("client_version", "Unknown") })
        return {"devices": devices}
    
    @app.post("/devices/remove-all", dependencies=[WEB_AUTH])
    async def remove_all_devices():
        try:
            removed_count = 0
            for device in device_manager.get_all_devices():
                if device.is_approved: device_manager.revoke_device(device.device_id); removed_count += 1
            connected_devices.clear()
            log.info(f"Removed {removed_count} devices via web UI")
            return {"status": "success", "removed_count": removed_count}
        except Exception as e: log.error(f"Failed to remove all devices: {e}"); raise HTTPException(status_code=500, detail="Failed to remove devices")
    
    @app.get("/updates/check")
    async def check_for_updates():
        try:
            import requests
            from ..core.version import __version__
            response = requests.get("https://api.github.com/repos/BYTEDz/pclink/releases/latest", timeout=10)
            if response.status_code == 200:
                release_data = response.json()
                latest_version = release_data.get("tag_name", "").lstrip("v")
                current_version = __version__
                def version_tuple(v): return tuple(map(int, (v.split("."))))
                try: update_available = version_tuple(latest_version) > version_tuple(current_version)
                except ValueError: update_available = False
                return { "update_available": update_available, "current_version": current_version, "latest_version": latest_version, "download_url": release_data.get("html_url"), "release_notes": release_data.get("body", "")[:500] }
            else: return {"update_available": False, "error": "Failed to check for updates"}
        except Exception as e: log.error(f"Update check failed: {e}"); return {"update_available": False, "error": str(e)}
    
    @app.post("/notifications/show", dependencies=[WEB_AUTH])
    async def show_system_notification(request: Request):
        try:
            data = await request.json()
            title = data.get("title", "PCLink"); message = data.get("message", "")
            if hasattr(app.state, 'tray_manager') and app.state.tray_manager:
                app.state.tray_manager.show_notification(title, message); return {"status": "success", "message": "Notification sent"}
            else: return {"status": "error", "message": "System notifications not available"}
        except Exception as e: log.error(f"Failed to show system notification: {e}"); return {"status": "error", "message": str(e)}
    
    @app.post("/settings/save", dependencies=[WEB_AUTH])
    async def save_server_settings(request: Request):
        try:
            data = await request.json()
            from ..core.config import config_manager
            
            if "auto_start" in data:
                auto_start_enabled = data["auto_start"]
                # Delegate to controller to apply OS-level changes
                if controller and hasattr(controller, 'handle_startup_change'):
                    try:
                        controller.handle_startup_change(auto_start_enabled)
                        log.info(f"Auto-start {'enabled' if auto_start_enabled else 'disabled'} via web UI")
                    except Exception as e:
                        log.error(f"Failed to update startup setting: {e}")
                        raise HTTPException(status_code=500, detail=str(e))
                else:
                    # Fallback (mostly for testing/dev if controller not injected)
                    config_manager.set("auto_start", auto_start_enabled)
            
            if "allow_terminal_access" in data:
                terminal_access = data["allow_terminal_access"]
                config_manager.set("allow_terminal_access", terminal_access)
                log.info(f"Terminal access setting updated: allow_terminal_access={terminal_access}")
            if "allow_insecure_shell" in data: config_manager.set("allow_insecure_shell", data["allow_insecure_shell"])
            if "auto_open_webui" in data: config_manager.set("auto_open_webui", data["auto_open_webui"])
            log.info(f"Server settings updated via web UI: {data}")
            return {"status": "success", "message": "Settings saved successfully"}
        except HTTPException as he: raise he
        except Exception as e: log.error(f"Failed to save settings: {e}"); return {"status": "error", "message": str(e)}
    
    @app.get("/settings/load", dependencies=[WEB_AUTH])
    async def load_server_settings():
        try:
            from ..core.config import config_manager
            from ..core import constants
            
            # Default from config
            auto_start_status = config_manager.get("auto_start", False)
            
            # Verify with actual OS state via controller
            if controller and hasattr(controller, 'startup_manager'):
                try:
                    real_status = controller.startup_manager.is_enabled()
                    if real_status != auto_start_status:
                        log.warning(f"Config auto_start ({auto_start_status}) mismatch with system ({real_status}). Updating config.")
                        config_manager.set("auto_start", real_status)
                        auto_start_status = real_status
                except Exception as e:
                    log.error(f"Failed to verify startup status: {e}")

            return { 
                "auto_start": auto_start_status, 
                "allow_terminal_access": config_manager.get("allow_terminal_access", False), 
                "allow_insecure_shell": config_manager.get("allow_insecure_shell", False), 
                "auto_open_webui": config_manager.get("auto_open_webui", True) 
            }
        except Exception as e: log.error(f"Failed to load settings: {e}"); return {"status": "error", "message": str(e)}
    
    @app.get("/logs", dependencies=[WEB_AUTH])
    async def get_server_logs():
        try:
            log_file = constants.APP_DATA_PATH / "pclink.log"
            if log_file.exists():
                with open(log_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    recent_lines = lines[-100:] if len(lines) > 100 else lines
                    return {"logs": ''.join(recent_lines), "lines": len(recent_lines)}
            else: return {"logs": "No log file found", "lines": 0}
        except Exception as e: return {"logs": f"Error reading logs: {str(e)}", "lines": 0}
    
    @app.post("/logs/clear", dependencies=[WEB_AUTH])
    async def clear_server_logs():
        try:
            log_file = constants.APP_DATA_PATH / "pclink.log"
            if log_file.exists():
                with open(log_file, 'w') as f: f.write(""); log.info("Server logs cleared via web UI")
                return {"status": "success", "message": "Logs cleared"}
            else: return {"status": "error", "message": "No log file found"}
        except Exception as e: return {"status": "error", "message": f"Error clearing logs: {str(e)}"}
    
    @app.get("/qr-payload", response_model=QrPayload)
    async def get_qr_payload():
        fingerprint = get_cert_fingerprint(constants.CERT_FILE)
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80)); local_ip = s.getsockname()[0]
        except Exception:
            try: local_ip = socket.gethostbyname(socket.gethostname())
            except Exception: local_ip = "127.0.0.1"
        return QrPayload(protocol="https", ip=local_ip, port=app.state.host_port, apiKey=app.state.api_key, certFingerprint=fingerprint)
    
    @app.post("/pairing/approve")
    async def approve_pairing(request: Request):
        data = await request.json(); pairing_id = data.get("pairing_id"); approved = data.get("approved", False)
        if pairing_id in pairing_results:
            pairing_results[pairing_id]["approved"] = approved; pairing_results[pairing_id]["user_decided"] = True
            if event := pairing_events.get(pairing_id): event.set()
            return {"status": "success", "approved": approved}
        else: raise HTTPException(status_code=404, detail="Pairing request not found")
    
    @app.post("/pairing/deny")
    async def deny_pairing(request: Request):
        data = await request.json(); pairing_id = data.get("pairing_id")
        if pairing_id in pairing_results:
            pairing_results[pairing_id]["approved"] = False; pairing_results[pairing_id]["user_decided"] = True
            if event := pairing_events.get(pairing_id): event.set()
            return {"status": "success", "approved": False}
        else: raise HTTPException(status_code=404, detail="Pairing request not found")
    
    @app.post("/announce", dependencies=MOBILE_API)
    async def announce_device(request: Request, payload: AnnouncePayload):
        client_ip = request.client.host
        is_new = client_ip not in connected_devices
        connected_devices[client_ip] = {"last_seen": time.time(), "name": payload.name, "ip": client_ip, "platform": payload.platform, "client_version": payload.client_version, "device_id": payload.device_id}
        if is_new:
            log.info(f"New device connected: {payload.name} ({client_ip})")
            notification_payload = {"type": "notification", "data": {"title": "Device Connected", "message": f"{payload.name} ({client_ip}) has connected.", "timestamp": datetime.now(timezone.utc).isoformat()}}
            await mobile_manager.broadcast(notification_payload)
            await ui_manager.broadcast(notification_payload)
        return {"status": "announced"}
    
    @app.post("/server/start", dependencies=[WEB_AUTH])
    async def start_server():
        try:
            if controller and hasattr(controller, 'start_server'):
                await ui_manager.broadcast({"type": "server_status", "status": "starting"})
                controller.start_server()
                await asyncio.sleep(1)
                await ui_manager.broadcast({"type": "server_status", "status": "running"})
                return {"status": "success", "message": "Server starting"}
            raise HTTPException(status_code=500, detail="Server controller not available")
        except Exception as e:
            log.error(f"Failed to start server: {e}")
            await ui_manager.broadcast({"type": "server_status", "status": "stopped"})
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.post("/server/stop", dependencies=[WEB_AUTH])
    async def stop_server():
        try:
            if controller and hasattr(controller, 'stop_server'):
                await ui_manager.broadcast({"type": "server_status", "status": "stopping"})
                controller.stop_server()
                await asyncio.sleep(1)
                await ui_manager.broadcast({"type": "server_status", "status": "stopped"})
                return {"status": "success", "message": "Server stopping"}
            raise HTTPException(status_code=500, detail="Server controller not available")
        except Exception as e:
            log.error(f"Failed to stop server: {e}")
            await ui_manager.broadcast({"type": "server_status", "status": "running"})
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.post("/server/restart", dependencies=[WEB_AUTH])
    async def restart_server():
        try:
            if controller and hasattr(controller, 'stop_server') and hasattr(controller, 'start_server'):
                await ui_manager.broadcast({"type": "server_status", "status": "restarting"})
                async def delayed_restart():
                    controller.stop_server()
                    await asyncio.sleep(2)
                    controller.start_server()
                    await asyncio.sleep(1)
                    await ui_manager.broadcast({"type": "server_status", "status": "running"})

                asyncio.create_task(delayed_restart())
                return {"status": "success", "message": "Server restarting"}
            raise HTTPException(status_code=500, detail="Server controller not available")
        except Exception as e:
            log.error(f"Failed to restart server: {e}")
            await ui_manager.broadcast({"type": "server_status", "status": "running"})
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.get("/debug/performance")
    async def debug_performance():
        import psutil
        import time
        from .transfers.session import ACTIVE_UPLOADS, ACTIVE_DOWNLOADS, TRANSFER_LOCKS, TEMP_UPLOAD_DIR, DOWNLOAD_SESSION_DIR
        
        process = psutil.Process()
        persisted_uploads = len(list(TEMP_UPLOAD_DIR.glob("*.meta")))
        persisted_downloads = len(list(DOWNLOAD_SESSION_DIR.glob("*.json")))
        
        return {
            "cpu_percent": process.cpu_percent(),
            "memory_mb": process.memory_info().rss / 1024 / 1024,
            "open_files": len(process.open_files()),
            "connections": len(process.connections()),
            "threads": process.num_threads(),
            "server_time": time.time(),
            "active_uploads_memory": len(ACTIVE_UPLOADS),
            "active_downloads_memory": len(ACTIVE_DOWNLOADS),
            "persisted_uploads_disk": persisted_uploads,
            "persisted_downloads_disk": persisted_downloads,
            "transfer_locks": len(TRANSFER_LOCKS)
        }
    
    @app.post("/server/shutdown", dependencies=[WEB_AUTH])
    async def shutdown_server():
        try:
            log.info("Shutdown endpoint called via web UI")
            await ui_manager.broadcast({"type": "server_status", "status": "shutting_down"})
            def do_shutdown():
                try:
                    log.info("Executing shutdown sequence...")
                    if controller and hasattr(controller, 'stop_server_completely'):
                        log.info("Stopping server completely...")
                        controller.stop_server_completely()
                    else:
                        log.warning("Controller not available or missing stop_server_completely method")
                finally:
                    log.info("Forcing application exit...")
                    import os
                    os._exit(0)
            import threading
            log.info("Starting shutdown timer...")
            threading.Timer(0.5, do_shutdown).start()
            return {"status": "success", "message": "Server shutting down"}
        except Exception as e:
            log.error(f"Failed to shutdown server: {e}")
            raise HTTPException(status_code=500, detail=str(e))
        
    @app.get("/transfers/cleanup/status", dependencies=[WEB_AUTH])
    async def get_transfer_cleanup_status():
        try:
            from .transfers.session import TEMP_UPLOAD_DIR, DOWNLOAD_SESSION_DIR
            from ..core.config import config_manager
            
            threshold = config_manager.get("transfer_cleanup_threshold", 7)
            current_time = time.time()
            threshold_seconds = threshold * 24 * 60 * 60
            
            stale_uploads = 0
            for meta in TEMP_UPLOAD_DIR.glob("*.meta"):
                if current_time - meta.stat().st_mtime > threshold_seconds:
                    stale_uploads += 1
                    
            stale_downloads = 0
            for sess in DOWNLOAD_SESSION_DIR.glob("*.json"):
                if current_time - sess.stat().st_mtime > threshold_seconds:
                    stale_downloads += 1
                    
            return {
                "threshold_days": threshold,
                "stale_uploads": stale_uploads,
                "stale_downloads": stale_downloads,
                "total_stale": stale_uploads + stale_downloads
            }
        except Exception as e:
            log.error(f"Failed to get cleanup status: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/transfers/cleanup/execute", dependencies=[WEB_AUTH])
    async def execute_transfer_cleanup():
        try:
            from ..core.config import config_manager
            threshold = config_manager.get("transfer_cleanup_threshold", 7)
            result = await cleanup_stale_sessions(threshold_days=threshold)
            return {"status": "success", "cleaned": result}
        except Exception as e:
            log.error(f"Manual cleanup failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.patch("/transfers/cleanup/config", dependencies=[WEB_AUTH])
    async def update_transfer_cleanup_config(request: Request):
        try:
            data = await request.json()
            threshold = data.get("threshold")
            if threshold is None or not isinstance(threshold, int) or threshold < 0:
                raise HTTPException(status_code=400, detail="Invalid threshold value")
            
            from ..core.config import config_manager
            config_manager.set("transfer_cleanup_threshold", threshold)
            return {"status": "success", "threshold": threshold}
        except Exception as e:
            log.error(f"Failed to update cleanup config: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    return app

async def broadcast_updates_task(manager: ConnectionManager, state: Any, network_monitor: NetworkMonitor):
    while True:
        try:
            if not manager.active_connections:
                await asyncio.sleep(5)
                continue
            
            system_data = await get_system_info_data(network_monitor)
            media_data = await get_media_info_data()
            system_data["allow_insecure_shell"] = state.allow_insecure_shell
            payload = {"type": "update", "data": {"system": system_data, "media": media_data}}
            await manager.broadcast(payload)
        except Exception as e: log.error(f"Error in broadcast task: {e}")
        await asyncio.sleep(1)