# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

"""
File Transfer Module - Upload and Download Operations

This module handles all file upload and download operations for PCLink,
including chunked transfers, session management, and resume capability.
"""

import asyncio
import json
import logging
import shutil
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Dict, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..core.validators import validate_filename
from .file_browser import _validate_and_resolve_path, _get_unique_filename, _encode_filename_for_header

# --- Performance Enhancement: Use aiofiles if available ---
try:
    import aiofiles
    AIOFILES_INSTALLED = True
except ImportError:
    AIOFILES_INSTALLED = False


log = logging.getLogger(__name__)


# --- Pydantic Models ---
class UploadInitiatePayload(BaseModel):
    file_name: str
    destination_path: str
    conflict_resolution: Literal["abort", "overwrite", "keep_both"] = "abort"


class UploadInitiateResponse(BaseModel):
    upload_id: str
    final_file_name: str | None = None


class FileConflictResponse(BaseModel):
    conflict: bool = True
    existing_file: str
    options: list[str] = ["abort", "overwrite", "keep_both"]
    suggested_name: str | None = None


class DownloadInitiatePayload(BaseModel):
    file_path: str


class DownloadInitiateResponse(BaseModel):
    download_id: str
    file_size: int
    file_name: str


class DownloadStatusResponse(BaseModel):
    download_id: str
    file_size: int
    bytes_downloaded: int
    progress_percent: float
    status: str


# --- API Routers ---
upload_router = APIRouter()
download_router = APIRouter()


# --- Constants and State ---
HOME_DIR = Path.home().resolve()
TEMP_UPLOAD_DIR = HOME_DIR / ".pclink_uploads"
TEMP_UPLOAD_DIR.mkdir(exist_ok=True, parents=True)
DOWNLOAD_SESSION_DIR = HOME_DIR / ".pclink_downloads"
DOWNLOAD_SESSION_DIR.mkdir(exist_ok=True, parents=True)

# Performance Enhancement: Configurable chunk sizes
DOWNLOAD_CHUNK_SIZE = 65536  # 64KB for better throughput
UPLOAD_CHUNK_SIZE = 262144  # 256KB for faster uploads (4x download size)
UPLOAD_BUFFER_SIZE = 1048576  # 1MB buffer for write operations

ACTIVE_UPLOADS: Dict[str, str] = {}
ACTIVE_DOWNLOADS: Dict[str, Dict] = {}
TRANSFER_LOCKS: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
UPLOAD_BUFFERS: Dict[str, bytearray] = {}  # In-memory buffers for faster writes


# --- Utility Functions ---
async def write_file_async(file_path: Path, data: bytes, mode: str = "wb", offset: int | None = None):
    """
    Unified async/sync file writer with optional offset support.
    
    Args:
        file_path: Path to the file
        data: Data to write
        mode: File open mode ('wb', 'ab', 'rb+')
        offset: Optional seek offset for random access writes
    """
    if AIOFILES_INSTALLED:
        open_mode = "r+b" if mode == "rb+" else mode
        async with aiofiles.open(file_path, open_mode) as f:
            if offset is not None:
                await f.seek(offset)
            await f.write(data)
    else:
        def _sync_write():
            with open(file_path, mode) as f:
                if offset is not None:
                    f.seek(offset)
                f.write(data)
        await asyncio.to_thread(_sync_write)


async def _cleanup_transfer_session(transfer_id: str):
    """Clean up transfer session resources."""
    TRANSFER_LOCKS.pop(transfer_id, None)
    UPLOAD_BUFFERS.pop(transfer_id, None)


def _manage_session_file(session_id: str, data: Dict | None = None, operation: str = "read", session_type: str = "download"):
    """
    Unified session file manager for both uploads and downloads.
    
    Args:
        session_id: The session identifier
        data: Session data (required for 'save' operation)
        operation: 'read', 'save', or 'delete'
        session_type: 'download' or 'upload'
    
    Returns:
        Dict for 'read' operation, None otherwise
    """
    directory = DOWNLOAD_SESSION_DIR if session_type == "download" else TEMP_UPLOAD_DIR
    extension = ".json" if session_type == "download" else ".meta"
    session_file = directory / f"{session_id}{extension}"
    
    try:
        if operation == "delete":
            session_file.unlink(missing_ok=True)
            if session_type == "upload":
                (directory / f"{session_id}.part").unlink(missing_ok=True)
        elif operation == "save" and data:
            session_file.write_text(json.dumps(data), encoding="utf-8")
        elif operation == "read":
            if session_file.exists():
                return json.loads(session_file.read_text(encoding="utf-8"))
    except Exception as e:
        log.error(f"Session {operation} failed for {session_id} ({session_type}): {e}")
    return None


