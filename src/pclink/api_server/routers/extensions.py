# src/pclink/api_server/routers/extensions.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import gettext
import logging
import os
import shutil
import tempfile
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from ...core.config import config_manager
from ...core.extension_manager import DANGEROUS_PERMISSIONS, ExtensionManager
from ...core.utils import resource_path

log = logging.getLogger(__name__)
_ = gettext.gettext

extension_manager = ExtensionManager()

mgmt_router = APIRouter(tags=["extension-management"])
runtime_router = APIRouter(tags=["extension-runtime"])


def _ensure_extensions_enabled():
    if not config_manager.get("allow_extensions", False):
        raise HTTPException(
            status_code=403, detail=_("Extension system is globally disabled.")
        )


def _serialize_metadata(metadata: Any) -> Dict[str, Any]:
    if isinstance(metadata, dict):
        return metadata.copy()
    if hasattr(metadata, "model_dump"):
        return metadata.model_dump()
    return metadata.dict()


def _resolve_extension_path_and_manifest(
    extension_id: str,
) -> Tuple[Path, Optional[dict]]:
    """Helper to resolve extension filesystem path and manifest dict reliably."""
    ext_dir = (extension_manager.extensions_path / extension_id).resolve()
    manifest = extension_manager.get_manifest(extension_id)
    return ext_dir, manifest


@mgmt_router.get("/")
@mgmt_router.get("")
async def list_extensions():
    enabled_globally = config_manager.get("allow_extensions", False)
    discovered = extension_manager.discover_extensions()
    all_exts = []

    for eid in discovered:
        try:
            meta = extension_manager.get_manifest(eid)
            if not meta:
                continue

            is_loaded = (eid in extension_manager.extensions) or (
                eid in extension_manager.isolated_processes
            )
            ext = extension_manager.get_extension(eid)

            if ext and hasattr(ext, "metadata"):
                response_meta = _serialize_metadata(ext.metadata)
            elif ext and isinstance(ext, dict) and "metadata" in ext:
                response_meta = _serialize_metadata(ext["metadata"])
            else:
                response_meta = meta.copy()

            response_meta["id"] = eid
            response_meta["is_loaded"] = is_loaded

            # Add process telemetry (PID, CPU %, Memory MB)
            telemetry = extension_manager.get_extension_telemetry(eid)
            response_meta["pid"] = telemetry.get("pid")
            response_meta["cpu_percent"] = telemetry.get("cpu_percent", 0.0)
            response_meta["memory_mb"] = telemetry.get("memory_mb", 0.0)

            if ext and getattr(ext, "has_venv", False):
                response_meta["has_venv"] = True
                response_meta["venv_path"] = str(getattr(ext, "venv_path", ""))
            else:
                response_meta["has_venv"] = False
                response_meta["venv_path"] = None

            perms = response_meta.get("permissions", [])
            response_meta["has_dangerous_perms"] = any(
                p in DANGEROUS_PERMISSIONS for p in perms
            )
            response_meta["user_approved"] = not response_meta.get(
                "security_consent_needed", False
            )

            if "dashboard_widgets" not in response_meta:
                response_meta["dashboard_widgets"] = []

            all_exts.append(response_meta)

        except Exception as e:
            log.error(f"Error processing extension '{eid}': {e}", exc_info=True)

    return {"extensions_enabled": enabled_globally, "extensions": all_exts}


@mgmt_router.post("/install")
async def install_extension(file: UploadFile = File(...)):
    _ensure_extensions_enabled()
    if not file.filename.endswith(".zip"):
        raise HTTPException(400, _("Only .zip allowed"))
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_p = Path(tmp.name)
    try:
        if extension_manager.install_extension(tmp_p):
            return {"status": "success"}
        raise HTTPException(400, _("Install failed"))
    except PermissionError as e:
        raise HTTPException(403, str(e))
    finally:
        if tmp_p.exists():
            os.unlink(tmp_p)


