# src/pclink/api_server/extension_router.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import os
import shutil
import tempfile
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File, Query
from fastapi.responses import FileResponse
from ..services.extension_service import extension_service

mgmt_router = APIRouter(tags=["extension-management"])
runtime_router = APIRouter(tags=["extension-runtime"])

@mgmt_router.get("/")
@mgmt_router.get("")
async def list_extensions():
    return extension_service.list_extensions()

@mgmt_router.post("/install")
async def install_extension(file: UploadFile = File(...)):
    if not file.filename.endswith(".zip"): raise HTTPException(400, "Only .zip allowed")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_p = Path(tmp.name)
    try:
        if extension_service.install(tmp_p): return {"status": "success"}
        raise HTTPException(400, "Install failed")
    except PermissionError as e: raise HTTPException(403, str(e))
    finally:
        if tmp_p.exists(): os.unlink(tmp_p)

@mgmt_router.delete("/{extension_id}")
async def delete_extension(extension_id: str):
    try:
        if extension_service.uninstall(extension_id): return {"status": "success"}
        raise HTTPException(500, "Delete failed")
    except PermissionError as e: raise HTTPException(403, str(e))

@mgmt_router.post("/{extension_id}/toggle")
async def toggle_extension(extension_id: str, enabled: bool):
    try:
        if extension_service.toggle(extension_id, enabled): return {"status": "success"}
        raise HTTPException(500, "Toggle failed")
    except PermissionError as e: raise HTTPException(403, str(e))

@mgmt_router.get("/{extension_id}/logs")
async def get_logs(extension_id: str):
    return {"id": extension_id, "logs": extension_service.manager.get_extension_logs(extension_id)}

@mgmt_router.delete("/{extension_id}/logs")
async def clear_logs(extension_id: str):
    extension_service.manager.clear_extension_logs(extension_id)
    return {"status": "success"}

@runtime_router.get("/{extension_id}/ui")
async def get_ui(extension_id: str, token: str = Query(None)):
    ext = extension_service.manager.get_extension(extension_id)
    if not ext: raise HTTPException(404, "Not found")
    ui_p = ext.extension_path / ext.metadata.ui_entry
    if not ui_p.exists(): raise HTTPException(404, "UI missing")
    res = FileResponse(ui_p, media_type="text/html")
    res.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    res.headers["Pragma"] = "no-cache"
    if token: res.set_cookie("pclink_device_token", token, max_age=3600, httponly=True, samesite="lax", path="/")
    return res

@runtime_router.get("/{extension_id}/widget/{widget_id}")
async def get_widget_ui(extension_id: str, widget_id: str, token: str = Query(None)):
    ext = extension_service.manager.get_extension(extension_id)
    if not ext: raise HTTPException(404, "Extension not found")
    
    # Find the widget in metadata
    widget = next((w for w in ext.metadata.dashboard_widgets if w.id == widget_id), None)
    if not widget: raise HTTPException(404, "Widget not found")
    
    ui_p = (ext.extension_path / widget.ui_entry).resolve()
    # Security: Ensure it's inside the extension path
    if not str(ui_p).startswith(str(ext.extension_path.resolve())): raise HTTPException(403)
    if not ui_p.exists(): raise HTTPException(404, "Widget UI missing")
    
    res = FileResponse(ui_p, media_type="text/html")
    res.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    res.headers["Pragma"] = "no-cache"
    if token: res.set_cookie("pclink_device_token", token, max_age=3600, httponly=True, samesite="lax", path="/")
    return res

@runtime_router.get("/{extension_id}/icon")
async def get_icon(extension_id: str):
    ext = extension_service.manager.get_extension(extension_id)
    if not ext or not ext.metadata.icon: raise HTTPException(404, "No icon")
    icon_p = (ext.extension_path / ext.metadata.icon).resolve()
    if not str(icon_p).startswith(str(ext.extension_path.resolve())): raise HTTPException(403)
    return FileResponse(icon_p)

@runtime_router.get("/{extension_id}/static/{file_path:path}")
async def get_static(extension_id: str, file_path: str):
    ext = extension_service.manager.get_extension(extension_id)
    if not ext: raise HTTPException(404)
    base = ext.get_static_path().resolve()
    target = (base / file_path).resolve()
    if not str(target).startswith(str(base)) or not target.is_file(): raise HTTPException(403 if target.exists() else 404)
    return FileResponse(target)

def mount_extension_routes(app, dependencies=None):
    for eid, ext in extension_service.manager.extensions.items():
        if eid not in extension_service.manager._mounted_extensions:
            try:
                app.include_router(ext.get_routes(), prefix=f"/extensions/{eid}", tags=[f"ext-{eid}"], dependencies=dependencies)
                extension_service.manager._mounted_extensions.add(eid)
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Error mounting {eid} on startup: {e}")
