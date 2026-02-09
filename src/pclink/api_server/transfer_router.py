# src/pclink/api_server/transfer_router.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
import urllib.parse
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.requests import ClientDisconnect

from ..core.device_manager import device_manager
from ..core.validators import validate_api_key
from ..services.transfer_service import transfer_service, UPLOAD_CHUNK_SIZE, UPLOAD_BUFFER_SIZE, DOWNLOAD_CHUNK_SIZE, AIOFILES_INSTALLED
from ..services.file_service import file_service

log = logging.getLogger(__name__)

upload_router = APIRouter()
download_router = APIRouter()

# --- Auth Helper ---
def get_client_id(
    x_api_key: str = Header(None), 
    token: str = Query(None),
    request: Request = None
) -> str:
    key = x_api_key or token
    if not key and request:
        key = request.cookies.get("pclink_device_token")
    
    if not key:
        raise HTTPException(401, "Missing API Key")

    try:
        from ..api_server.api import create_api_app # Circular import workaround if needed, or better fetch from app state
        # Actually, simpler: check device manager directly.
        # But for 'server' uploads we need to know if it's the master key.
        pass
    except: pass
    
    # Check device manager
    dev = device_manager.get_device_by_api_key(key)
    if dev: return dev.device_id
    
    # Master key - use the key itself as client ID for session tracking
    return key

# --- Models ---
class UploadInitiatePayload(BaseModel):
    file_name: str
    destination_path: str
    file_size: int | None = None
    conflict_resolution: Literal["abort", "overwrite", "keep_both"] = "abort"

class UploadInitiateResponse(BaseModel):
    upload_id: str
    final_file_name: str | None = None

class DownloadInitiatePayload(BaseModel):
    file_path: str

class DownloadInitiateResponse(BaseModel):
    download_id: str; file_size: int; file_name: str

class DownloadStatusResponse(BaseModel):
    download_id: str; file_size: int; bytes_downloaded: int; progress_percent: float; status: str

def _encode_filename(filename: str) -> str:
    quoted = urllib.parse.quote(filename)
    return f'attachment; filename="{filename}"; filename*=UTF-8\'\'{quoted}'

# --- UPLOAD ENDPOINTS ---

@upload_router.get("/config")
async def get_upload_config():
    return {
        "recommended_chunk_size": UPLOAD_CHUNK_SIZE,
        "max_chunk_size": UPLOAD_CHUNK_SIZE * 4,
        "buffer_size": UPLOAD_BUFFER_SIZE,
        "supports_concurrent_chunks": True,
        "supports_resume": True
    }

@upload_router.post("/initiate", response_model=UploadInitiateResponse)
async def initiate_upload(payload: UploadInitiatePayload, client_id: str = Depends(get_client_id)):
    try:
        res = await transfer_service.initiate_upload(
            client_id, payload.destination_path, payload.file_name, 
            payload.file_size or 0, payload.conflict_resolution
        )
        return UploadInitiateResponse(**res)
    except ValueError as e: raise HTTPException(400, str(e))
    except FileExistsError as e: raise HTTPException(409, str(e))
    except Exception as e: 
        log.error(f"Init upload failed: {e}")
        raise HTTPException(500, str(e))

@upload_router.get("/status/{upload_id}")
async def get_upload_status(upload_id: str, client_id: str = Depends(get_client_id)):
    meta = transfer_service.manage_session(upload_id, op="read", type="upload")
    if not meta or not transfer_service.verify_ownership(meta, client_id):
        raise HTTPException(404, "Upload not found")
    
    _, part = transfer_service._get_files(upload_id, "upload")
    received = part.stat().st_size if part.exists() else 0
    return {
        "upload_id": upload_id, "bytes_received": received, 
        "status": meta.get("status"), "expected_size": meta.get("file_size")
    }

@upload_router.post("/chunk/{upload_id}")
async def upload_chunk(upload_id: str, request: Request, offset: int = Query(...), client_id: str = Depends(get_client_id)):
    meta = transfer_service.manage_session(upload_id, op="read", type="upload")
    if not meta or not transfer_service.verify_ownership(meta, client_id):
        raise HTTPException(404, "Upload not found")

    data = bytearray()
    try:
        async for chunk in request.stream(): data.extend(chunk)
    except ClientDisconnect:
        return {"status": "interrupted"}

    return await transfer_service.write_chunk(upload_id, offset, bytes(data))

