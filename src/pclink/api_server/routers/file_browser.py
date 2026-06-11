# src/pclink/api_server/file_browser.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
from typing import List, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from ...core.validators import validate_filename
from ...services.file_service import HOME_DIR, file_service
from .dependencies import verify_api_key
from ...core.share_manager import share_manager

log = logging.getLogger(__name__)

# NOTE: Enforce authentication for all file operations
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
def _map_error(e: Exception):
    if isinstance(e, HTTPException):
        raise e
    if isinstance(e, FileNotFoundError):
        raise HTTPException(status_code=404, detail="File or directory not found")
    if isinstance(e, PermissionError):
        raise HTTPException(status_code=403, detail="Permission denied")
    if isinstance(e, ValueError):
        raise HTTPException(status_code=400, detail=str(e))
    if isinstance(e, shutil.SameFileError):
        raise HTTPException(status_code=409, detail="SOURCE_IS_DEST")

    log.error(f"Internal file error: {e}", exc_info=True)
    raise HTTPException(status_code=500, detail="Internal server error")


async def get_file_hash(path: str) -> str:
    """Fast hashing utilizing native C-implementation in modern Python."""

    def _read():
        with open(path, "rb") as f:
            # Python 3.11+ native file hashing
            if hasattr(hashlib, "file_digest"):
                return hashlib.file_digest(f, "md5").hexdigest()
            # Fallback
            hasher = hashlib.md5()
            for chunk in iter(lambda: f.read(131072), b""):
                hasher.update(chunk)
            return hasher.hexdigest()

    return await asyncio.to_thread(_read)


# --- Endpoints ---


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
    # 1. Try standard API key verification
    try:
        # We simulate the call to verify_api_key by checking the token
        # since verify_api_key is a dependency and not a simple function.
        # However, we can use the device_manager directly.
        from ...core.device_manager import device_manager

        key = token
        if not key and request:
            key = request.headers.get("X-API-Key") or request.cookies.get(
                "pclink_device_token"
            )

        if key:
            device = device_manager.get_device_by_api_key(key)
            if device and device.is_approved:
                return True
    except Exception:
        pass

    # 2. Try share token verification
    if token and path:
        if share_manager.validate_share_token(token, path):
            return True

    raise HTTPException(status_code=403, detail="Invalid or missing access token")


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
        return DirectoryListing(
            current_path=ROOT_IDENTIFIER, parent_path=None, items=items
        )

    try:
        p = file_service.validate_path(path)
        items = await file_service.scan_directory(p)

        is_root = any(str(p) == str(r) for r in file_service.get_system_roots())
        parent = str(p.parent) if not is_root else ROOT_IDENTIFIER
        if p.samefile(HOME_DIR):
            parent = ROOT_IDENTIFIER

        return DirectoryListing(
            current_path=str(p),
            parent_path=parent,
            items=[FileItem(**i) for i in items],
        )
    except Exception as e:
        _map_error(e)


@router.get("/thumbnail", dependencies=[Depends(verify_api_key)])
async def get_thumbnail(path: str = Query(...)):
    try:
        p = file_service.validate_path(path)
        data = await file_service.get_thumbnail(p)
        if not data:
            raise HTTPException(404, "Thumbnail not available")
        return Response(content=data, media_type="image/png")
    except Exception as e:
        _map_error(e)


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
    try:
        parent = file_service.validate_path(payload.parent_path)
        name = validate_filename(payload.folder_name)
        new_p = parent / name

        # Security: Re-validate to ensure name traversal didn't escape constraints
        new_p = file_service.validate_path(str(new_p), check_existence=False)

        if new_p.exists():
            raise HTTPException(409, "Target already exists")

        await asyncio.to_thread(new_p.mkdir)
        return {"status": "success"}
    except Exception as e:
        _map_error(e)


