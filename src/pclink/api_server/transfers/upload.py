import asyncio
import shutil
import time
import uuid
import logging
import json
from pathlib import Path

# UPDATED: Import ClientDisconnect to handle pauses/cancellations gracefully
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, Depends
from starlette.requests import ClientDisconnect 

from ...core.validators import validate_filename
from ..file_browser import _validate_and_resolve_path, _get_unique_filename

from .models import UploadInitiatePayload, UploadInitiateResponse
from .session import (
    ACTIVE_UPLOADS, TRANSFER_LOCKS, CHUNK_BUFFERS, NEXT_WRITE_OFFSET, 
    UPLOAD_BUFFERS, TEMP_UPLOAD_DIR, AIOFILES_INSTALLED, UPLOAD_CHUNK_SIZE, 
    UPLOAD_BUFFER_SIZE, get_client_id, manage_session_file, 
    verify_session_ownership, cleanup_transfer_session, restore_sessions
)

if AIOFILES_INSTALLED:
    import aiofiles

log = logging.getLogger(__name__)
upload_router = APIRouter()

@upload_router.get("/config")
async def get_upload_config():
    return {
        "recommended_chunk_size": UPLOAD_CHUNK_SIZE,
        "max_chunk_size": UPLOAD_CHUNK_SIZE * 4,
        "min_chunk_size": 65536,
        "buffer_size": UPLOAD_BUFFER_SIZE,
        "supports_concurrent_chunks": True,
        "max_concurrent_chunks": 4,
        "supports_resume": True,
        "aiofiles_enabled": AIOFILES_INSTALLED
    }

@upload_router.post("/initiate")
async def initiate_upload(payload: UploadInitiatePayload, client_id: str = Depends(get_client_id)):
    dest_path = _validate_and_resolve_path(payload.destination_path)
    if not dest_path.is_dir():
        raise HTTPException(status_code=400, detail="Destination is not a directory")
    
    safe_filename = validate_filename(payload.file_name)
    final_file_path = dest_path / safe_filename
    
    if final_file_path.exists():
        if payload.conflict_resolution == "abort":
            raise HTTPException(status_code=409, detail="File exists")
        elif payload.conflict_resolution == "keep_both":
            final_file_path = _get_unique_filename(final_file_path)
            
    final_path_str = str(final_file_path)
    async with TRANSFER_LOCKS[f"init_{final_path_str}"]:
        # Resume check
        if final_path_str in ACTIVE_UPLOADS.get(client_id, {}):
            existing_id = ACTIVE_UPLOADS[client_id][final_path_str]
            if (TEMP_UPLOAD_DIR / f"{existing_id}.part").exists():
                return UploadInitiateResponse(upload_id=existing_id, final_file_name=final_file_path.name)
        
        # New Session
        upload_id = str(uuid.uuid4())
        metadata = {
            "client_id": client_id,
            "final_path": final_path_str,
            "file_name": final_file_path.name,
            "created_at": time.time(),
            "file_size": payload.file_size,
            "status": "active"
        }
        manage_session_file(upload_id, metadata, "save", "upload")
        (TEMP_UPLOAD_DIR / f"{upload_id}.part").write_bytes(b"")
        
        ACTIVE_UPLOADS[client_id][final_path_str] = upload_id
        NEXT_WRITE_OFFSET[upload_id] = 0
        CHUNK_BUFFERS[upload_id] = {}
        
        return UploadInitiateResponse(upload_id=upload_id, final_file_name=final_file_path.name)

@upload_router.get("/status/{upload_id}")
async def get_upload_status(upload_id: str, client_id: str = Depends(get_client_id)):
    metadata = manage_session_file(upload_id, operation="read", session_type="upload")
    if not metadata or not verify_session_ownership(metadata, client_id):
        raise HTTPException(status_code=404, detail="Upload not found")
        
    part_file = TEMP_UPLOAD_DIR / f"{upload_id}.part"
    if not part_file.exists():
        raise HTTPException(status_code=404, detail="Upload data missing")

    bytes_received = part_file.stat().st_size
    return {
        "upload_id": upload_id,
        "bytes_received": bytes_received,
        "status": metadata.get("status", "active"),
        "expected_size": metadata.get("file_size")
    }

@upload_router.post("/chunk/{upload_id}")
async def upload_chunk(
    upload_id: str, request: Request, offset: int = Query(...), 
    client_id: str = Depends(get_client_id)
):
    metadata = manage_session_file(upload_id, operation="read", session_type="upload")
    if not metadata or not verify_session_ownership(metadata, client_id):
        raise HTTPException(status_code=404, detail="Upload not found")

    chunk_data = bytearray()
    
    # FIX: Handle client disconnection (Pause/Cancel) gracefully
    try:
        async for chunk in request.stream():
            chunk_data.extend(chunk)
    except ClientDisconnect:
        log.info(f"Client disconnected during chunk upload {upload_id} (likely paused)")
        return {"status": "interrupted"} # Stops processing immediately

    async with TRANSFER_LOCKS[upload_id]:
        if upload_id not in CHUNK_BUFFERS: CHUNK_BUFFERS[upload_id] = {}
        
        # Crash recovery for offset
        if upload_id not in NEXT_WRITE_OFFSET:
            part_file = TEMP_UPLOAD_DIR / f"{upload_id}.part"
            NEXT_WRITE_OFFSET[upload_id] = part_file.stat().st_size if part_file.exists() else 0

        expected = NEXT_WRITE_OFFSET[upload_id]
        if offset < expected: return {"status": "ignored"} # Duplicate

        CHUNK_BUFFERS[upload_id][offset] = bytes(chunk_data)
        
        # Flush sequential
        part_file = TEMP_UPLOAD_DIR / f"{upload_id}.part"
        written = 0
        curr = expected
        
        while curr in CHUNK_BUFFERS[upload_id]:
            data = CHUNK_BUFFERS[upload_id].pop(curr)
            if AIOFILES_INSTALLED:
                async with aiofiles.open(part_file, "ab") as f: await f.write(data)
            else:
                await asyncio.to_thread(lambda: part_file.open("ab").write(data))
            written += len(data)
            curr += len(data)
        
        NEXT_WRITE_OFFSET[upload_id] = curr
        return {"status": "received", "bytes_written": written, "next_offset": curr}

