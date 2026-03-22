# src/pclink/api_server/routers/auth.py
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ...core.web_auth import web_auth_manager
from .dependencies import WEB_AUTH

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