@router.patch("/rename", dependencies=[Depends(verify_api_key)])
async def rename(payload: RenamePayload):
    try:
        src = file_service.validate_path(payload.path)

        if "/" in payload.new_name or "\\" in payload.new_name:
            dest = file_service.validate_path(payload.new_name, check_existence=False)
        else:
            new_n = validate_filename(payload.new_name)
            dest = src.parent / new_n

        # Security: Always validate the final destination path
        dest = file_service.validate_path(str(dest), check_existence=False)

        if dest.exists() and src.resolve() != dest.resolve():
            raise HTTPException(409, "Target already exists")

        if not dest.parent.exists():
            await asyncio.to_thread(os.makedirs, str(dest.parent), exist_ok=True)

        await asyncio.to_thread(shutil.move, str(src), str(dest))
        return {"status": "success"}
    except Exception as e:
        _map_error(e)


@router.post("/batch-rename", dependencies=[Depends(verify_api_key)])
async def batch_rename(payload: BatchRenamePayload):  # Fixed payload validation
    items = payload.items
    results, wait_list = [], []
    success_count = 0

    async def _do_rename(item: BatchRenameItem, is_retry: bool = False) -> dict:
        try:
            src = file_service.validate_path(item.path)

            if item.target_path:
                dest = file_service.validate_path(
                    item.target_path, check_existence=False
                )
            elif item.new_name:
                if (
                    ".." in item.new_name
                    or "/" in item.new_name
                    or "\\" in item.new_name
                ):
                    return {
                        "path": item.path,
                        "status": "error",
                        "error": "UNSAFE_PATH",
                    }
                raw_dest = src.parent / item.new_name
                # Security: Enforce final validation check
                dest = file_service.validate_path(str(raw_dest), check_existence=False)
            else:
                return {
                    "path": item.path,
                    "status": "error",
                    "error": "MISSING_DESTINATION",
                }

            dest = dest.resolve(strict=False)

            if dest.exists() and src.resolve() != dest.resolve():
                if not is_retry:
                    return {"path": item.path, "status": "conflict"}

                src_stat, dest_stat = src.stat(), dest.stat()
                if src_stat.st_size == dest_stat.st_size:
                    if await get_file_hash(str(src)) == await get_file_hash(str(dest)):
                        await asyncio.to_thread(os.remove, str(src))
                        return {
                            "path": item.path,
                            "status": "duplicate_deleted",
                            "new_path": str(dest),
                        }

                return {"path": item.path, "status": "error", "error": "TARGET_EXISTS"}

            if not dest.parent.exists():
                await asyncio.to_thread(os.makedirs, str(dest.parent), exist_ok=True)

            await asyncio.to_thread(shutil.move, str(src), str(dest))
            return {"path": item.path, "status": "success", "new_path": str(dest)}

        except Exception as e:
            log.error(f"Rename failed for {item.path}: {e}")
            return {"path": item.path, "status": "error", "error": str(e)}

    chunk_size = 50
    first_pass_results = []

    for i in range(0, len(items), chunk_size):
        chunk = items[i : i + chunk_size]
        chunk_res = await asyncio.gather(*[_do_rename(item) for item in chunk])
        first_pass_results.extend(chunk_res)

    for i, res in enumerate(first_pass_results):
        if res["status"] == "conflict":
            wait_list.append(items[i])
        else:
            if res["status"] in ["success", "duplicate_deleted"]:
                success_count += 1
            results.append(res)

    if wait_list:
        for item in wait_list:
            res = await _do_rename(item, is_retry=True)
            if res["status"] in ["success", "duplicate_deleted"]:
                success_count += 1
            results.append(res)

    return {
        "success_count": success_count,
        "error_count": len(items) - success_count,
        "results": results,
    }


@router.post("/delete", dependencies=[Depends(verify_api_key)])
async def delete(payload: PathsPayload):
    results = await file_service.delete_items(payload.paths)
    return {
        "succeeded": [r for r in results if r["success"]],
        "failed": [r for r in results if not r["success"]],
    }


