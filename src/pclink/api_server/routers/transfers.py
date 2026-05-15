# src/pclink/api_server/transfer_router.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
import urllib.parse
from pathlib import Path
from typing import Literal

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ValidationError
from starlette.requests import ClientDisconnect

from ...core.device_manager import device_manager
from ...services.file_service import file_service
from ...services.transfer_service import (
    DOWNLOAD_CHUNK_SIZE,
    UPLOAD_BUFFER_SIZE,
    UPLOAD_CHUNK_SIZE,
    transfer_service,
)

log = logging.getLogger(__name__)

upload_router = APIRouter()
download_router = APIRouter()

# Constants
MAX_CHUNK_TOLERANCE = UPLOAD_CHUNK_SIZE * 2  # Hard limit for memory protection


# --- Auth Helper ---
def get_client_id(
    x_api_key: str = Header(None), token: str = Query(None), request: Request = None
) -> str:
    key = x_api_key or token
    if not key and request:
        key = request.cookies.get("pclink_device_token")

    if not key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing API Key")

    dev = device_manager.get_device_by_api_key(key)
    if dev:
        return dev.device_id

    # TODO: Explicitly check against a Master/Admin key securely here
    # Do NOT blindly return the key, otherwise it allows Auth Bypass.
    if key == getattr(device_manager, "master_key", None):
        return "master_admin"

    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API Key")


# --- Dependencies ---
async def get_download_session(
    download_id: str, client_id: str = Depends(get_client_id)
) -> dict:
    """Consolidated dependency to fetch and secure download sessions."""
    # Check memory cache first
    info = transfer_service.active_downloads.get(client_id, {}).get(download_id)
    if not info:
        info = await transfer_service.read_metadata(download_id, "download")
        if not info or not transfer_service.verify_ownership(info, client_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Transfer session not found")

        if client_id not in transfer_service.active_downloads:
            transfer_service.active_downloads[client_id] = {}
        transfer_service.active_downloads[client_id][download_id] = info

    return info


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
    download_id: str
    file_size: int
    file_name: str


class DownloadStatusResponse(BaseModel):
    download_id: str
    file_size: int
    bytes_downloaded: int
    progress_percent: float
    status: str


def _encode_filename(filename: str) -> str:
    quoted = urllib.parse.quote(filename)
    try:
        filename.encode("ascii")
        return f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quoted}"
    except UnicodeEncodeError:
        return f"attachment; filename*=UTF-8''{quoted}"


# --- UPLOAD ENDPOINTS ---


@upload_router.get("/config")
async def get_upload_config():
    return {
        "recommended_chunk_size": UPLOAD_CHUNK_SIZE,
        "max_chunk_size": UPLOAD_CHUNK_SIZE * 4,
        "buffer_size": UPLOAD_BUFFER_SIZE,
        "supports_concurrent_chunks": True,
        "supports_resume": True,
    }


@upload_router.post("/initiate", response_model=UploadInitiateResponse)
async def initiate_upload(
    payload: UploadInitiatePayload, client_id: str = Depends(get_client_id)
):
    try:
        res = await transfer_service.initiate_upload(
            client_id,
            payload.destination_path,
            payload.file_name,
            payload.file_size or 0,
            payload.conflict_resolution,
        )
        return UploadInitiateResponse(**res)
    except (ValueError, ValidationError) as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    except FileExistsError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    except Exception as e:
        log.error(f"Init upload failed: {e}", exc_info=True)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Internal error")


@upload_router.get("/status/{upload_id}")
async def get_upload_status(upload_id: str, client_id: str = Depends(get_client_id)):
    meta = await transfer_service.read_metadata(upload_id, "upload")
    if not meta or not transfer_service.verify_ownership(meta, client_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload not found")

    received = await transfer_service.get_received_bytes(upload_id)
    return {
        "upload_id": upload_id,
        "bytes_received": received,
        "status": meta.get("status"),
        "expected_size": meta.get("file_size"),
    }


@upload_router.post("/chunk/{upload_id}")
async def upload_chunk(
    upload_id: str,
    request: Request,
    offset: int = Query(...),
    client_id: str = Depends(get_client_id),
):
    meta = await transfer_service.read_metadata(upload_id, "upload")
    if not meta or not transfer_service.verify_ownership(meta, client_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload not found")

    data = bytearray()
    try:
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > MAX_CHUNK_TOLERANCE:
                raise HTTPException(
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Chunk payload too large"
                )
    except ClientDisconnect:
        log.warning(f"Client disconnected during chunk upload for {upload_id}")
        return {"status": "interrupted"}
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Stream error for {upload_id}: {e}")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Stream read failed")

    try:
        return await transfer_service.write_chunk(upload_id, offset, bytes(data))
    except BufferError as e:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, str(e))
    except Exception as e:
        log.error(f"Chunk write failed for {upload_id}: {e}", exc_info=True)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "Chunk processing failed"
        )


