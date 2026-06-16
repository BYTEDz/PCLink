# src/pclink/api_server/extension_router.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import os
import shutil
import tempfile
import urllib.request
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from ...services.extension_service import extension_service

mgmt_router = APIRouter(tags=["extension-management"])
runtime_router = APIRouter(tags=["extension-runtime"])


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

    def download_and_install():
        manager = extension_service.manager
        manager.install_states[task_id] = {
            "status": "downloading",
            "progress": 0,
            "error": None,
        }
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
    ext = extension_service.manager.get_extension(extension_id)
    if not ext:
        raise HTTPException(404, "Not found")
    ui_p = ext.extension_path / ext.metadata.ui_entry
    if not ui_p.exists():
        raise HTTPException(404, "UI missing")
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
    ext = extension_service.manager.get_extension(extension_id)
    if not ext:
        raise HTTPException(404, "Extension not found")

    # Find the widget in metadata
    widget = next(
        (w for w in ext.metadata.dashboard_widgets if w.id == widget_id), None
    )
    if not widget:
        raise HTTPException(404, "Widget not found")

    ui_p = (ext.extension_path / widget.ui_entry).resolve()
    # Security: Ensure it's inside the extension path
    if not str(ui_p).startswith(str(ext.extension_path.resolve())):
        raise HTTPException(403)
    if not ui_p.exists():
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


@runtime_router.get("/{extension_id}/icon")
async def get_icon(extension_id: str):
    ext = extension_service.manager.get_extension(extension_id)
    if not ext or not ext.metadata.icon:
        raise HTTPException(404, "No icon")
    icon_p = (ext.extension_path / ext.metadata.icon).resolve()
    if not str(icon_p).startswith(str(ext.extension_path.resolve())):
        raise HTTPException(403)
    return FileResponse(icon_p)


@runtime_router.get("/{extension_id}/static/{file_path:path}")
async def get_static(extension_id: str, file_path: str):
    ext = extension_service.manager.get_extension(extension_id)
    if not ext:
        raise HTTPException(404)
    base = ext.get_static_path().resolve()
    target = (base / file_path).resolve()
    if not str(target).startswith(str(base)) or not target.is_file():
        raise HTTPException(403 if target.exists() else 404)
    return FileResponse(target)


def mount_extension_routes(app, dependencies=None):
    for eid, ext in extension_service.manager.extensions.items():
        if eid not in extension_service.manager._mounted_extensions:
            try:
                app.include_router(
                    ext.get_routes(),
                    prefix=f"/extensions/{eid}",
                    tags=[f"ext-{eid}"],
                    dependencies=dependencies,
                )
                extension_service.manager._mounted_extensions.add(eid)
            except Exception as e:
                import logging

                logging.getLogger(__name__).error(
                    f"Error mounting {eid} on startup: {e}"
                )