@mgmt_router.post("/install/url")
async def install_extension_from_url(url: str = Query(...)):
    _ensure_extensions_enabled()
    if not url.startswith("http"):
        raise HTTPException(400, _("Invalid URL"))

    import threading

    task_id = f"url-{abs(hash(url))}"

    extension_manager.install_states[task_id] = {
        "status": "downloading",
        "progress": 0,
        "error": None,
    }

    def download_and_install():
        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
            tmp_p = Path(tmp.name)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as response:
                content_length = response.headers.get("content-length")
                total_bytes = int(content_length) if content_length else None
                downloaded = 0

                with open(tmp_p, "wb") as out_file:
                    while True:
                        chunk = response.read(8192)
                        if not chunk:
                            break
                        out_file.write(chunk)
                        downloaded += len(chunk)
                        if total_bytes:
                            percent = int((downloaded / total_bytes) * 100)
                            extension_manager.install_states[task_id] = {
                                "status": "downloading",
                                "progress": min(percent, 99),
                                "error": None,
                            }
            extension_manager.install_states[task_id] = {
                "status": "downloading",
                "progress": 100,
                "error": None,
            }
            if not extension_manager.install_extension(tmp_p, task_id=task_id):
                extension_manager.install_states[task_id] = {
                    "status": "failed",
                    "progress": 0,
                    "error": _("Install failed"),
                }
        except Exception as e:
            extension_manager.install_states[task_id] = {
                "status": "failed",
                "progress": 0,
                "error": str(e),
            }
        finally:
            if tmp_p.exists():
                try:
                    os.unlink(tmp_p)
                except OSError:
                    pass

    threading.Thread(target=download_and_install, name=f"downloader-{task_id}").start()
    return {"status": "success", "task_id": task_id}


@mgmt_router.delete("/{extension_id}")
async def delete_extension(extension_id: str):
    _ensure_extensions_enabled()
    try:
        if extension_manager.delete_extension(extension_id):
            return {"status": "success"}
        raise HTTPException(500, _("Delete failed"))
    except PermissionError as e:
        raise HTTPException(403, str(e))


@mgmt_router.post("/{extension_id}/toggle")
async def toggle_extension(extension_id: str, enabled: bool):
    _ensure_extensions_enabled()
    try:
        if extension_manager.toggle_extension(extension_id, enabled):
            return {"status": "success"}
        raise HTTPException(500, _("Toggle failed"))
    except PermissionError as e:
        raise HTTPException(403, str(e))


@mgmt_router.get("/{extension_id}/install-status")
async def get_install_status(extension_id: str):
    status = extension_manager.install_states.get(extension_id)
    if not status:
        ext = extension_manager.get_extension(extension_id)
        if ext:
            return {"status": "completed", "progress": 100, "error": None}
        return {"status": "idle", "progress": 0, "error": None}
    return status


@mgmt_router.get("/{extension_id}/logs")
async def get_logs(extension_id: str):
    return {
        "id": extension_id,
        "logs": extension_manager.get_extension_logs(extension_id),
    }


@mgmt_router.delete("/{extension_id}/logs")
async def clear_logs(extension_id: str):
    extension_manager.clear_extension_logs(extension_id)
    return {"status": "success"}


@runtime_router.get("/sdk/pclink-sdk.js")
async def get_pclink_sdk():
    """Serves the unified extension SDK JS library."""
    sdk_path = resource_path("src/pclink/web_ui/static/pclink-sdk.js")
    if not sdk_path.exists():
        raise HTTPException(404, _("SDK file missing"))
    return FileResponse(sdk_path, media_type="application/javascript")