# Legacy compatibility wrappers
def _save_download_session(download_id: str, session_data: Dict):
    _manage_session_file(download_id, session_data, operation="save", session_type="download")


def _load_download_session(download_id: str) -> Dict | None:
    return _manage_session_file(download_id, operation="read", session_type="download")


def _delete_download_session(download_id: str):
    _manage_session_file(download_id, operation="delete", session_type="download")


def restore_sessions():
    """Restore upload and download sessions from disk on startup."""
    restored_uploads = 0
    restored_downloads = 0
    
    # Restore uploads
    for meta_file in TEMP_UPLOAD_DIR.glob("*.meta"):
        try:
            upload_id = meta_file.stem
            part_file = TEMP_UPLOAD_DIR / f"{upload_id}.part"
            if part_file.exists():
                metadata = _manage_session_file(upload_id, operation="read", session_type="upload")
                if metadata:
                    final_path = metadata.get("final_path")
                    if final_path:
                        ACTIVE_UPLOADS[final_path] = upload_id
                        restored_uploads += 1
                        log.info(f"Restored upload session: {upload_id} for {metadata.get('file_name', 'unknown')}")
        except Exception as e:
            log.warning(f"Failed to restore upload session from {meta_file}: {e}")
    
    # Restore downloads
    for session_file in DOWNLOAD_SESSION_DIR.glob("*.json"):
        try:
            download_id = session_file.stem
            session_data = _manage_session_file(download_id, operation="read", session_type="download")
            
            if session_data:
                file_path = Path(session_data["file_path"])
                if file_path.exists() and file_path.is_file():
                    current_stat = file_path.stat()
                    if current_stat.st_mtime == session_data.get("file_modified_at"):
                        ACTIVE_DOWNLOADS[download_id] = session_data
                        restored_downloads += 1
                        log.info(f"Restored download session: {download_id} for {session_data.get('file_name', 'unknown')}")
                    else:
                        _manage_session_file(download_id, operation="delete", session_type="download")
                        log.info(f"Removed stale download session {download_id} (file modified)")
                else:
                    _manage_session_file(download_id, operation="delete", session_type="download")
                    log.info(f"Removed stale download session {download_id} (file not found)")
        except Exception as e:
            log.warning(f"Failed to restore download session from {session_file}: {e}")
    
    if restored_uploads or restored_downloads:
        log.info(f"Session restoration complete: {restored_uploads} uploads, {restored_downloads} downloads")
    
    return {"restored_uploads": restored_uploads, "restored_downloads": restored_downloads}


async def cleanup_stale_sessions():
    """Background task to clean up old sessions and buffers."""
    current_time = time.time()
    stale_threshold = 7 * 24 * 60 * 60  # 7 days
    cleaned_uploads, cleaned_downloads = 0, 0
    
    # Clean stale uploads
    for upload_file in TEMP_UPLOAD_DIR.glob("*.meta"):
        try:
            if current_time - upload_file.stat().st_mtime > stale_threshold:
                upload_id = upload_file.stem
                _manage_session_file(upload_id, operation="delete", session_type="upload")
                
                # Clean up from active uploads
                for path, uid in list(ACTIVE_UPLOADS.items()):
                    if uid == upload_id:
                        del ACTIVE_UPLOADS[path]
                
                # Clean up buffer
                UPLOAD_BUFFERS.pop(upload_id, None)
                cleaned_uploads += 1
        except Exception as e:
            log.warning(f"Error cleaning up stale upload {upload_file}: {e}")
    
    # Clean stale downloads
    for session_file in DOWNLOAD_SESSION_DIR.glob("*.json"):
        try:
            if current_time - session_file.stat().st_mtime > stale_threshold:
                download_id = session_file.stem
                _manage_session_file(download_id, operation="delete", session_type="download")
                ACTIVE_DOWNLOADS.pop(download_id, None)
                cleaned_downloads += 1
        except Exception as e:
            log.warning(f"Error cleaning up stale download {session_file}: {e}")
    
    if cleaned_uploads or cleaned_downloads:
        log.info(f"Cleaned up {cleaned_uploads} stale uploads and {cleaned_downloads} stale downloads")
    
    return {"cleaned_uploads": cleaned_uploads, "cleaned_downloads": cleaned_downloads}


