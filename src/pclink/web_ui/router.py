# src/pclink/web_ui/router.py
"""
PCLink Web UI Router
Serves the web-based control panel interface
"""

from fastapi import APIRouter, Request, FastAPI
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from ..core.utils import resource_path

def create_web_ui_router(app: FastAPI) -> APIRouter:
    """
    Create and configure the web UI router and mount static files.
    
    The `app` instance is required to mount the StaticFiles directory.
    """
    router = APIRouter()
    
    # Use the helper to define the static directory robustly.
    static_dir = resource_path("src/pclink/web_ui/static")
    assets_dir = resource_path("src/pclink/assets")
    
    # The mount path MUST match the prefix used in api.py
    # This will now correctly serve files from /ui/static/
    app.mount("/ui/static", StaticFiles(directory=static_dir), name="static")
    
    # Mount assets directory for icons and other assets
    app.mount("/ui/assets", StaticFiles(directory=assets_dir), name="assets")
    
    # This helper is needed to prevent caching of critical UI files
    def no_cache_file_response(path, media_type="text/html"):
        headers = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
        return FileResponse(path, media_type=media_type, headers=headers)

    @router.get("/", response_class=HTMLResponse)
    async def serve_web_ui(request: Request):
        """Serve the main web UI page or redirect to auth."""
        from ..core.web_auth import web_auth_manager
        
        auth_file = static_dir / "auth.html"
        
        # Check if setup is completed
        if not web_auth_manager.is_setup_completed():
            if auth_file.exists():
                return no_cache_file_response(auth_file)
        
        # Check for valid session
        session_token = request.cookies.get("pclink_session")
        client_ip = request.client.host if request.client else None
        
        if not session_token or not web_auth_manager.validate_session(session_token, client_ip):
            if auth_file.exists():
                return no_cache_file_response(auth_file)
        
        # Serve main UI
        # --- THIS IS THE CORRECTED LINE ---
        index_file = static_dir / "index.html"
        # ---
        if index_file.exists():
            return no_cache_file_response(index_file)
        else:
            return HTMLResponse(
                content="<h1>PCLink Web UI</h1><p>Web UI files not found</p>",
                status_code=404
            )
    
    @router.get("/auth", response_class=HTMLResponse)
    async def serve_auth_page():
        """Serve the authentication page explicitly."""
        auth_file = static_dir / "auth.html"
        if auth_file.exists():
            return no_cache_file_response(auth_file)
        else:
            return HTMLResponse(
                content="<h1>Authentication</h1><p>Auth page not found</p>",
                status_code=404
            )
    
    return router