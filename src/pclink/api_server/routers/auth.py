# src/pclink/api_server/routers/auth.py
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ...core.web_auth import web_auth_manager
from .dependencies import WEB_AUTH

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


class SetupPasswordPayload(BaseModel):
    password: str


class LoginPayload(BaseModel):
    password: str


class ChangePasswordPayload(BaseModel):
    old_password: str
    new_password: str


@router.get("/status")
async def auth_status():
    return web_auth_manager.get_session_info()


@router.get("/check")
async def check_session(request: Request):
    session_token = request.cookies.get("pclink_session")
    client_ip = request.client.host if request.client else None
    if not session_token:
        return {"authenticated": False, "reason": "No session token"}
    if not web_auth_manager.validate_session(session_token, client_ip):
        return {"authenticated": False, "reason": "Invalid or expired session"}
    return {"authenticated": True, "session_valid": True}


@router.post("/setup")
async def setup_password(payload: SetupPasswordPayload, request: Request):
    """Provision initial server password."""
    if web_auth_manager.is_setup_completed():
        raise HTTPException(status_code=400, detail="Setup already completed")
    if len(payload.password) < 8:
        raise HTTPException(
            status_code=400, detail="Password must be at least 8 characters"
        )
    if not web_auth_manager.setup_password(payload.password):
        raise HTTPException(status_code=400, detail="Failed to setup password")

    # Access controller from app state safely
    controller = getattr(request.app.state, "controller", None)
    if controller and hasattr(controller, "activate_secure_mode"):
        controller.activate_secure_mode()

    return {"status": "success", "message": "Password setup completed"}


@router.post("/login")
async def login(payload: LoginPayload, request: Request):
    """Create authenticated session."""
    session_token = web_auth_manager.create_session(payload.password)
    if not session_token:
        raise HTTPException(status_code=401, detail="Invalid password")

    response = JSONResponse(
        {
            "status": "success",
            "message": "Login successful",
            "session_token": session_token,
            "redirect": "/ui/",
        }
    )
    response.set_cookie(
        key="pclink_session",
        value=session_token,
        max_age=24 * 60 * 60,
        httponly=True,
        secure=False,
        samesite="lax",
        path="/",
    )
    return response


@router.post("/logout")
async def logout(request: Request):
    session_token = request.cookies.get("pclink_session")
    if session_token:
        web_auth_manager.revoke_session(session_token)

    response = JSONResponse({"status": "success", "message": "Logged out"})
    response.delete_cookie("pclink_session")
    return response


@router.post("/change-password", dependencies=[WEB_AUTH])
async def change_password(payload: ChangePasswordPayload):
    """Update server password."""
    if len(payload.new_password) < 8:
        raise HTTPException(
            status_code=400, detail="New password must be at least 8 characters"
        )
    if not web_auth_manager.change_password(payload.old_password, payload.new_password):
        raise HTTPException(status_code=400, detail="Invalid old password")
    return {"status": "success", "message": "Password changed successfully"}


class FactoryResetPayload(BaseModel):
    password: str
    wipe_auth: bool
    wipe_extensions: bool = False


@router.post("/factory-reset")
async def factory_reset(payload: FactoryResetPayload, request: Request):
    """Destructive operation: wipes server configuration and logic."""
    # Safety Check: Request must originate from local machine
    client_ip = request.client.host if request.client else None
    if client_ip not in ("127.0.0.1", "::1", "localhost"):
        log.warning(f"BLOCKED: Factory reset attempt from external IP: {client_ip}")
        raise HTTPException(
            status_code=403, detail="Factory reset only allowed from local machine."
        )

    # Verify Password
    if not web_auth_manager.verify_password(payload.password):
        log.error(f"BLOCKED: Failed password for factory reset from {client_ip}")
        raise HTTPException(status_code=401, detail="Invalid password.")

    from ...core.utils import perform_factory_reset

    # Trigger reset — this will terminate the server process.
    perform_factory_reset(
        wipe_auth=payload.wipe_auth, wipe_extensions=payload.wipe_extensions
    )
    return {"status": "success", "message": "Server reset initiating..."}
