# src/pclink/api_server/routers/extensions.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import os
import shutil
import tempfile
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from ...services.extension_service import extension_service

mgmt_router = APIRouter(tags=["extension-management"])
runtime_router = APIRouter(tags=["extension-runtime"])


def _resolve_extension_path_and_manifest(
    extension_id: str,
) -> Tuple[Path, Optional[dict]]:
    """Helper to resolve extension filesystem path and manifest dict reliably."""
    ext_dir = (extension_service.manager.extensions_path / extension_id).resolve()
    manifest = extension_service.manager.get_manifest(extension_id)
    return ext_dir, manifest


@mgmt_router.get("/")
@mgmt_router.get("")
async def list_extensions():
    return extension_service.list_extensions()


@mgmt_router.post("/install")
async def install_extension(file: UploadFile = File(...)):
    if not file.filename.endswith(".zip"):
        raise HTTPException(400, "Only .zip allowed")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_p = Path(tmp.name)
    try:
        if extension_service.install(tmp_p):
            return {"status": "success"}
        raise HTTPException(400, "Install failed")
    except PermissionError as e:
        raise HTTPException(403, str(e))
    finally:
        if tmp_p.exists():
            os.unlink(tmp_p)


@mgmt_router.post("/install/url")
async def install_extension_from_url(url: str = Query(...)):
    if not url.startswith("http"):
        raise HTTPException(400, "Invalid URL")

    import threading

    task_id = f"url-{abs(hash(url))}"
    manager = extension_service.manager

    manager.install_states[task_id] = {
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
                            manager.install_states[task_id] = {
                                "status": "downloading",
                                "progress": min(percent, 99),
                                "error": None,
                            }
            manager.install_states[task_id] = {
                "status": "downloading",
                "progress": 100,
                "error": None,
            }
            if not extension_service.install(tmp_p, task_id=task_id):
                manager.install_states[task_id] = {
                    "status": "failed",
                    "progress": 0,
                    "error": "Install failed",
                }
        except Exception as e:
            manager.install_states[task_id] = {
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
    try:
        if extension_service.uninstall(extension_id):
            return {"status": "success"}
        raise HTTPException(500, "Delete failed")
    except PermissionError as e:
        raise HTTPException(403, str(e))


@mgmt_router.post("/{extension_id}/toggle")
async def toggle_extension(extension_id: str, enabled: bool):
    try:
        if extension_service.toggle(extension_id, enabled):
            return {"status": "success"}
        raise HTTPException(500, "Toggle failed")
    except PermissionError as e:
        raise HTTPException(403, str(e))


@mgmt_router.get("/{extension_id}/install-status")
async def get_install_status(extension_id: str):
    status = extension_service.manager.install_states.get(extension_id)
    if not status:
        ext = extension_service.manager.get_extension(extension_id)
        if ext:
            return {"status": "completed", "progress": 100, "error": None}
        return {"status": "idle", "progress": 0, "error": None}
    return status


@mgmt_router.get("/{extension_id}/logs")
async def get_logs(extension_id: str):
    return {
        "id": extension_id,
        "logs": extension_service.manager.get_extension_logs(extension_id),
    }


@mgmt_router.delete("/{extension_id}/logs")
async def clear_logs(extension_id: str):
    extension_service.manager.clear_extension_logs(extension_id)
    return {"status": "success"}


@runtime_router.get("/{extension_id}/ui")
async def get_ui(extension_id: str, token: str = Query(None)):
    ext_dir, manifest = _resolve_extension_path_and_manifest(extension_id)
    if not manifest:
        raise HTTPException(404, "Extension manifest not found")

    ui_entry = manifest.get("ui_entry")
    if not ui_entry:
        raise HTTPException(404, "UI entry point not specified")

    ui_p = (ext_dir / ui_entry).resolve()
    if not str(ui_p).startswith(str(ext_dir.resolve())) or not ui_p.exists():
        raise HTTPException(404, "UI entry file missing")

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
        raise HTTPException(404, "Extension not found")

    widgets = manifest.get("dashboard_widgets", [])
    widget = next((w for w in widgets if w.get("id") == widget_id), None)
    if not widget:
        raise HTTPException(404, "Widget not found")

    ui_entry = widget.get("ui_entry")
    if not ui_entry:
        raise HTTPException(404, "Widget UI entry missing")

    ui_p = (ext_dir / ui_entry).resolve()
    if not str(ui_p).startswith(str(ext_dir.resolve())) or not ui_p.exists():
        raise HTTPException(404, "Widget UI missing")

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
        raise HTTPException(404, "No icon specified in extension manifest")

    icon_p = (ext_dir / icon_rel).resolve()
    if not str(icon_p).startswith(str(ext_dir.resolve())) or not icon_p.exists():
        raise HTTPException(404, "Icon file not found")

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
    manager = extension_service.manager
    if extension_id not in manager.isolated_processes:
        raise HTTPException(
            status_code=404, detail=f"Extension '{extension_id}' not active"
        )

    body = None
    try:
        body = await request.json()
    except Exception:
        pass

    subpath_clean = "/" + subpath.lstrip("/")

    res = manager.dispatch_ipc_http_request(
        extension_id=extension_id,
        method=request.method,
        subpath=subpath_clean,
        body=body,
    )

    if not res:
        raise HTTPException(
            status_code=502, detail="Isolated extension process did not respond"
        )

    status_code = res.get("status_code", 200)
    content = res.get("content") or {"error": res.get("error")}

    return JSONResponse(content=content, status_code=status_code)