# --- Upload Endpoints ---

@upload_router.get("/config")
async def get_upload_config():
    """Return optimal upload configuration for clients."""
    return {
        "recommended_chunk_size": UPLOAD_CHUNK_SIZE,
        "max_chunk_size": UPLOAD_CHUNK_SIZE * 2,
        "min_chunk_size": 65536,
        "buffer_size": UPLOAD_BUFFER_SIZE,
        "supports_concurrent_chunks": False,
        "supports_resume": True,
        "supports_pause": True,
        "aiofiles_enabled": AIOFILES_INSTALLED
    }


@upload_router.post("/check-conflict")
async def check_upload_conflict(payload: UploadInitiatePayload):
    dest_path = _validate_and_resolve_path(payload.destination_path)
    if not dest_path.is_dir():
        raise HTTPException(status_code=400, detail="Destination is not a directory")
    safe_filename = validate_filename(payload.file_name)
    file_path = dest_path / safe_filename
    if file_path.exists():
        suggested_name = _get_unique_filename(file_path).name
        return {
            "conflict": True, "existing_file": safe_filename,
            "options": ["abort", "overwrite", "keep_both"], "suggested_name": suggested_name,
            "message": f"File '{safe_filename}' already exists"
        }
    return {"conflict": False, "message": "No conflict, upload can proceed"}


@upload_router.post("/initiate")
async def initiate_upload(payload: UploadInitiatePayload):
    dest_path = _validate_and_resolve_path(payload.destination_path)
    if not dest_path.is_dir():
        raise HTTPException(status_code=400, detail="Destination is not a directory")
    safe_filename = validate_filename(payload.file_name)
    original_file_path = dest_path / safe_filename
    final_file_path = original_file_path
    if original_file_path.exists():
        if payload.conflict_resolution == "abort":
            raise HTTPException(status_code=409, detail={
                "conflict": True, "existing_file": safe_filename,
                "options": ["abort", "overwrite", "keep_both"],
                "suggested_name": _get_unique_filename(original_file_path).name,
                "message": f"File '{safe_filename}' already exists"
            })
        elif payload.conflict_resolution == "keep_both":
            final_file_path = _get_unique_filename(original_file_path)
    final_file_path_str = str(final_file_path)
    init_lock = TRANSFER_LOCKS[f"init_upload_{final_file_path_str}"]
    async with init_lock:
        if final_file_path_str in ACTIVE_UPLOADS:
            existing_id = ACTIVE_UPLOADS[final_file_path_str]
            if (TEMP_UPLOAD_DIR / f"{existing_id}.part").exists():
                log.info(f"Resuming upload for {final_file_path.name} with ID {existing_id}")
                return UploadInitiateResponse(upload_id=existing_id, final_file_name=final_file_path.name)
            else:
                del ACTIVE_UPLOADS[final_file_path_str]
        upload_id = str(uuid.uuid4())
        metadata = {"final_path": final_file_path_str, "file_name": final_file_path.name}
        (TEMP_UPLOAD_DIR / f"{upload_id}.meta").write_text(json.dumps(metadata), encoding="utf-8")
        (TEMP_UPLOAD_DIR / f"{upload_id}.part").touch()
        ACTIVE_UPLOADS[final_file_path_str] = upload_id
        log.info(f"Initiated new upload for {final_file_path.name} with ID {upload_id}")
        return UploadInitiateResponse(upload_id=upload_id, final_file_name=final_file_path.name)