@upload_router.post("/complete/{upload_id}")
async def complete_upload(upload_id: str, client_id: str = Depends(get_client_id)):
    # Added auth verification to complete
    meta = await transfer_service.read_metadata(upload_id, "upload")
    if not meta or not transfer_service.verify_ownership(meta, client_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload not found")

    try:
        path = await transfer_service.complete_upload(upload_id)
        return {"status": "completed", "path": path}
    except (ValueError, ValidationError, FileNotFoundError) as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    except Exception as e:
        log.error(f"Upload completion failed: {e}", exc_info=True)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Completion failed")


@upload_router.delete("/cancel/{upload_id}")
async def cancel_upload(
    upload_id: str, bg_tasks: BackgroundTasks, client_id: str = Depends(get_client_id)
):
    meta = await transfer_service.read_metadata(upload_id, "upload")
    if not meta or not transfer_service.verify_ownership(meta, client_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload not found")

    cid = meta.get("client_id")
    if cid and cid in transfer_service.active_uploads:
        path = meta.get("final_path")
        if path:
            transfer_service.active_uploads[cid].pop(path, None)

    bg_tasks.add_task(transfer_service.cleanup_session, upload_id, "upload")
    return {"status": "cancelled"}


# --- DOWNLOAD ENDPOINTS ---


@download_router.get("/config")
async def get_download_config():
    return {"recommended_chunk_size": DOWNLOAD_CHUNK_SIZE, "supports_resume": True}


@download_router.post("/initiate", response_model=DownloadInitiateResponse)
async def initiate_download(
    payload: DownloadInitiatePayload, client_id: str = Depends(get_client_id)
):
    try:
        res = await transfer_service.initiate_download(client_id, payload.file_path)
        return DownloadInitiateResponse(**res)
    except FileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    except Exception as e:
        log.error(f"Init download failed: {e}", exc_info=True)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Internal error")


@download_router.get("/status/{download_id}", response_model=DownloadStatusResponse)
async def get_download_status(info: dict = Depends(get_download_session)):
    download_id = info.get("download_id", "unknown")
    prog = (
        (info["bytes_downloaded"] / info["file_size"]) * 100 if info["file_size"] else 0
    )

    return DownloadStatusResponse(
        download_id=download_id,
        file_size=info["file_size"],
        bytes_downloaded=info["bytes_downloaded"],
        progress_percent=round(prog, 2),
        status=info["status"],
    )


@download_router.get("/chunk/{download_id}")
async def download_chunk(
    download_id: str,
    range_header: str = Header(None, alias="Range"),
    info: dict = Depends(get_download_session),
):
    path = Path(info["file_path"])
    fsize = info["file_size"]
    start, end = 0, fsize - 1

    # Robust Range header parsing
    if range_header and range_header.startswith("bytes="):
        try:
            ranges = range_header.replace("bytes=", "").split("-")
            start_str, end_str = ranges[0], ranges[1] if len(ranges) > 1 else ""

            start = int(start_str) if start_str else 0
            end = int(end_str) if end_str else fsize - 1

            # Ensure bounds
            start = max(0, min(start, fsize - 1))
            end = max(start, min(end, fsize - 1))
        except ValueError:
            raise HTTPException(
                status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE, "Invalid Range format"
            )

    chunk_len = (end - start) + 1
    # Note: State updating like this isn't persistent until synced to disk
    info["bytes_downloaded"] = max(info.get("bytes_downloaded", 0), end + 1)

    return StreamingResponse(
        file_service.get_file_iterator(
            path, start, end, chunk_size=DOWNLOAD_CHUNK_SIZE
        ),
        status_code=206,
        headers={
            "Content-Range": f"bytes {start}-{end}/{fsize}",
            "Content-Length": str(chunk_len),
            "Content-Disposition": _encode_filename(info["file_name"]),
        },
    )


@download_router.delete("/cancel/{download_id}")
async def cancel_download(
    download_id: str,
    bg_tasks: BackgroundTasks,
    info: dict = Depends(get_download_session),
):
    client_id = info["client_id"]
    if client_id in transfer_service.active_downloads:
        transfer_service.active_downloads[client_id].pop(download_id, None)

    bg_tasks.add_task(transfer_service.cleanup_session, download_id, "download")
    return {"status": "cancelled"}


# Helper router setup
def restore_sessions_startup():
    return transfer_service.restore_sessions()


async def cleanup_stale_sessions(days=7):
    return await transfer_service.cleanup_stale_sessions(days)