@upload_router.post("/complete/{upload_id}")
async def complete_upload(upload_id: str, bg_tasks: BackgroundTasks, client_id: str = Depends(get_client_id)):
    try:
        path = await transfer_service.complete_upload(upload_id)
        return {"status": "completed", "path": path}
    except ValueError as e: raise HTTPException(400, str(e))
    except Exception as e:
        log.error(f"Upload completion failed: {e}")
        raise HTTPException(500, str(e))

@upload_router.delete("/cancel/{upload_id}")
async def cancel_upload(upload_id: str, bg_tasks: BackgroundTasks, client_id: str = Depends(get_client_id)):
    meta = transfer_service.manage_session(upload_id, op="read", type="upload")
    if meta and transfer_service.verify_ownership(meta, client_id):
        pass # Owned
    
    cid = meta.get("client_id") if meta else None
    if cid and cid in transfer_service.active_uploads:
        path = meta.get("final_path")
        if path: transfer_service.active_uploads[cid].pop(path, None)

    bg_tasks.add_task(transfer_service.cleanup_session, upload_id, "upload")
    return {"status": "cancelled"}


# --- DOWNLOAD ENDPOINTS ---

@download_router.get("/config")
async def get_download_config():
    return {
        "recommended_chunk_size": DOWNLOAD_CHUNK_SIZE,
        "supports_resume": True
    }

@download_router.post("/initiate", response_model=DownloadInitiateResponse)
async def initiate_download(payload: DownloadInitiatePayload, client_id: str = Depends(get_client_id)):
    try:
        res = await transfer_service.initiate_download(client_id, payload.file_path)
        return DownloadInitiateResponse(**res)
    except FileNotFoundError: raise HTTPException(404, "File not found")
    except Exception as e: raise HTTPException(500, str(e))

@download_router.get("/status/{download_id}", response_model=DownloadStatusResponse)
async def get_download_status(download_id: str, client_id: str = Depends(get_client_id)):
    info = transfer_service.active_downloads.get(client_id, {}).get(download_id)
    if not info:
        info = transfer_service.manage_session(download_id, op="read", type="download")
        if not info or not transfer_service.verify_ownership(info, client_id):
            raise HTTPException(404, "Session not found")
        transfer_service.active_downloads[client_id][download_id] = info
        
    prog = (info["bytes_downloaded"] / info["file_size"]) * 100 if info["file_size"] else 0
    return DownloadStatusResponse(
        download_id=download_id, file_size=info["file_size"],
        bytes_downloaded=info["bytes_downloaded"], progress_percent=round(prog, 2),
        status=info["status"]
    )

@download_router.get("/chunk/{download_id}")
async def download_chunk(download_id: str, range_header: str = Header(None, alias="Range"), client_id: str = Depends(get_client_id)):
    info = transfer_service.active_downloads.get(client_id, {}).get(download_id)
    if not info:
        info = transfer_service.manage_session(download_id, op="read", type="download")
        if not info or not transfer_service.verify_ownership(info, client_id): raise HTTPException(404, "Session not found")
        transfer_service.active_downloads[client_id][download_id] = info

    path = Path(info["file_path"])
    fsize = info["file_size"]
    start, end = 0, fsize - 1
    
    if range_header:
        try:
            p = range_header.replace("bytes=", "").split("-")
            start = int(p[0])
            if len(p) > 1 and p[1]: end = int(p[1])
        except: raise HTTPException(400, "Invalid Range")

    chunk_len = (end - start) + 1
    info["bytes_downloaded"] = max(info["bytes_downloaded"], end + 1)
    
    return StreamingResponse(
        file_service.get_file_iterator(path, start, end, chunk_size=DOWNLOAD_CHUNK_SIZE),
        status_code=206,
        headers={
            "Content-Range": f"bytes {start}-{end}/{fsize}",
            "Content-Length": str(chunk_len),
            "Content-Disposition": _encode_filename(info["file_name"])
        }
    )

@download_router.delete("/cancel/{download_id}")
async def cancel_download(download_id: str, bg_tasks: BackgroundTasks, client_id: str = Depends(get_client_id)):
    if client_id in transfer_service.active_downloads:
        transfer_service.active_downloads[client_id].pop(download_id, None)
    
    bg_tasks.add_task(transfer_service.cleanup_session, download_id, "download")
    return {"status": "cancelled"}

# Helper router setup
def restore_sessions_startup():
    return transfer_service.restore_sessions()

async def cleanup_stale_sessions(days=7):
    return await transfer_service.cleanup_stale_sessions(days)
