# src/pclink/api_server/media_streaming.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
import mimetypes
import urllib.parse
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ..services.file_service import file_service

log = logging.getLogger(__name__)
router = APIRouter()

@router.get("/stream")
async def stream_media(request: Request, path: str = Query(...)):
    """Streams a file with Range support for seeking."""
    try:
        p = file_service.validate_path(path)
        if not p.is_file(): raise HTTPException(404, "File not found")
        
        stat = p.stat()
        file_size = stat.st_size
        mime, _ = mimetypes.guess_type(p)
        content_type = mime or "application/octet-stream"
        
        range_header = request.headers.get("Range")
        start, end = 0, file_size - 1
        status_code = 200
        headers = {
            "Content-Type": content_type,
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
            "Content-Disposition": f'inline; filename="{urllib.parse.quote(p.name)}"'
        }

        if range_header:
            try:
                # Basic Range parsing: bytes=start-end
                range_bytes = range_header.replace("bytes=", "").split("-")
                start = int(range_bytes[0])
                if range_bytes[1]: end = int(range_bytes[1])
                
                if start >= file_size or end >= file_size or start > end:
                    raise HTTPException(416, "Range Not Satisfiable")
                
                status_code = 206
                chunk_size = (end - start) + 1
                headers["Content-Length"] = str(chunk_size)
                headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
            except (ValueError, IndexError):
                raise HTTPException(400, "Invalid Range header")

        log.debug(f"Streaming {p.name}: {start}-{end} (status {status_code})")
        return StreamingResponse(
            file_service.get_file_iterator(p, start, end),
            status_code=status_code,
            headers=headers
        )
    except HTTPException: raise
    except Exception as e:
        log.error(f"Stream failed for {path}: {e}")
        raise HTTPException(500, "Streaming failed")