@upload_router.get("/status/{upload_id}")
async def get_upload_status(upload_id: str):
    part_file = TEMP_UPLOAD_DIR / f"{upload_id}.part"
    meta_file = TEMP_UPLOAD_DIR / f"{upload_id}.meta"
    if not part_file.exists() or not meta_file.exists():
        raise HTTPException(status_code=404, detail="Upload not found or expired.")
    try:
        metadata = json.loads(meta_file.read_text(encoding="utf-8"))
        bytes_received = part_file.stat().st_size
        return {
            "upload_id": upload_id, "bytes_received": bytes_received,
            "file_name": metadata.get("file_name", "unknown"),
            "status": "active", "resumable": True
        }
    except Exception as e:
        log.error(f"Error reading upload status for {upload_id}: {e}")
        raise HTTPException(status_code=500, detail="Error reading upload status")


@upload_router.post("/chunk/{upload_id}")
async def upload_chunk(upload_id: str, request: Request, offset: int = Query(...)):
    part_file = TEMP_UPLOAD_DIR / f"{upload_id}.part"
    meta_file = TEMP_UPLOAD_DIR / f"{upload_id}.meta"
    lock = TRANSFER_LOCKS[upload_id]
    
    if upload_id not in UPLOAD_BUFFERS:
        UPLOAD_BUFFERS[upload_id] = bytearray()
    
    bytes_written = 0
    
    async with lock:
        if not part_file.exists() or not meta_file.exists():
            raise HTTPException(status_code=404, detail="Upload session not found or expired.")
        
        try:
            buffer = UPLOAD_BUFFERS[upload_id]
            buffer.clear()
            
            async for chunk in request.stream():
                buffer.extend(chunk)
                bytes_written += len(chunk)
            
            await write_file_async(part_file, buffer, mode="rb+", offset=offset)
            buffer.clear()
            
        except Exception as e:
            log.error(f"Error writing chunk for upload {upload_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Error writing file chunk: {e}")
    
    return {"status": "chunk received", "bytes_written": bytes_written}


