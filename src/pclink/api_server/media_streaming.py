# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import logging
import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

# Import utilities from file_browser
from .file_browser import _validate_and_resolve_path, DOWNLOAD_CHUNK_SIZE

# --- Performance Enhancement: Use aiofiles if available ---
try:
    import aiofiles
    AIOFILES_INSTALLED = True
except ImportError:
    AIOFILES_INSTALLED = False


log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/stream")
async def stream_media(request: Request, path: str = Query(...)):
    """
    Streams a video/audio file with support for HTTP Range requests.
    This allows media players to seek and buffer the content.
    Uses query parameter to avoid URL encoding issues with special characters.
    
    Query Parameters:
        path: Full file path to the media file
        
    Headers:
        Range: Optional byte range for partial content requests (e.g., "bytes=0-1023")
        
    Returns:
        StreamingResponse with appropriate status code (200 or 206)
    """
    log.info(f"=== MEDIA STREAM REQUEST RECEIVED ===")
    log.info(f"Requested file path: {path!r}")
    log.info(f"Request headers: {dict(request.headers)}")
    log.info(f"Client: {request.client}")
    
    # Validate and resolve the file path
    try:
        resolved_path = _validate_and_resolve_path(path)
        log.info(f"Path resolved successfully to: {resolved_path}")
    except HTTPException as e:
        log.error(f"HTTPException validating path '{path}': {e.detail}")
        raise
    except Exception as e:
        log.error(f"Error validating path '{path}': {e}")
        raise HTTPException(status_code=400, detail=f"Invalid path: {e}")
    
    # Verify it's a file
    if not resolved_path.is_file():
        log.error(f"Path exists but is not a file: {resolved_path}")
        raise HTTPException(status_code=404, detail="File not found or is not a file.")
    
    log.info(f"File exists and is valid for streaming")

    # Get file information
    try:
        file_stat = await asyncio.to_thread(resolved_path.stat)
        file_size = file_stat.st_size
        content_type, _ = mimetypes.guess_type(resolved_path)
        if not content_type or not (content_type.startswith("video/") or content_type.startswith("audio/")):
            content_type = "application/octet-stream"  # Fallback
        log.info(f"File size: {file_size} bytes, Content-Type: {content_type}")
    except Exception as e:
        log.error(f"Error accessing file stats for '{resolved_path}': {e}")
        raise HTTPException(status_code=500, detail=f"Error accessing file: {e}")

    # Parse Range header for partial content requests
    range_header = request.headers.get("Range")
    log.info(f"Range header: {range_header}")
    
    headers = {
        "Content-Type": content_type,
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size),
        "Content-Disposition": f'inline; filename="{resolved_path.name}"'
    }

    start, end = 0, file_size - 1
    status_code = 200

    if range_header:
        try:
            range_bytes = range_header.split("=")[1]
            start_str, end_str = range_bytes.split("-")
            start = int(start_str)
            if end_str:
                end = int(end_str)
            else:
                end = file_size - 1
            
            if start >= file_size or end >= file_size or start > end:
                log.error(f"Range not satisfiable: start={start}, end={end}, file_size={file_size}")
                raise HTTPException(status_code=416, detail="Requested range not satisfiable")

            chunk_size = (end - start) + 1
            headers["Content-Length"] = str(chunk_size)
            headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
            status_code = 206
            log.info(f"Partial content: bytes {start}-{end}/{file_size} (chunk: {chunk_size} bytes)")
        except (ValueError, IndexError) as e:
            log.error(f"Invalid Range header: {range_header}, error: {e}")
            raise HTTPException(status_code=400, detail="Invalid Range header format.")
    else:
        log.info(f"Full file request: {file_size} bytes")

    log.info(f"Returning StreamingResponse with status {status_code}")
    bytes_sent = 0

    async def file_iterator(start_pos, end_pos):
        nonlocal bytes_sent
        try:
            log.info(f"Iterator started: reading bytes {start_pos} to {end_pos}")
            if AIOFILES_INSTALLED:
                async with aiofiles.open(resolved_path, "rb") as f:
                    await f.seek(start_pos)
                    remaining = (end_pos - start_pos) + 1
                    while remaining > 0:
                        chunk = await f.read(min(DOWNLOAD_CHUNK_SIZE, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        bytes_sent += len(chunk)
                        yield chunk
            else:
                # Sync fallback
                log.info("Using sync I/O (aiofiles not available)")
                with resolved_path.open("rb") as f:
                    f.seek(start_pos)
                    remaining = (end_pos - start_pos) + 1
                    while remaining > 0:
                        data = f.read(min(DOWNLOAD_CHUNK_SIZE, remaining))
                        if not data:
                            break
                        remaining -= len(data)
                        bytes_sent += len(data)
                        yield data
            log.info(f"Stream completed: sent {bytes_sent} bytes")
        except Exception as e:
            log.error(f"Error in file_iterator: {e}, bytes sent: {bytes_sent}")
            import traceback
            log.error(f"Traceback: {traceback.format_exc()}")

    return StreamingResponse(
        file_iterator(start, end),
        status_code=status_code,
        headers=headers,
    )