@runtime_router.get("/{extension_id}/ui")
async def get_ui(extension_id: str, token: str = Query(None)):
    ext_dir, manifest = _resolve_extension_path_and_manifest(extension_id)
    if not manifest:
        raise HTTPException(404, _("Extension manifest not found"))

    ui_entry = manifest.get("ui_entry", "index.html")
    if not ui_entry:
        raise HTTPException(404, _("UI entry point not specified"))

    ui_p = (ext_dir / ui_entry).resolve()
    if not str(ui_p).startswith(str(ext_dir.resolve())) or not ui_p.exists():
        raise HTTPException(404, _("UI entry file missing"))

    res = FileResponse(ui_p, media_type="text/html")
    res.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    res.headers["Pragma"] = "no-cache"
    if token:
        res.set_cookie(
            "pclink_device_token",
            token,
            max_age=3600,
            httponly=True,
            samesite="lax",
            path="/",
        )
    return res


@runtime_router.get("/{extension_id}/widget/{widget_id}")
async def get_widget_ui(extension_id: str, widget_id: str, token: str = Query(None)):
    ext_dir, manifest = _resolve_extension_path_and_manifest(extension_id)
    if not manifest:
        raise HTTPException(404, _("Extension not found"))

    widgets = manifest.get("dashboard_widgets", [])
    widget = next((w for w in widgets if w.get("id") == widget_id), None)
    if not widget:
        raise HTTPException(404, _("Widget not found"))

    ui_entry = widget.get("ui_entry")
    if not ui_entry:
        raise HTTPException(404, _("Widget UI entry missing"))

    ui_p = (ext_dir / ui_entry).resolve()
    if not str(ui_p).startswith(str(ext_dir.resolve())) or not ui_p.exists():
        raise HTTPException(404, _("Widget UI missing"))

    res = FileResponse(ui_p, media_type="text/html")
    res.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    res.headers["Pragma"] = "no-cache"
    if token:
        res.set_cookie(
            "pclink_device_token",
            token,
            max_age=3600,
            httponly=True,
            samesite="lax",
            path="/",
        )
    return res


@mgmt_router.get("/{extension_id}/icon")
@runtime_router.get("/{extension_id}/icon")
async def get_icon(extension_id: str):
    ext_dir, manifest = _resolve_extension_path_and_manifest(extension_id)
    icon_rel = manifest.get("icon") if manifest else None
    if not icon_rel:
        raise HTTPException(404, _("No icon specified in extension manifest"))

    icon_p = (ext_dir / icon_rel).resolve()
    if not str(icon_p).startswith(str(ext_dir.resolve())) or not icon_p.exists():
        raise HTTPException(404, _("Icon file not found"))

    return FileResponse(icon_p)


@runtime_router.get("/{extension_id}/static/{file_path:path}")
async def get_static(extension_id: str, file_path: str):
    ext_dir, _ = _resolve_extension_path_and_manifest(extension_id)
    base = (ext_dir / "static").resolve()
    target = (base / file_path).resolve()
    if not str(target).startswith(str(base)) or not target.is_file():
        raise HTTPException(403 if target.exists() else 404)
    return FileResponse(target)


# Dynamic IPC HTTP Gateway Handler for Process-Isolated Extension Endpoints
@runtime_router.api_route(
    "/{extension_id}/{subpath:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
)
async def proxy_isolated_extension_http(
    extension_id: str, subpath: str, request: Request
):
    """
    Transparently forwards HTTP requests to the isolated extension process via IPC Pipe.
    """
    if extension_id not in extension_manager.isolated_processes:
        raise HTTPException(
            status_code=404,
            detail=_("Extension '{extension_id}' not active").format(
                extension_id=extension_id
            ),
        )

    body = None
    try:
        body = await request.json()
    except Exception:
        pass

    subpath_clean = "/" + subpath.lstrip("/")

    res = extension_manager.dispatch_ipc_http_request(
        extension_id=extension_id,
        method=request.method,
        subpath=subpath_clean,
        body=body,
    )

    if not res:
        raise HTTPException(
            status_code=502, detail=_("Isolated extension process did not respond")
        )

    status_code = res.get("status_code", 200)
    content = res.get("content") or {"error": res.get("error")}

    return JSONResponse(content=content, status_code=status_code)