@upload_router.post("/complete/{upload_id}")
async def complete_upload(upload_id: str, background_tasks: BackgroundTasks):
    part_file = TEMP_UPLOAD_DIR / f"{upload_id}.part"
    meta_file = TEMP_UPLOAD_DIR / f"{upload_id}.meta"
    lock = TRANSFER_LOCKS[upload_id]
    async with lock:
        if not part_file.exists() or not meta_file.exists():
            raise HTTPException(status_code=404, detail="Upload not found or expired.")
        metadata = json.loads(meta_file.read_text(encoding="utf-8"))
        final_path = Path(metadata["final_path"])
        final_path_str = str(final_path)
        try:
            await asyncio.to_thread(final_path.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(shutil.move, str(part_file), final_path_str)
        except Exception as e:
            if part_file.exists(): part_file.unlink()
            raise HTTPException(status_code=500, detail=f"Error moving completed file: {e}")
        finally:
            if meta_file.exists(): meta_file.unlink()
            if final_path_str in ACTIVE_UPLOADS:
                del ACTIVE_UPLOADS[final_path_str]
            if upload_id in UPLOAD_BUFFERS:
                del UPLOAD_BUFFERS[upload_id]
    background_tasks.add_task(_cleanup_transfer_session, upload_id)
    log.info(f"Completed upload for {final_path.name}")
    return {"status": "completed", "path": final_path_str}


@upload_router.post("/pause/{upload_id}")
async def pause_upload(upload_id: str):
    part_file = TEMP_UPLOAD_DIR / f"{upload_id}.part"
    meta_file = TEMP_UPLOAD_DIR / f"{upload_id}.meta"
    if not part_file.exists() or not meta_file.exists():
        raise HTTPException(status_code=404, detail="Upload session not found")
    try:
        metadata = json.loads(meta_file.read_text(encoding="utf-8"))
        metadata.update({"status": "paused", "paused_at": time.time()})
        meta_file.write_text(json.dumps(metadata), encoding="utf-8")
        bytes_received = part_file.stat().st_size
        log.info(f"Paused upload {upload_id} at {bytes_received} bytes")
        return {
            "status": "paused", "upload_id": upload_id,
            "bytes_received": bytes_received, "resumable": True
        }
    except Exception as e:
        log.error(f"Error pausing upload {upload_id}: {e}")
        raise HTTPException(status_code=500, detail="Error pausing upload")


@upload_router.post("/resume/{upload_id}")
async def resume_upload(upload_id: str):
    part_file = TEMP_UPLOAD_DIR / f"{upload_id}.part"
    meta_file = TEMP_UPLOAD_DIR / f"{upload_id}.meta"
    if not part_file.exists() or not meta_file.exists():
        raise HTTPException(status_code=404, detail="Upload session not found")
    try:
        metadata = json.loads(meta_file.read_text(encoding="utf-8"))
        metadata.update({"status": "active", "resumed_at": time.time()})
        meta_file.write_text(json.dumps(metadata), encoding="utf-8")
        bytes_received = part_file.stat().st_size
        log.info(f"Resumed upload {upload_id} from {bytes_received} bytes")
        return {
            "status": "resumed", "upload_id": upload_id,
            "bytes_received": bytes_received, "resume_offset": bytes_received
        }
    except Exception as e:
        log.error(f"Error resuming upload {upload_id}: {e}")
        raise HTTPException(status_code=500, detail="Error resuming upload")


@upload_router.delete("/cancel/{upload_id}")
async def cancel_upload(upload_id: str, background_tasks: BackgroundTasks):
    part_file = TEMP_UPLOAD_DIR / f"{upload_id}.part"
    meta_file = TEMP_UPLOAD_DIR / f"{upload_id}.meta"
    file_name = "unknown"
    if meta_file.exists():
        try:
            metadata = json.loads(meta_file.read_text(encoding="utf-8"))
            file_name = metadata.get("file_name", "unknown")
            final_path_str = metadata.get("final_path")
            if final_path_str and final_path_str in ACTIVE_UPLOADS:
                del ACTIVE_UPLOADS[final_path_str]
        except Exception:
            pass
    if part_file.exists(): part_file.unlink()
    if meta_file.exists(): meta_file.unlink()
    if upload_id in UPLOAD_BUFFERS:
        del UPLOAD_BUFFERS[upload_id]
    background_tasks.add_task(_cleanup_transfer_session, upload_id)
    log.info(f"Cancelled upload {upload_id} for {file_name}")
    return {"status": "cancelled"}


@upload_router.post("/restore-sessions")
async def restore_upload_sessions():
    result = await asyncio.to_thread(restore_sessions)
    return {
        "status": "success", "message": "Sessions restored",
        "restored_uploads": result["restored_uploads"],
        "restored_downloads": result["restored_downloads"]
    }


@upload_router.get("/list-active")
async def list_active_uploads():
    """List all active upload sessions."""
    active_uploads = []
    for upload_file in TEMP_UPLOAD_DIR.glob("*.meta"):
        try:
            upload_id = upload_file.stem
            part_file = TEMP_UPLOAD_DIR / f"{upload_id}.part"
            if part_file.exists():
                metadata = json.loads(upload_file.read_text(encoding="utf-8"))
                stat_info = part_file.stat()
                active_uploads.append({
                    "upload_id": upload_id,
                    "file_name": metadata.get("file_name", "unknown"),
                    "bytes_received": stat_info.st_size,
                    "status": metadata.get("status", "active"),
                    "created_at": stat_info.st_ctime,
                    "resumable": True
                })
        except Exception as e:
            log.warning(f"Error reading upload metadata {upload_file}: {e}")
    return {"active_uploads": active_uploads}


@upload_router.post("/stream/{upload_id}")
async def stream_upload(upload_id: str, request: Request):
    """Stream upload data directly without chunking."""
    part_file = TEMP_UPLOAD_DIR / f"{upload_id}.part"
    meta_file = TEMP_UPLOAD_DIR / f"{upload_id}.meta"
    if not part_file.exists() or not meta_file.exists():
        raise HTTPException(status_code=404, detail="Upload session not found or expired.")
    
    if upload_id not in UPLOAD_BUFFERS:
        UPLOAD_BUFFERS[upload_id] = bytearray()
    
    try:
        bytes_written = 0
        buffer = UPLOAD_BUFFERS[upload_id]
        buffer.clear()
        
        if AIOFILES_INSTALLED:
            async with aiofiles.open(part_file, "wb") as f:
                async for chunk in request.stream():
                    buffer.extend(chunk)
                    bytes_written += len(chunk)
                    
                    if len(buffer) >= UPLOAD_BUFFER_SIZE:
                        await f.write(buffer)
                        buffer.clear()
                
                if buffer:
                    await f.write(buffer)
                    buffer.clear()
        else:
            def write_stream_sync():
                nonlocal bytes_written
                with part_file.open("wb") as f:
                    if buffer:
                        f.write(buffer)
                        bytes_written = len(buffer)
            
            async for chunk in request.stream():
                buffer.extend(chunk)
                
                if len(buffer) >= UPLOAD_BUFFER_SIZE:
                    await asyncio.to_thread(write_stream_sync)
                    buffer.clear()
            
            if buffer:
                await asyncio.to_thread(write_stream_sync)
                buffer.clear()
        
        log.info(f"Streamed {bytes_written} bytes for upload {upload_id}")
        return {"status": "stream received", "bytes_written": bytes_written}
    except Exception as e:
        log.error(f"Error in stream upload {upload_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error streaming file: {e}")
    finally:
        if upload_id in UPLOAD_BUFFERS:
            UPLOAD_BUFFERS[upload_id].clear()


@upload_router.post("/direct")
async def direct_upload(request: Request, destination_path: str = Query(...), file_name: str = Query(...),
                      conflict_resolution: str = Query("keep_both", regex="^(abort|overwrite|keep_both)$")):
    """Direct upload without session management for simple use cases."""
    try:
        dest_path = _validate_and_resolve_path(destination_path)
        if not dest_path.is_dir():
            raise HTTPException(status_code=400, detail="Destination is not a directory")
        safe_filename = validate_filename(file_name)
        original_file_path = dest_path / safe_filename
        final_file_path = original_file_path
        if original_file_path.exists():
            if conflict_resolution == "abort":
                raise HTTPException(status_code=409, detail={
                    "conflict": True, "existing_file": safe_filename,
                    "options": ["abort", "overwrite", "keep_both"],
                    "suggested_name": _get_unique_filename(original_file_path).name,
                    "message": f"File '{safe_filename}' already exists"
                })
            elif conflict_resolution == "keep_both":
                final_file_path = _get_unique_filename(original_file_path)
        
        await asyncio.to_thread(final_file_path.parent.mkdir, parents=True, exist_ok=True)
        
        bytes_written = 0
        buffer = bytearray()
        
        if AIOFILES_INSTALLED:
            async with aiofiles.open(final_file_path, "wb") as f:
                async for chunk in request.stream():
                    buffer.extend(chunk)
                    bytes_written += len(chunk)
                    
                    if len(buffer) >= UPLOAD_BUFFER_SIZE:
                        await f.write(buffer)
                        buffer.clear()
                
                if buffer:
                    await f.write(buffer)
        else:
            def write_buffered_sync():
                with final_file_path.open("ab") as f:
                    f.write(buffer)
            
            async for chunk in request.stream():
                buffer.extend(chunk)
                bytes_written += len(chunk)
                
                if len(buffer) >= UPLOAD_BUFFER_SIZE:
                    await asyncio.to_thread(write_buffered_sync)
                    buffer.clear()
            
            if buffer:
                await asyncio.to_thread(write_buffered_sync)
        
        log.info(f"Direct upload completed: {final_file_path.name} ({bytes_written} bytes)")
        return {
            "status": "completed", "path": str(final_file_path),
            "bytes_written": bytes_written, "file_name": final_file_path.name
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error in direct upload: {e}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")


# --- Download Endpoints ---

@download_router.get("/config")
async def get_download_config():
    """Return optimal download configuration for clients."""
    return {
        "recommended_chunk_size": DOWNLOAD_CHUNK_SIZE,
        "max_chunk_size": DOWNLOAD_CHUNK_SIZE * 4,
        "min_chunk_size": 32768,
        "supports_resume": True,
        "supports_pause": True,
        "supports_range_requests": True,
        "aiofiles_enabled": AIOFILES_INSTALLED
    }


@download_router.post("/initiate", response_model=DownloadInitiateResponse)
async def initiate_download(payload: DownloadInitiatePayload):
    try:
        file_path_str = payload.file_path.decode('utf-8') if isinstance(payload.file_path, bytes) else payload.file_path
        file_path = _validate_and_resolve_path(file_path_str)
    except (HTTPException, UnicodeDecodeError) as e:
        detail = e.detail if isinstance(e, HTTPException) else f"Invalid character encoding in file path: {e}"
        log.error(f"Path validation failed for '{payload.file_path}': {detail}")
        raise HTTPException(status_code=400, detail=detail) from e
    except Exception as e:
        log.error(f"Unexpected error during path validation: {e}")
        raise HTTPException(status_code=500, detail=f"Error processing path: {e}") from e
    
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found or is not a file")
    
    try:
        file_stat = await asyncio.to_thread(file_path.stat)
        file_size = file_stat.st_size
    except Exception as e:
        log.error(f"Error accessing file stats for '{file_path}': {e}")
        raise HTTPException(status_code=500, detail=f"Error accessing file: {e}") from e
    
    download_id = str(uuid.uuid4())
    session_data = {
        "file_path": str(file_path), "file_name": file_path.name,
        "file_size": file_size, "bytes_downloaded": 0, "status": "active",
        "file_modified_at": file_stat.st_mtime, "session_created_at": time.time(),
    }
    ACTIVE_DOWNLOADS[download_id] = session_data
    await asyncio.to_thread(_save_download_session, download_id, session_data)
    log.info(f"Successfully created download session for '{file_path.name}' with ID {download_id}")
    return DownloadInitiateResponse(download_id=download_id, file_size=file_size, file_name=file_path.name)


@download_router.get("/status/{download_id}", response_model=DownloadStatusResponse)
async def get_download_status(download_id: str):
    if download_id not in ACTIVE_DOWNLOADS:
        session_data = await asyncio.to_thread(_load_download_session, download_id)
        if session_data and Path(session_data["file_path"]).exists():
            ACTIVE_DOWNLOADS[download_id] = session_data
            log.info(f"Restored download session {download_id} from disk")
        else:
            if session_data: _delete_download_session(download_id)
            raise HTTPException(status_code=404, detail="Download session not found")
    info = ACTIVE_DOWNLOADS[download_id]
    progress = (info["bytes_downloaded"] / info["file_size"]) * 100 if info["file_size"] > 0 else 0
    return DownloadStatusResponse(
        download_id=download_id, file_size=info["file_size"],
        bytes_downloaded=info["bytes_downloaded"], progress_percent=round(progress, 2),
        status=info["status"]
    )


@download_router.get("/chunk/{download_id}")
async def download_chunk(download_id: str, request: Request, range_header: str = Header(None, alias="Range")):
    if download_id not in ACTIVE_DOWNLOADS:
        session_data = _load_download_session(download_id)
        if session_data:
            ACTIVE_DOWNLOADS[download_id] = session_data
        else:
            raise HTTPException(status_code=404, detail="Download session not found")
    info = ACTIVE_DOWNLOADS[download_id]
    file_path, file_size = Path(info["file_path"]), info["file_size"]
    try:
        current_stat = file_path.stat()
        if current_stat.st_size != file_size or current_stat.st_mtime != info["file_modified_at"]:
            raise HTTPException(status_code=409, detail="File has changed since download was initiated.")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File no longer exists.")
    start_byte, end_byte = 0, file_size - 1
    if range_header:
        try:
            range_val = range_header.replace("bytes=", "").split("-")
            start_byte = int(range_val[0])
            end_byte = int(range_val[1]) if len(range_val) > 1 and range_val[1] else file_size - 1
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Range header.")
    if start_byte >= file_size:
        raise HTTPException(status_code=416, detail="Requested range not satisfiable.")
    
    chunk_size = (end_byte - start_byte) + 1
    
    async def stream_file_range():
        try:
            if AIOFILES_INSTALLED:
                async with aiofiles.open(file_path, "rb") as f:
                    await f.seek(start_byte)
                    bytes_to_send = chunk_size
                    while bytes_to_send > 0:
                        data = await f.read(min(DOWNLOAD_CHUNK_SIZE, bytes_to_send))
                        if not data: break
                        bytes_to_send -= len(data)
                        yield data
            else:
                with file_path.open("rb") as f:
                    f.seek(start_byte)
                    bytes_to_send = chunk_size
                    while bytes_to_send > 0:
                        data = f.read(min(DOWNLOAD_CHUNK_SIZE, bytes_to_send))
                        if not data: break
                        bytes_to_send -= len(data)
                        yield data
            info["bytes_downloaded"] = end_byte + 1
            _save_download_session(download_id, info)
        except Exception as e:
            log.error(f"Error streaming file chunk for download {download_id}: {e}")
            raise
    
    headers = {
        "Content-Range": f"bytes {start_byte}-{end_byte}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(chunk_size),
        "Content-Disposition": _encode_filename_for_header(info["file_name"])
    }
    return StreamingResponse(stream_file_range(), status_code=206, headers=headers, media_type="application/octet-stream")


@download_router.post("/pause/{download_id}")
async def pause_download(download_id: str):
    if download_id not in ACTIVE_DOWNLOADS:
        session_data = _load_download_session(download_id)
        if session_data:
            ACTIVE_DOWNLOADS[download_id] = session_data
        else:
            raise HTTPException(status_code=404, detail="Download session not found")
    info = ACTIVE_DOWNLOADS[download_id]
    info.update({"status": "paused", "paused_at": time.time()})
    _save_download_session(download_id, info)
    log.info(f"Paused download {download_id} for {info['file_name']}")
    return {"status": "paused", "download_id": download_id, "bytes_downloaded": info["bytes_downloaded"],
            "file_size": info["file_size"], "resumable": True}


@download_router.post("/resume/{download_id}")
async def resume_download(download_id: str):
    if download_id not in ACTIVE_DOWNLOADS:
        session_data = _load_download_session(download_id)
        if session_data:
            ACTIVE_DOWNLOADS[download_id] = session_data
        else:
            raise HTTPException(status_code=404, detail="Download session not found")
    info = ACTIVE_DOWNLOADS[download_id]
    info.update({"status": "active", "resumed_at": time.time()})
    _save_download_session(download_id, info)
    log.info(f"Resumed download {download_id} for {info['file_name']}")
    return {"status": "resumed", "download_id": download_id, "bytes_downloaded": info["bytes_downloaded"],
            "file_size": info["file_size"], "resume_offset": info["bytes_downloaded"]}


@download_router.delete("/cancel/{download_id}")
async def cancel_download(download_id: str, background_tasks: BackgroundTasks):
    file_name = "unknown"
    if download_id in ACTIVE_DOWNLOADS:
        file_name = ACTIVE_DOWNLOADS[download_id].get('file_name', 'unknown')
        del ACTIVE_DOWNLOADS[download_id]
    _delete_download_session(download_id)
    background_tasks.add_task(_cleanup_transfer_session, download_id)
    log.info(f"Cancelled download {download_id} for {file_name}")
    return {"status": "cancelled"}


@download_router.get("/list-active")
async def list_active_downloads():
    """List all active download sessions."""
    active_downloads, seen_ids = [], set()
    for download_id, info in ACTIVE_DOWNLOADS.items():
        progress = (info["bytes_downloaded"] / info["file_size"]) * 100 if info["file_size"] > 0 else 0
        active_downloads.append({
            "download_id": download_id, "file_name": info["file_name"],
            "file_size": info["file_size"], "bytes_downloaded": info["bytes_downloaded"],
            "progress_percent": round(progress, 2), "status": info["status"],
            "created_at": info["session_created_at"]
        })
        seen_ids.add(download_id)
    for session_file in DOWNLOAD_SESSION_DIR.glob("*.json"):
        try:
            download_id = session_file.stem
            if download_id not in seen_ids:
                session_data = json.loads(session_file.read_text(encoding="utf-8"))
                if Path(session_data["file_path"]).exists():
                    progress = (session_data["bytes_downloaded"] / session_data["file_size"]) * 100 if session_data["file_size"] > 0 else 0
                    active_downloads.append({
                        "download_id": download_id, "file_name": session_data["file_name"],
                        "file_size": session_data["file_size"], "bytes_downloaded": session_data["bytes_downloaded"],
                        "progress_percent": round(progress, 2), "status": session_data.get("status", "paused"),
                        "created_at": session_data["session_created_at"], "recoverable": True
                    })
        except Exception as e:
            log.warning(f"Error reading persisted download session {session_file}: {e}")
    return {"active_downloads": active_downloads}