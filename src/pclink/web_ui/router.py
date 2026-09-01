# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

"""
PCLink Web UI Router
Serves the web-based control panel interface, cached assets, and dynamic templates.
"""

import asyncio
import logging
import urllib.request

import jinja2  # noqa: F401
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..core import constants
from ..core.utils import resource_path
from ..core.version import __version__

log = logging.getLogger(__name__)

CACHE_UPSTREAM_URLS = {
    "tailwindcss.js": "https://cdn.tailwindcss.com",
    "daisyui.min.css": "https://cdn.jsdelivr.net/npm/daisyui@4.12.10/dist/full.min.css",
}


async def prewarm_web_cache():
    """Asynchronously caches remote web assets to avoid client-side CDN timeouts."""
    cache_dir = constants.WEB_CACHE_PATH
    cache_dir.mkdir(parents=True, exist_ok=True)

    def _download_asset(filename: str, url: str):
        target_path = cache_dir / filename
        if target_path.exists() and target_path.stat().st_size > 0:
            return
        tmp_path = target_path.with_suffix(".tmp")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "PCLink-Server"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    tmp_path.write_bytes(resp.read())
                    tmp_path.replace(target_path)
                    log.info(f"Cached web UI asset locally: {filename}")
        except Exception as e:
            log.debug(f"Web UI asset prewarm skipped for '{filename}': {e}")
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    for filename, url in CACHE_UPSTREAM_URLS.items():
        await asyncio.to_thread(_download_asset, filename, url)


def create_web_ui_router(app: FastAPI) -> APIRouter:
    router = APIRouter()

    static_dir = resource_path("src/pclink/web_ui/static")
    assets_dir = resource_path("src/pclink/assets")
    templates_dir = resource_path("src/pclink/web_ui/templates")

    app.mount("/ui/static", StaticFiles(directory=str(static_dir)), name="static")
    app.mount("/ui/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    templates = Jinja2Templates(directory=str(templates_dir))

    @router.get("/cache/{filename}")
    async def serve_cached_asset(filename: str):
        """Serves cached web assets locally from application storage."""
        if filename not in CACHE_UPSTREAM_URLS:
            raise HTTPException(status_code=404, detail="Asset not found")

        cache_path = constants.WEB_CACHE_PATH / filename
        if cache_path.exists() and cache_path.stat().st_size > 0:
            media_type = (
                "application/javascript" if filename.endswith(".js") else "text/css"
            )
            return FileResponse(
                cache_path,
                media_type=media_type,
                headers={"Cache-Control": "public, max-age=31536000, immutable"},
            )

        upstream_url = CACHE_UPSTREAM_URLS[filename]

        def _fetch_sync():
            req = urllib.request.Request(
                upstream_url, headers={"User-Agent": "PCLink-Server"}
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                if resp.status == 200:
                    return resp.read()
            return None

        try:
            content = await asyncio.to_thread(_fetch_sync)
            if content:
                constants.WEB_CACHE_PATH.mkdir(parents=True, exist_ok=True)
                cache_path.write_bytes(content)
                media_type = (
                    "application/javascript" if filename.endswith(".js") else "text/css"
                )
                return FileResponse(
                    cache_path,
                    media_type=media_type,
                    headers={"Cache-Control": "public, max-age=31536000, immutable"},
                )
        except Exception as e:
            log.debug(f"Failed to retrieve upstream asset '{filename}': {e}")

        media_type = (
            "application/javascript" if filename.endswith(".js") else "text/css"
        )
        return Response(
            content="/* Offline fallback: Asset unavailable */", media_type=media_type
        )

    @router.get("/", response_class=HTMLResponse)
    async def serve_web_ui(request: Request):
        from ..core.web_auth import web_auth_manager

        context = {"request": request, "server_version": __version__}

        if not web_auth_manager.is_setup_completed():
            return templates.TemplateResponse(
                request=request, name="auth.html", context=context
            )

        session_token = request.cookies.get("pclink_session")
        client_ip = request.client.host if request.client else None

        if not session_token or not web_auth_manager.validate_session(
            session_token, client_ip
        ):
            return templates.TemplateResponse(
                request=request, name="auth.html", context=context
            )

        return templates.TemplateResponse(
            request=request, name="base.html", context=context
        )

    @router.get("/auth", response_class=HTMLResponse)
    async def serve_auth_page(request: Request):
        context = {"request": request, "server_version": __version__}
        return templates.TemplateResponse(
            request=request, name="auth.html", context=context
        )

    return router
