# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

# src/pclink/web_ui/router.py
"""
PCLink Web UI Router
Serves the web-based control panel interface
"""

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..core.utils import resource_path


def create_web_ui_router(app: FastAPI) -> APIRouter:
    """
    Create and configure the web UI router and mount static files.
    """
    router = APIRouter()

    # Use the helper to define the static directory robustly.
    static_dir = resource_path("src/pclink/web_ui/static")
    assets_dir = resource_path("src/pclink/assets")
    templates_dir = resource_path("src/pclink/web_ui/templates")

    # Mount static files
    app.mount("/ui/static", StaticFiles(directory=static_dir), name="static")
    app.mount("/ui/assets", StaticFiles(directory=assets_dir), name="assets")

    # Initialize Jinja2
    templates = Jinja2Templates(directory=templates_dir)

    @router.get("/", response_class=HTMLResponse)
    async def serve_web_ui(request: Request):
        """Serve the main web UI page or redirect to auth."""
        from ..core.web_auth import web_auth_manager

        # Check if setup is completed
        if not web_auth_manager.is_setup_completed():
            return templates.TemplateResponse("auth.html", {"request": request})

        # Check for valid session
        session_token = request.cookies.get("pclink_session")
        client_ip = request.client.host if request.client else None

        if not session_token or not web_auth_manager.validate_session(
            session_token, client_ip
        ):
            return templates.TemplateResponse("auth.html", {"request": request})

        # Serve main UI using Jinja2
        return templates.TemplateResponse("base.html", {"request": request})

    @router.get("/auth", response_class=HTMLResponse)
    async def serve_auth_page(request: Request):
        """Serve the authentication page explicitly."""
        return templates.TemplateResponse("auth.html", {"request": request})

    return router
