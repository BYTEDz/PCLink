import asyncio
import time
import uuid
import logging
import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Header, Depends
from fastapi.responses import StreamingResponse

from ..file_browser import _validate_and_resolve_path, _encode_filename_for_header
from .models import DownloadInitiatePayload, DownloadInitiateResponse, DownloadStatusResponse
from .session import (
    ACTIVE_DOWNLOADS, DOWNLOAD_SESSION_DIR, AIOFILES_INSTALLED, 
    DOWNLOAD_CHUNK_SIZE, get_client_id, manage_session_file, 
    verify_session_ownership, cleanup_transfer_session
)

if AIOFILES_INSTALLED:
    import aiofiles

log = logging.getLogger(__name__)
download_router = APIRouter()

@download_router.get("/config")
async def get_download_config():
    return {
        "recommended_chunk_size": DOWNLOAD_CHUNK_SIZE,
        "supports_resume": True,
        "aiofiles_enabled": AIOFILES_INSTALLED
    }

@download_router.post("/initiate")
async def initiate_download(payload: DownloadInitiatePayload, client_id: str = Depends(get_client_id)):
    path = _validate_and_resolve_path(payload.file_path)
    if not path.is_file(): raise HTTPException(404, "File not found")
    
    download_id = str(uuid.uuid4())
    stat = path.stat()
    
    session = {
        "client_id": client_id,
        "file_path": str(path),
        "file_name": path.name,
        "file_size": stat.st_size,
        "file_modified_at": stat.st_mtime,
        "bytes_downloaded": 0,
        "status": "active",
        "session_created_at": time.time()
    }
    
    ACTIVE_DOWNLOADS[client_id][download_id] = session
    await asyncio.to_thread(manage_session_file, download_id, session, "save", "download")
    
    return DownloadInitiateResponse(
        download_id=download_id, file_size=stat.st_size, file_name=path.name
    )

@download_router.get("/status/{download_id}", response_model=DownloadStatusResponse)
async def get_download_status(download_id: str, client_id: str = Depends(get_client_id)):
    info = ACTIVE_DOWNLOADS.get(client_id, {}).get(download_id)
    if not info:
        info = manage_session_file(download_id, operation="read", session_type="download")
        if not info or not verify_session_ownership(info, client_id):
            raise HTTPException(404, "Download session not found")
        ACTIVE_DOWNLOADS[client_id][download_id] = info

    progress = (info["bytes_downloaded"] / info["file_size"]) * 100 if info["file_size"] > 0 else 0
    return DownloadStatusResponse(
        download_id=download_id, file_size=info["file_size"],
        bytes_downloaded=info["bytes_downloaded"], progress_percent=round(progress, 2),
        status=info["status"]
    )

@download_router.get("/chunk/{download_id}")
async def download_chunk(
    download_id: str, range_header: str = Header(None, alias="Range"), 
    client_id: str = Depends(get_client_id)
):
    # Try memory cache first, then disk
    info = ACTIVE_DOWNLOADS.get(client_id, {}).get(download_id)
    if not info:
        info = manage_session_file(download_id, operation="read", session_type="download")
        if not info or not verify_session_ownership(info, client_id):
            raise HTTPException(404, "Download session not found")
        ACTIVE_DOWNLOADS[client_id][download_id] = info

    path = Path(info["file_path"])
    if not path.exists(): raise HTTPException(404, "File missing")

    file_size = info["file_size"]
    start, end = 0, file_size - 1
    
    if range_header:
        try:
            parts = range_header.replace("bytes=", "").split("-")
            start = int(parts[0])
            if len(parts) > 1 and parts[1]: end = int(parts[1])
        except:
            raise HTTPException(400, "Invalid Range")
            
    chunk_len = (end - start) + 1
    
    async def iterfile():
        try:
            if AIOFILES_INSTALLED:
                async with aiofiles.open(path, "rb") as f:
                    await f.seek(start)
                    left = chunk_len
                    while left > 0:
                        chunk = await f.read(min(DOWNLOAD_CHUNK_SIZE, left))
                        if not chunk: break
                        left -= len(chunk)
                        yield chunk
            else:
                with path.open("rb") as f:
                    f.seek(start)
                    left = chunk_len
                    while left > 0:
                        chunk = f.read(min(DOWNLOAD_CHUNK_SIZE, left))
                        if not chunk: break
                        left -= len(chunk)
                        yield chunk
            
            # Update progress loosely (approx) to avoid disk thrashing
            info["bytes_downloaded"] = max(info["bytes_downloaded"], end + 1)
            # We don't save to disk on every chunk read for performance
            
        except Exception as e:
            log.error(f"Stream error: {e}")

    return StreamingResponse(
        iterfile(), status_code=206, 
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(chunk_len),
            "Content-Disposition": _encode_filename_for_header(info["file_name"])
        }
    )

