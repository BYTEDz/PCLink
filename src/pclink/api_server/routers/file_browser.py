# src/pclink/api_server/routers/file_browser.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import gettext
import json
import logging
import mimetypes
import os
import subprocess
import sys
import urllib.parse
from typing import List, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from ...core.share_manager import share_manager
from ...services.file_service import HOME_DIR, file_service
from .dependencies import extract_token, verify_api_key, verify_web_session

log = logging.getLogger(__name__)
_ = gettext.gettext

router = APIRouter()

ROOT_IDENTIFIER = "_ROOT_"


# --- Models ---
class FileItem(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: int
    modified_at: float
    item_type: str
    duration: int | None = None


class DirectoryListing(BaseModel):
    current_path: str
    parent_path: str | None
    items: List[FileItem]


class PathPayload(BaseModel):
    path: str


class SharePayload(BaseModel):
    path: str
    expires_in: int | None = None


class RenamePayload(BaseModel):
    path: str
    new_name: str = Field(..., min_length=1)


class BatchRenameItem(BaseModel):
    path: str
    new_name: str | None = None
    target_path: str | None = None


class BatchRenamePayload(BaseModel):
    items: List[BatchRenameItem] = Field(..., min_length=1, max_length=10_000)


class CreateFolderPayload(BaseModel):
    parent_path: str
    folder_name: str = Field(..., min_length=1)


class PastePayload(BaseModel):
    source_paths: List[str] = Field(..., min_length=1, max_length=5_000)
    destination_path: str = Field(..., max_length=4096)
    action: Literal["cut", "copy"]
    conflict_resolution: Literal["skip", "overwrite", "rename"] = "skip"


class PathsPayload(BaseModel):
    paths: List[str] = Field(..., min_length=1, max_length=5_000)


class CompressPayload(BaseModel):
    file_paths: List[str] = Field(..., min_length=1)
    output_path: str


class ExtractPayload(BaseModel):
    zip_path: str
    destination: str
    password: str | None = None


# --- Helpers ---
async def verify_download_access(
    path: str = Query(...),
    token: str = Query(None),
    request: Request = None,
):
    """
    Custom dependency for file downloads.
    Allows access if:
    1. A valid device API key is provided.
    2. A valid share token for the specific path is provided.
    """
    try:
        from ...core.device_manager import device_manager

        key = extract_token(request, token=token)
        if key:
            device = device_manager.get_device_by_api_key(key)
            if device and device.is_approved:
                return True
    except Exception:
        pass

    if token and path:
        if share_manager.validate_share_token(token, path):
            return True

    raise HTTPException(status_code=403, detail=_("Invalid or missing access token"))


# --- Endpoints ---


@router.get(
    "/browse", response_model=DirectoryListing, dependencies=[Depends(verify_api_key)]
)
async def browse_directory(path: str | None = Query(None)):
    if not path or path == ROOT_IDENTIFIER:
        items = [
            FileItem(
                name=str(r),
                path=str(r),
                is_dir=True,
                size=0,
                modified_at=0,
                item_type="drive",
            )
            for r in file_service.get_system_roots()
        ]
        if HOME_DIR.exists():
            try:
                st = HOME_DIR.stat()
                items.append(
                    FileItem(
                        name="Home",
                        path=str(HOME_DIR),
                        is_dir=True,
                        size=st.st_size,
                        modified_at=st.st_mtime,
                        item_type="home",
                    )
                )
            except Exception:
                pass
        return DirectoryListing(
            current_path=ROOT_IDENTIFIER, parent_path=None, items=items
        )

    p = file_service.validate_path(path)
    items = await file_service.scan_directory(p)

    is_root = any(str(p) == str(r) for r in file_service.get_system_roots())
    parent = str(p.parent) if not is_root else ROOT_IDENTIFIER

    try:
        if HOME_DIR.exists() and p.samefile(HOME_DIR):
            parent = ROOT_IDENTIFIER
    except Exception:
        if p == HOME_DIR:
            parent = ROOT_IDENTIFIER

    return DirectoryListing(
        current_path=str(p),
        parent_path=parent,
        items=[FileItem(**i) for i in items],
    )


@router.get("/thumbnail", dependencies=[Depends(verify_api_key)])
async def get_thumbnail(path: str = Query(...)):
    p = file_service.validate_path(path)
    data = await file_service.get_thumbnail(p)
    if not data:
        raise FileNotFoundError(_("Thumbnail not available"))
    return Response(
        content=data,
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=604800, stale-while-revalidate=86400"
        },
    )