@router.post("/open", dependencies=[Depends(verify_api_key)])
async def open_file(payload: PathPayload):
    try:
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
    except Exception as e:
        _map_error(e)


@router.post("/paste", dependencies=[Depends(verify_api_key)])
async def paste(payload: PastePayload):
    try:
        dest = file_service.validate_path(payload.destination_path)
        res = await file_service.move_copy(
            payload.source_paths, dest, payload.action, payload.conflict_resolution
        )
        if res["conflicts"]:
            raise HTTPException(
                409, {"message": "Conflicts", "conflicting_items": res["conflicts"]}
            )
        return res
    except Exception as e:
        _map_error(e)


@router.get("/shares", dependencies=[Depends(verify_api_key)])
async def list_shares(request: Request):
    """List all active share links created by the calling device."""
    from ...core.device_manager import device_manager

    key = request.headers.get("X-API-Key") or request.cookies.get("pclink_device_token")
    if not key:
        key = request.query_params.get("token")

    device_id = "unknown_device"
    if key:
        device = device_manager.get_device_by_api_key(key)
        if device:
            device_id = device.device_id

    return {"shares": share_manager.list_shares_for_device(device_id)}


@router.delete("/shares/{share_token}", dependencies=[Depends(verify_api_key)])
async def revoke_share(share_token: str, request: Request):
    """Revoke a specific share token. Only succeeds if it belongs to the calling device."""
    from ...core.device_manager import device_manager

    key = request.headers.get("X-API-Key") or request.cookies.get("pclink_device_token")
    if not key:
        key = request.query_params.get("token")

    device_id = "unknown_device"
    if key:
        device = device_manager.get_device_by_api_key(key)
        if device:
            device_id = device.device_id

    # Only allow revocation if token belongs to this device
    shares = share_manager.list_shares_for_device(device_id)
    owned = any(s["token"] == share_token for s in shares)
    if not owned:
        # Also check expired ones to still allow explicit revocation
        with share_manager._lock:
            import sqlite3 as _sqlite3

            with _sqlite3.connect(share_manager.db_path) as conn:
                row = conn.execute(
                    "SELECT device_id FROM shared_links WHERE token = ?", (share_token,)
                ).fetchone()
                if not row or row[0] != device_id:
                    raise HTTPException(status_code=404, detail="Share token not found")

    share_manager.revoke_share_link(share_token)
    return {"status": "revoked"}


@router.post("/share", response_model=dict, dependencies=[Depends(verify_api_key)])
async def share_file(payload: SharePayload, request: Request):
    try:
        from ...core.device_manager import device_manager

        # Extract API key to find the device_id
        key = request.headers.get("X-API-Key") or request.cookies.get(
            "pclink_device_token"
        )
        if not key:
            key = request.query_params.get("token")

        device_id = "unknown_device"
        if key:
            device = device_manager.get_device_by_api_key(key)
            if device:
                device_id = device.device_id

        token = share_manager.create_share_link(
            path=payload.path, device_id=device_id, expires_in=payload.expires_in
        )

        # Construct the full download URL
        base_url = str(request.base_url).rstrip("/")
        download_url = f"{base_url}/files/download?path={payload.path}&token={token}"

        return {
            "token": token,
            "download_url": download_url,
            "expires_in": payload.expires_in,
        }
    except Exception as e:
        _map_error(e)


@router.get("/download", dependencies=[Depends(verify_download_access)])
async def download(path: str = Query(...)):
    try:
        p = file_service.validate_path(path)
        if not p.is_file():
            raise HTTPException(400, "Requested path is not a file")

        # FastAPI Native FileResponse handles chunking, async I/O, range headers, and mime-types securely
        return FileResponse(
            path=str(p), filename=p.name, content_disposition_type="attachment"
        )
    except Exception as e:
        _map_error(e)