@download_router.post("/pause/{download_id}")
async def pause_download(download_id: str, client_id: str = Depends(get_client_id)):
    info = ACTIVE_DOWNLOADS.get(client_id, {}).get(download_id)
    if not info:
        info = manage_session_file(download_id, operation="read", session_type="download")
        if not info or not verify_session_ownership(info, client_id):
            raise HTTPException(404, "Download session not found")
        ACTIVE_DOWNLOADS[client_id][download_id] = info
    
    info["status"] = "paused"
    manage_session_file(download_id, info, "save", "download")
    return {"status": "paused", "download_id": download_id}

@download_router.post("/resume/{download_id}")
async def resume_download(download_id: str, client_id: str = Depends(get_client_id)):
    info = ACTIVE_DOWNLOADS.get(client_id, {}).get(download_id)
    if not info:
        info = manage_session_file(download_id, operation="read", session_type="download")
        if not info or not verify_session_ownership(info, client_id):
            raise HTTPException(404, "Download session not found")
        ACTIVE_DOWNLOADS[client_id][download_id] = info
    
    info["status"] = "active"
    manage_session_file(download_id, info, "save", "download")
    return {"status": "resumed", "download_id": download_id, "resume_offset": info["bytes_downloaded"]}

@download_router.post("/complete/{download_id}")
async def complete_download(download_id: str, bg_tasks: BackgroundTasks, client_id: str = Depends(get_client_id)):
    # Just cleanup session, client has the file
    if client_id in ACTIVE_DOWNLOADS:
        ACTIVE_DOWNLOADS[client_id].pop(download_id, None)
    
    manage_session_file(download_id, operation="delete", session_type="download")
    bg_tasks.add_task(cleanup_transfer_session, download_id)
    return {"status": "completed"}

@download_router.delete("/cancel/{download_id}")
async def cancel_download(download_id: str, bg_tasks: BackgroundTasks, client_id: str = Depends(get_client_id)):
    if client_id in ACTIVE_DOWNLOADS:
        ACTIVE_DOWNLOADS[client_id].pop(download_id, None)
    
    manage_session_file(download_id, operation="delete", session_type="download")
    bg_tasks.add_task(cleanup_transfer_session, download_id)
    return {"status": "cancelled"}

@download_router.get("/list-active")
async def list_active_downloads(client_id: str = Depends(get_client_id)):
    active = []
    # From Memory
    for did, info in ACTIVE_DOWNLOADS.get(client_id, {}).items():
        active.append({
            "download_id": did,
            "file_name": info["file_name"],
            "status": info["status"],
            "progress": (info["bytes_downloaded"] / info["file_size"]) * 100 if info["file_size"] else 0
        })
    
    # From Disk (if not in memory)
    seen = {x["download_id"] for x in active}
    for sess_file in DOWNLOAD_SESSION_DIR.glob("*.json"):
        if sess_file.stem in seen: continue
        try:
            data = json.loads(sess_file.read_text(encoding="utf-8"))
            if data.get("client_id") == client_id:
                 active.append({
                    "download_id": sess_file.stem,
                    "file_name": data["file_name"],
                    "status": data.get("status", "paused"),
                    "progress": (data["bytes_downloaded"] / data["file_size"]) * 100 if data["file_size"] else 0
                 })
        except: pass
        
    return {"active_downloads": active}