@router.get("/stream", dependencies=[Depends(verify_api_key)])
async def stream_media(request: Request, path: str = Query(...)):
    """Streams a media file with HTTP Range headers for seeking."""
    p = file_service.validate_path(path)
    if not p.is_file():
        raise FileNotFoundError(_("File or directory not found"))

    stat = p.stat()
    file_size = stat.st_size
    mime, _encoding = mimetypes.guess_type(p)
    content_type = mime or "application/octet-stream"

    range_header = request.headers.get("Range")
    start, end = 0, file_size - 1
    status_code = 200
    headers = {
        "Content-Type": content_type,
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size),
        "Content-Disposition": f'inline; filename="{urllib.parse.quote(p.name)}"',
    }

    if range_header:
        try:
            range_bytes = range_header.replace("bytes=", "").split("-")
            start = int(range_bytes[0])
            if range_bytes[1]:
                end = int(range_bytes[1])

            if start >= file_size or end >= file_size or start > end:
                raise HTTPException(416, _("Range Not Satisfiable"))

            status_code = 206
            chunk_size = (end - start) + 1
            headers["Content-Length"] = str(chunk_size)
            headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        except (ValueError, IndexError):
            raise HTTPException(400, _("Invalid Range header"))

    return StreamingResponse(
        file_service.get_file_iterator(p, start, end),
        status_code=status_code,
        headers=headers,
    )


@router.get("/media-info", dependencies=[Depends(verify_api_key)])
async def get_media_info(path: str = Query(...)):
    p = file_service.validate_path(path)
    info = await file_service.get_media_info(p)
    if not info:
        raise FileNotFoundError(_("Media info not available"))
    return info


@router.post("/compress", dependencies=[Depends(verify_api_key)])
async def compress(payload: CompressPayload):
    async def _stream():
        try:
            gen = await file_service.compress(payload.file_paths, payload.output_path)
            for prog in gen:
                yield f"data: {json.dumps({'progress': prog})}\n\n"
            yield f"data: {json.dumps({'status': 'complete', 'progress': 100})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.post("/extract", dependencies=[Depends(verify_api_key)])
async def extract(payload: ExtractPayload):
    async def _stream():
        try:
            p = file_service.validate_path(payload.zip_path)
            dest = file_service.validate_path(
                payload.destination, check_existence=False
            )
            gen = await file_service.extract(p, dest, payload.password)
            for prog in gen:
                yield f"data: {json.dumps({'progress': prog})}\n\n"
            yield f"data: {json.dumps({'status': 'complete', 'progress': 100})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.post("/create-folder", dependencies=[Depends(verify_api_key)])
async def create_folder(payload: CreateFolderPayload):
    await file_service.create_folder(payload.parent_path, payload.folder_name)
    return {"status": "success"}


@router.patch("/rename", dependencies=[Depends(verify_api_key)])
async def rename(payload: RenamePayload):
    await file_service.rename_item(payload.path, payload.new_name)
    return {"status": "success"}


@router.post("/batch-rename", dependencies=[Depends(verify_api_key)])
async def batch_rename(payload: BatchRenamePayload):
    return await file_service.batch_rename_items(payload.items)


@router.post("/delete", dependencies=[Depends(verify_api_key)])
async def delete(payload: PathsPayload):
    results = await file_service.delete_items(payload.paths)
    return {
        "succeeded": [r for r in results if r["success"]],
        "failed": [r for r in results if not r["success"]],
    }


