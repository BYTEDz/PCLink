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
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel

from ..core import constants
from ..core.device_manager import device_manager
from ..core.utils import get_cert_fingerprint
from ..core.validators import ValidationError, validate_api_key
from ..core.web_auth import web_auth_manager
from ..web_ui.router import create_web_ui_router

# --- API Router Imports ---
from .file_browser import router as file_browser_router
from .phone_file_router import router as phone_file_router

# UPDATED: Import from the new transfers package
from .transfer_router import upload_router, download_router, restore_sessions_startup, cleanup_stale_sessions
from ..services.transfer_service import transfer_service, TEMP_UPLOAD_DIR, DOWNLOAD_SESSION_DIR

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
from .extension_router import mgmt_router, runtime_router, mount_extension_routes
from .services_router import router as services_router
from ..core.extension_manager import ExtensionManager

log = logging.getLogger(__name__)

# --- Pydantic Models ---
class AnnouncePayload(BaseModel): name: str; local_ip: Optional[str] = None; platform: Optional[str] = None; client_version: Optional[str] = None; device_id: Optional[str] = None
class QrPayload(BaseModel): protocol: str; ip: str; port: int; apiKey: str; certFingerprint: Optional[str] = None
class PairingRequestPayload(BaseModel): device_name: str; device_id: Optional[str] = None; device_fingerprint: Optional[str] = None; client_version: Optional[str] = None; platform: Optional[str] = None; hardware_id: Optional[str] = None

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
    def __init__(self): 
        self.active_connections: List[WebSocket] = []
        # Support multiple connections per device (Mobile app + Extensions)
        self.device_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, device_id: str = None): 
        await websocket.accept()
        self.active_connections.append(websocket)
        if device_id:
            if device_id not in self.device_connections:
                self.device_connections[device_id] = []
            self.device_connections[device_id].append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections: 
            self.active_connections.remove(websocket)
        
        # Remove from device map (cleanup lists)
        for dev_id, ws_list in list(self.device_connections.items()):
            if websocket in ws_list:
                ws_list.remove(websocket)
                if not ws_list:
                    del self.device_connections[dev_id]
                break

    async def disconnect_device(self, device_id: str):
        """Forcefully disconnect all paths for a specific device."""
        if ws_list := self.device_connections.get(device_id):
            # Create a copy to avoid modification during iteration
            for socket in list(ws_list):
                try:
                    # Using code 4003 to signal "Device Revoked" explicitly
                    await socket.close(code=4003, reason="Device revoked")
                except Exception:
                    pass
                finally:
                    # Logic safety: Ensure it's removed even if close fails
                    if socket in self.active_connections:
                        self.active_connections.remove(socket)
            
            # Final purge of the device list
            if device_id in self.device_connections:
                del self.device_connections[device_id]

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
    controller = controller_instance

    async def verify_api_key(x_api_key: str = Header(None), token: str = Query(None), request: Request = None):
        # 1. Check for API Key (Mobile/Extensions)
        key = x_api_key or token
        if not key and request:
            key = request.cookies.get("pclink_device_token")
            
        if key:
            try:
                if secrets.compare_digest(validate_api_key(key), server_api_key): return True
            except ValidationError: pass
            device = device_manager.get_device_by_api_key(key)
            if device and device.is_approved:
                if request and request.client:
                    client_ip = request.client.host
                    if device.current_ip != client_ip: device_manager.update_device_ip(device.device_id, client_ip)
                    else: device_manager.update_device_last_seen(device.device_id)
                return True
            raise HTTPException(status_code=403, detail="DEVICE_REVOKED")
        
        # 2. Fallback to Web Session (if accessed via browser)
        try:
            if await verify_web_session(request):
                return True
        except HTTPException: pass
            
        raise HTTPException(status_code=403, detail="Missing API Key or session")
    
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
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    
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
    
    # --- Service Management ---
    app.include_router(services_router, prefix="/ui/services", tags=["Services"], dependencies=[WEB_AUTH])
    
    # --- Register Routers (ORDER MATTERS) ---
    app.include_router(upload_router, prefix="/files/upload", tags=["Uploads"], dependencies=MOBILE_API)
    app.include_router(download_router, prefix="/files/download", tags=["Downloads"], dependencies=MOBILE_API)
    app.include_router(file_browser_router, prefix="/files", tags=["Files"], dependencies=MOBILE_API)
    app.include_router(phone_file_router, prefix="/phone/files", tags=["Phone Files"], dependencies=MOBILE_API)
    
    app.include_router(system_router, prefix="/system", tags=["System"], dependencies=MOBILE_API)
    app.include_router(media_streaming_router, prefix="/files", tags=["Streaming"], dependencies=MOBILE_API)
    app.include_router(process_manager_router, prefix="/system", tags=["Processes"], dependencies=MOBILE_API)
    app.include_router(info_router, prefix="/info", tags=["Info"], dependencies=MOBILE_API)
    app.include_router(input_router, prefix="/input", tags=["Input"], dependencies=MOBILE_API)
    app.include_router(media_router, prefix="/media", tags=["Media"], dependencies=MOBILE_API)
    app.include_router(utils_router, prefix="/utils", tags=["Utils"], dependencies=MOBILE_API)
    app.include_router(terminal_router, prefix="/terminal", tags=["Terminal"], dependencies=MOBILE_API)
    app.include_router(macro_router, prefix="/macro", tags=["Macros"], dependencies=MOBILE_API)
    app.include_router(applications_router, prefix="/applications", tags=["Apps"], dependencies=MOBILE_API)
    
    # --- Extension System ---
    extension_manager = ExtensionManager()
    extension_manager.load_all_extensions()
    
    # Extension management (accessible by mobile app)
    app.include_router(mgmt_router, prefix="/api/extensions", dependencies=MOBILE_API)
    
    # Extension runtime (UI/Static) - Authenticated unique per extension ID
    app.include_router(runtime_router, prefix="/extensions", dependencies=MOBILE_API)
    
    # Mount actual extension routes (dynamic)
    mount_extension_routes(app, MOBILE_API)
    
    # Enable dynamic mounting for extensions loaded later (hot-loading)
    extension_manager.app = app
    
    app.state.allow_insecure_shell = allow_insecure_shell
    app.state.api_key = server_api_key

    @app.middleware("http")
    async def extension_safety_middleware(request: Request, call_next):
        # Block access to any /extensions/{extension_id} routes if disabled
        # Except for the management API which is under /api/extensions
        path = request.url.path
        if path.startswith("/extensions/") and not path.startswith("/api/extensions"):
            from ..core.config import config_manager
            if not config_manager.get("allow_extensions", False):
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Extension system is disabled globally"}
                )

            parts = path.split("/")
            if len(parts) > 2:
                extension_id = parts[2]
                if not extension_manager.get_extension(extension_id):
                    # Hot-loading attempt: Check if it exists and is enabled on disk
                    manifest_path = extension_manager.extensions_path / extension_id / "extension.yaml"
                    if manifest_path.exists():
                        try:
                            import yaml
                            with open(manifest_path, 'r', encoding='utf-8') as f:
                                config = yaml.safe_load(f)
                            if config.get('enabled', True):
                                log.info(f"Hot-loading requested extension on-demand: {extension_id}")
                                if extension_manager.load_extension(extension_id):
                                    # Successfully loaded, allow the request to proceed
                                    return await call_next(request)
                        except Exception as e:
                            log.error(f"Failed to hot-load extension {extension_id} on request: {e}")

                    log.warning(f"Blocking request to disabled or unknown extension: {extension_id} (Path: {path})")
                    from fastapi.responses import JSONResponse
                    return JSONResponse(
                        status_code=403,
                        content={"detail": f"Extension '{extension_id}' is disabled or not found"}
                    )
        return await call_next(request)

    @app.middleware("http")
    async def service_enforcement_middleware(request: Request, call_next):
        """Enforces service-level permissions based on configuration."""
        path = request.url.path
        
        # Define path mappings for services
        service_mappings = {
            "/files": "files",
            "/system": "system",
            "/info": "info",
            "/input": "input",
            "/media": "media",
            "/terminal": "terminal",
            "/macro": "macros",
            "/applications": "applications",
            "/utils": "utils",
        }
        
        # Whitelist core endpoints
        whitelist = ["/info/version", "/ping", "/info/heartbeat", "/heartbeat"]
        if any(path == p for p in whitelist):
            return await call_next(request)
        
        for route_prefix, service_name in service_mappings.items():
            if path.startswith(route_prefix):
                from ..core.config import config_manager
                services = config_manager.get("services", {})
                if not services.get(service_name, True):
                    from fastapi.responses import JSONResponse
                    log.warning(f"Blocking request to disabled service '{service_name}': {path}")
                    return JSONResponse(
                        status_code=403,
                        content={
                            "detail": f"The '{service_name}' service is currently disabled.",
                            "service": service_name,
                            "action": "ENABLE_SERVICE_IN_UI"
                        }
                    )
                break
                
        return await call_next(request)

    @app.on_event("startup")
    async def startup_event():
        try:
            result = await restore_sessions_startup()
            log.info(f"Session restoration: {result['restored_uploads']} uploads, {result['restored_downloads']} downloads")
            
            async def periodic_cleanup():
                while True:
                    await asyncio.sleep(3600)
                    try:
                        from ..core.config import config_manager
                        threshold = config_manager.get("transfer_cleanup_threshold", 7)
                        await cleanup_stale_sessions(days=threshold)
                        pass
                    except Exception as e:
                        log.error(f"Periodic cleanup failed: {e}")
            
            asyncio.create_task(periodic_cleanup())
            
        except Exception as e:
            log.error(f"Failed to restore sessions on startup: {e}")
        
        asyncio.create_task(broadcast_updates_task(mobile_manager, app.state))
        
        # Clear extension crash counter on successful startup
        extension_manager.mark_startup_success()

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket, token: str = Query(None)):
        if not token: await websocket.close(code=1008, reason="Missing API Key"); return
        authenticated = False
        device = None
        try:
            if secrets.compare_digest(validate_api_key(token), server_api_key): authenticated = True
        except ValidationError: pass
        if not authenticated:
            device = device_manager.get_device_by_api_key(token)
            if device and device.is_approved: authenticated = True; device_manager.update_device_last_seen(device.device_id)
        if not authenticated: await websocket.close(code=1008, reason="Invalid API Key"); return
        device_id = device.device_id if device else None
        await mobile_manager.connect(websocket, device_id)
        try:
            while True:
                data = await websocket.receive_json()
                from ..core.config import config_manager
                services = config_manager.get("services", {})
                if not services.get("input", True):
                    # Silently ignore input commands if the service is disabled
                    continue
                    
                if (msg_type := data.get("type")) == "mouse_control": handle_mouse_command(data)
                elif msg_type == "keyboard_control": handle_keyboard_command(data)
        except (WebSocketDisconnect, OSError): pass
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
            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type")
                
                if msg_type == "approve_pair":
                    pid = data.get("pairing_id")
                    if pid and pid in pairing_events:
                        if pid in pairing_results:
                            pairing_results[pid]["approved"] = True
                        pairing_events[pid].set()
                        await websocket.send_json({"type": "notification", "data": {"title": "Pairing Approved", "message": f"Device approved"}})
                        
                elif msg_type == "deny_pair":
                    pid = data.get("pairing_id")
                    if pid and pid in pairing_events:
                        pairing_events[pid].set() # Approved defaults to False
                        await websocket.send_json({"type": "notification", "data": {"title": "Pairing Denied", "message": "Device pairing request denied"}})

        except (WebSocketDisconnect, OSError):
            log.info("Web UI client disconnected from WebSocket.")
        except json.JSONDecodeError:
            pass
        finally: ui_manager.disconnect(websocket)

    @app.get("/ui/pairing/list", dependencies=[WEB_AUTH])
    async def list_pending_pairings():
        """List all currently pending pairing requests."""
        pending = []
        for pid, data in pairing_results.items():
            dev = data.get("device")
            if dev:
                pending.append({
                    "pairing_id": pid,
                    "device_name": dev.device_name, 
                    "device_id": dev.device_id,
                    "platform": dev.platform,
                    "ip": dev.current_ip,
                })
        return {"requests": pending}

    @app.post("/pairing/request", dependencies=[Depends(verify_mobile_api_enabled)])
    async def request_pairing(payload: PairingRequestPayload, request: Request):
        """Initiate device pairing sequence."""
        pairing_id = str(uuid.uuid4())
        try:
            event = asyncio.Event(); pairing_events[pairing_id] = event
            client_ip = request.client.host if request.client else "unknown"
            device_id = payload.device_id or str(uuid.uuid4())
            if not payload.device_name or not payload.device_name.strip(): raise HTTPException(status_code=400, detail="Device name is required.")
            
            # --- Duplicate Detection & Cleanup ---
            # Handle re-pairing scenarios where a device gets a new ID.
            try:
                existing_devices = device_manager.get_all_devices()
                device_fingerprint = payload.device_fingerprint or ""
                platform = payload.platform or ""
                new_hardware_id = payload.hardware_id or ""
                
                for existing in existing_devices:
                    match_found = False
                    reason = ""
                    
                    # 1. Strong Match: Hardware ID
                    if new_hardware_id and existing.hardware_id == new_hardware_id and existing.device_id != device_id:
                        match_found = True
                        reason = "Hardware ID Match"
                        
                    # 2. Heuristic Match (Fallback): Same Name + Platform + Fingerprint
                    elif (not new_hardware_id and not match_found and
                          existing.device_name == payload.device_name and 
                          existing.platform == platform and 
                          existing.device_fingerprint == device_fingerprint and
                          existing.device_id != device_id):
                        match_found = True
                        reason = "Heuristic Match"

                    if match_found:
                        is_connected = existing.device_id in mobile_manager.device_connections
                        
                        # Conditions to delete:
                        # 1. Explicit Hardware ID Match (Always delete old entry, as unique ID guarantees same physical device)
                        # 2. Heuristic: IP match OR Offline
                        should_revoke = False
                        
                        if reason == "Hardware ID Match":
                             # If hardware ID matches, it IS the same device. 
                             # Even if "connected" (maybe zombie connection), we should prefer the new pairing request.
                             should_revoke = True
                        elif existing.current_ip == client_ip or not is_connected:
                             should_revoke = True

                        if should_revoke:
                            log.info(f"Cleanup: Revoking old/duplicate device entry: {existing.device_name} ({existing.device_id}) - Reason: {reason}")
                            device_manager.revoke_device(existing.device_id)
                            await mobile_manager.disconnect_device(existing.device_id)
                            
            except Exception as e:
                log.warning(f"Error during duplicate device cleanup: {e}")
            # -------------------------------------

            device = device_manager.register_device(
                device_id=device_id, 
                device_name=payload.device_name, 
                device_fingerprint=payload.device_fingerprint or "", 
                platform=payload.platform or "", 
                client_version=payload.client_version or "", 
                current_ip=client_ip,
                hardware_id=payload.hardware_id or ""
            )
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

    @app.get("/heartbeat", dependencies=MOBILE_API)
    async def heartbeat(): return {"status": "ok", "time": time.time()}

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
        """Provision initial server password."""
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
        """Create authenticated session."""
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
        """Update server password."""
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
                if device.is_approved: 
                    device_manager.revoke_device(device.device_id)
                    await mobile_manager.disconnect_device(device.device_id)
                    removed_count += 1
            connected_devices.clear()
            log.info(f"Removed {removed_count} devices via web UI")
            return {"status": "success", "removed_count": removed_count}
        except Exception as e: log.error(f"Failed to remove all devices: {e}"); raise HTTPException(status_code=500, detail="Failed to remove devices")

    @app.post("/devices/revoke", dependencies=[WEB_AUTH])
    async def revoke_single_device(device_id: str = Query(..., description="The ID of the device to revoke access for")):
        """Revoke device access and purge caches."""
        try:
            # 1. Get device details before deleting to know its IP
            device = device_manager.get_device_by_id(device_id)
            device_ip = device.current_ip if device else None
            
            if device_manager.revoke_device(device_id):
                # 2. Disconnect active WebSocket
                await mobile_manager.disconnect_device(device_id)
                
                # 3. Aggressively clean up connected_devices memory cache
                # Removal conditions:
                # a) The cached entry's device_id matches the revoked ID
                # b) The cached entry has NO device_id but matches the device's last known IP (ghost entry)
                removed_from_cache = 0
                for ip, data in list(connected_devices.items()):
                    cached_id = data.get("device_id")
                    
                    # Match by ID
                    if cached_id == device_id:
                        del connected_devices[ip]
                        removed_from_cache += 1
                        continue
                        
                    # Match by IP (fallback for entries without ID)
                    if device_ip and ip == device_ip and not cached_id:
                        del connected_devices[ip]
                        removed_from_cache += 1
                
                log.info(f"Device {device_id} revoked via web UI. Removed {removed_from_cache} entries from discovery cache.")
                return {"status": "success", "message": "Device access revoked"}
            
            raise HTTPException(status_code=404, detail="Device not found")
        except HTTPException: raise
        except Exception as e:
            log.error(f"Failed to revoke device {device_id}: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.get("/updates/check")
    async def check_for_updates():
        """Query GitHub for latest release metadata."""
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
        """Persist global server configuration."""
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
            if "allow_extensions" in data:
                extensions_enabled = data["allow_extensions"]
                config_manager.set("allow_extensions", extensions_enabled)
                log.info(f"Extensions setting updated: allow_extensions={extensions_enabled}")
                if extensions_enabled:
                    log.info("Enabling extension system: Loading all extensions...")
                    extension_manager.load_all_extensions()
                else:
                    log.info("Disabling extension system: Unloading all extensions...")
                    extension_manager.unload_all_extensions()
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
                "allow_extensions": config_manager.get("allow_extensions", False),
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
        ACTIVE_UPLOADS = transfer_service.active_uploads
        ACTIVE_DOWNLOADS = transfer_service.active_downloads
        TRANSFER_LOCKS = transfer_service.transfer_locks
        
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
            result = await cleanup_stale_sessions(days=threshold)
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

    @app.post("/extensions/{extension_id}/approve", dependencies=[WEB_AUTH])
    async def approve_extension(extension_id: str):
        try:
            from ..core.config import config_manager
            if not config_manager.get("allow_extensions", False):
                raise HTTPException(status_code=403, detail="Extension system is disabled globally. Enable it in settings to approve extensions.")

            # 1. Update manifest to remove security flag and enable
            manifest_path = extension_manager.extensions_path / extension_id / "extension.yaml"
            if not manifest_path.exists():
                raise HTTPException(status_code=404, detail="Extension not found")
                
            import yaml
            with open(manifest_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            config['enabled'] = True
            config['security_consent_needed'] = False
            
            with open(manifest_path, 'w', encoding='utf-8') as f:
                yaml.safe_dump(config, f)
            
            # 2. Load it
            if extension_manager.load_extension(extension_id):
                log.info(f"Extension {extension_id} approved and enabled.")
                return {"status": "success", "message": "Extension approved and enabled"}
            else:
                raise HTTPException(status_code=500, detail="Failed to load extension after approval")
        except HTTPException: raise
        except Exception as e:
            log.error(f"Failed to approve extension {extension_id}: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    return app

async def broadcast_updates_task(manager: ConnectionManager, state: Any):
    from ..services import system_service, media_service
    from ..core.config import config_manager
    while True:
        try:
            if not manager.active_connections:
                await asyncio.sleep(5)
                continue
            
            services = config_manager.get("services", {})
            
            # Prepare internal data structure
            update_data = {}
            
            # Check services for system info
            if services.get("info", True):
                update_data["system"] = await system_service.get_system_info()
                update_data["system"]["allow_insecure_shell"] = state.allow_insecure_shell
            else:
                # Basic info only even if service is disabled
                import platform
                from ..core.version import __version__
                update_data["system"] = {
                    "version": __version__,
                    "platform": platform.system(),
                    "allow_insecure_shell": state.allow_insecure_shell
                }

            # Check services for media info
            if services.get("media", True):
                update_data["media"] = await media_service.get_media_info()
            else:
                update_data["media"] = {"status": "Service disabled"}

            payload = {"type": "update", "data": update_data}
            await manager.broadcast(payload)
        except Exception as e: log.error(f"Error in broadcast task: {e}")
        await asyncio.sleep(1)