@upload_router.post("/complete/{upload_id}")
async def complete_upload(
    upload_id: str, bg_tasks: BackgroundTasks, client_id: str = Depends(get_client_id)
):
    metadata = manage_session_file(upload_id, operation="read", session_type="upload")
    if not metadata or not verify_session_ownership(metadata, client_id):
        raise HTTPException(status_code=404, detail="Upload not found")
        
    async with TRANSFER_LOCKS[upload_id]:
        final_path = Path(metadata["final_path"])
        part_file = TEMP_UPLOAD_DIR / f"{upload_id}.part"
        
        # Check incomplete buffer
        if CHUNK_BUFFERS.get(upload_id):
            raise HTTPException(status_code=400, detail="Missing chunks, cannot complete")

        # Size check
        if (exp := metadata.get("file_size")) and part_file.stat().st_size != exp:
             raise HTTPException(status_code=400, detail="Size mismatch")

        try:
            await asyncio.to_thread(final_path.parent.mkdir, parents=True, exist_ok=True)
            if final_path.exists(): final_path.unlink()
            await asyncio.to_thread(shutil.move, str(part_file), str(final_path))
        except Exception as e:
            log.error(f"Move failed: {e}")
            raise HTTPException(500, f"Completion failed: {e}")
        
        # Cleanup
        if client_id in ACTIVE_UPLOADS:
            ACTIVE_UPLOADS[client_id].pop(str(final_path), None)
        manage_session_file(upload_id, operation="delete", session_type="upload")
        bg_tasks.add_task(cleanup_transfer_session, upload_id)
        
    return {"status": "completed", "path": str(final_path)}

@upload_router.post("/pause/{upload_id}")
async def pause_upload(upload_id: str, client_id: str = Depends(get_client_id)):
    metadata = manage_session_file(upload_id, operation="read", session_type="upload")
    if not metadata or not verify_session_ownership(metadata, client_id):
        raise HTTPException(status_code=404, detail="Upload not found")
    
    metadata["status"] = "paused"
    manage_session_file(upload_id, metadata, "save", "upload")
    return {"status": "paused", "upload_id": upload_id}

@upload_router.delete("/cancel/{upload_id}")
async def cancel_upload(
    upload_id: str, bg_tasks: BackgroundTasks, client_id: str = Depends(get_client_id)
):
    metadata = manage_session_file(upload_id, operation="read", session_type="upload")
    if metadata and verify_session_ownership(metadata, client_id):
        path = metadata.get("final_path")
        if path and client_id in ACTIVE_UPLOADS:
             ACTIVE_UPLOADS[client_id].pop(path, None)
             
    manage_session_file(upload_id, operation="delete", session_type="upload")
    bg_tasks.add_task(cleanup_transfer_session, upload_id)
    return {"status": "cancelled"}

@upload_router.get("/list-active")
async def list_active_uploads(client_id: str = Depends(get_client_id)):
    active = []
    # From Memory
    for uid, uid_str in ACTIVE_UPLOADS.get(client_id, {}).items():
        # ACTIVE_UPLOADS stores {final_path: upload_id}
        # We need to look up metadata
        try:
             metadata = manage_session_file(uid_str, operation="read", session_type="upload")
             if metadata:
                 part_file = TEMP_UPLOAD_DIR / f"{uid_str}.part"
                 bytes_received = part_file.stat().st_size if part_file.exists() else 0
                 
                 active.append({
                     "upload_id": uid_str,
                     "file_name": metadata.get("file_name"),
                     "status": metadata.get("status", "active"),
                     "progress": (bytes_received / metadata["file_size"]) * 100 if metadata.get("file_size") else 0,
                     "bytes_transferred": bytes_received,
                     "total_size": metadata.get("file_size")
                 })
        except: pass
    
    # From Disk (orphaned/paused sessions not in memory)
    seen = {x["upload_id"] for x in active}
    for sess_file in TEMP_UPLOAD_DIR.glob("*.meta"):
        if sess_file.stem in seen: continue
        try:
            data = json.loads(sess_file.read_text(encoding="utf-8"))
            if data.get("client_id") == client_id:
                 part_file = TEMP_UPLOAD_DIR / f"{sess_file.stem}.part"
                 bytes_received = part_file.stat().st_size if part_file.exists() else 0
                 
                 active.append({
                    "upload_id": sess_file.stem,
                    "file_name": data["file_name"],
                    "status": data.get("status", "paused"),
                    "progress": (bytes_received / data["file_size"]) * 100 if data.get("file_size") else 0,
                    "bytes_transferred": bytes_received,
                    "total_size": data.get("file_size")
                 })
        except: pass
        
    return {"active_uploads": active}

@upload_router.post("/restore-sessions")
async def restore_upload_sessions():
    return await asyncio.to_thread(restore_sessions)