@router.post("/open", dependencies=[Depends(verify_api_key)])
async def open_file(payload: PathPayload):
    p = file_service.validate_path(payload.path)
    if sys.platform == "win32":
        await asyncio.to_thread(os.startfile, p)
    elif sys.platform == "darwin":
        subprocess.Popen(
            ["open", str(p)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    else:
        subprocess.Popen(
            ["xdg-open", str(p)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    return {"status": "success"}


@router.post("/paste", dependencies=[Depends(verify_api_key)])
async def paste(payload: PastePayload):
    dest = file_service.validate_path(payload.destination_path)
    if not dest.is_dir():
        raise NotADirectoryError(_("Destination path must be a directory"))

    res = await file_service.move_copy(
        payload.source_paths, dest, payload.action, payload.conflict_resolution
    )
    if res["conflicts"]:
        raise HTTPException(
            409, {"message": "Conflicts", "conflicting_items": res["conflicts"]}
        )
    return res


@router.get("/shares", dependencies=[Depends(verify_api_key)])
async def list_shares(request: Request):
    """List all active share links. Web sessions see all, devices see only their own."""
    from ...core.device_manager import device_manager

    is_web = False
    try:
        if await verify_web_session(request):
            is_web = True
    except Exception:
        pass

    device_id = None
    if not is_web:
        key = extract_token(request)
        device_id = "unknown_device"
        if key:
            device = device_manager.get_device_by_api_key(key)
            if device:
                device_id = device.device_id

    shares = share_manager.list_shares_for_device(None if is_web else device_id)

    for s in shares:
        d_id = s.get("device_id")
        if d_id == "unknown_device":
            s["device_name"] = "Web UI"
        else:
            dev = device_manager.get_device_by_id(d_id) if d_id else None
            s["device_name"] = dev.device_name if dev else (d_id or "Web UI")

    return {"shares": shares}


@router.delete("/shares/{share_token}", dependencies=[Depends(verify_api_key)])
async def revoke_share(share_token: str, request: Request):
    """Revoke a specific share token. Web sessions can revoke any, devices only their own."""
    from ...core.device_manager import device_manager

    is_web = False
    try:
        if await verify_web_session(request):
            is_web = True
    except Exception:
        pass

    if not is_web:
        key = extract_token(request)
        device_id = "unknown_device"
        if key:
            device = device_manager.get_device_by_api_key(key)
            if device:
                device_id = device.device_id

        shares = share_manager.list_shares_for_device(device_id)
        owned = any(s["token"] == share_token for s in shares)
        if not owned:
            with share_manager._lock:
                import sqlite3 as _sqlite3

                with _sqlite3.connect(share_manager.db_path) as conn:
                    row = conn.execute(
                        "SELECT device_id FROM shared_links WHERE token = ?",
                        (share_token,),
                    ).fetchone()
                    if not row or row[0] != device_id:
                        raise HTTPException(
                            status_code=404, detail=_("Share token not found")
                        )

    share_manager.revoke_share_link(share_token)
    return {"status": "revoked"}


@router.post("/share", response_model=dict, dependencies=[Depends(verify_api_key)])
async def share_file(payload: SharePayload, request: Request):
    from ...core.device_manager import device_manager

    file_service.validate_path(payload.path)
    key = extract_token(request)

    device_id = "unknown_device"
    if key:
        device = device_manager.get_device_by_api_key(key)
        if device:
            device_id = device.device_id

    token = share_manager.create_share_link(
        path=payload.path, device_id=device_id, expires_in=payload.expires_in
    )

    base_url = str(request.base_url).rstrip("/")
    download_url = f"{base_url}/files/download?path={payload.path}&token={token}"

    return {
        "token": token,
        "download_url": download_url,
        "expires_in": payload.expires_in,
    }


@router.get("/download", dependencies=[Depends(verify_download_access)])
async def download(path: str = Query(...)):
    p = file_service.validate_path(path)
    if not p.is_file():
        raise ValueError(_("Requested path is not a file"))

    return FileResponse(
        path=str(p), filename=p.name, content_disposition_type="attachment"
    )
