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
import urllib.parse
from pathlib import Path
from typing import List, Literal

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ...core.validators import validate_filename
from ...services.file_service import (
    AIOFILES_INSTALLED,
    HOME_DIR,
    file_service,
)

if AIOFILES_INSTALLED:
    import aiofiles

log = logging.getLogger(__name__)
router = APIRouter()

ROOT_IDENTIFIER = "_ROOT_"


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


class RenamePayload(BaseModel):
    path: str
    new_name: str = Field(..., min_length=1)


class BatchRenameItem(BaseModel):
    path: str
    new_name: str | None = None
    target_path: str | None = None


class BatchRenamePayload(BaseModel):
    items: List[BatchRenameItem] = Field(..., min_items=1, max_items=10_000)


class CreateFolderPayload(BaseModel):
    parent_path: str
    folder_name: str = Field(..., min_length=1)


class PastePayload(BaseModel):
    source_paths: List[str] = Field(..., min_items=1, max_items=5_000)
    destination_path: str = Field(..., max_length=4096)
    action: Literal["cut", "copy"]
    conflict_resolution: Literal["skip", "overwrite", "rename"] = "skip"


class PathsPayload(BaseModel):
    paths: List[str] = Field(..., min_items=1, max_items=5_000)


class CompressPayload(BaseModel):
    file_paths: List[str] = Field(..., min_items=1)
    output_path: str


class ExtractPayload(BaseModel):
    zip_path: str
    destination: str
    password: str | None = None


class IsEncryptedResponse(BaseModel):
    is_encrypted: bool


def _map_error(e: Exception):
    if isinstance(e, HTTPException):
        raise e  # let FastAPI handle it cleanly
    if isinstance(e, FileNotFoundError):
        raise HTTPException(status_code=404, detail=str(e))
    if isinstance(e, PermissionError):
        raise HTTPException(status_code=403, detail=str(e))
    if isinstance(e, ValueError):
        raise HTTPException(status_code=400, detail=str(e))
    if isinstance(e, shutil.SameFileError):
        raise HTTPException(status_code=409, detail="SOURCE_IS_DEST")
    log.error(f"Internal file error: {e}")
    raise HTTPException(status_code=500, detail="Internal server error")


async def get_file_hash(path: str) -> str:
    """Fast MD5 hashing with 128KB chunks."""
    hasher = hashlib.md5()

    def _read():
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(131072), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    return await asyncio.to_thread(_read)


@router.get("/browse", response_model=DirectoryListing)
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


@router.get("/thumbnail")
async def get_thumbnail(path: str = Query(...)):
    try:
        p = file_service.validate_path(path)
        data = await file_service.get_thumbnail(p)
        if not data:
            raise HTTPException(404, "Thumbnail not available")
        return Response(content=data, media_type="image/png")
    except Exception as e:
        _map_error(e)


@router.post("/compress")
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


@router.post("/extract")
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


@router.post("/create-folder")
async def create_folder(payload: CreateFolderPayload):
    try:
        parent = file_service.validate_path(payload.parent_path)
        name = validate_filename(payload.folder_name)
        new_p = parent / name
        if new_p.exists():
            raise HTTPException(409, "Target already exists")
        await asyncio.to_thread(new_p.mkdir)
        return {"status": "success"}
    except Exception as e:
        _map_error(e)


@router.patch("/rename")
async def rename(payload: RenamePayload):
    try:
        src = file_service.validate_path(payload.path)

        # Support moving via rename call if new_name looks like a path
        if "/" in payload.new_name or "\\" in payload.new_name:
            dest = file_service.validate_path(payload.new_name, check_existence=False)
        else:
            new_n = validate_filename(payload.new_name)
            dest = src.parent / new_n

        if dest.exists() and src != dest:
            raise HTTPException(409, "Target already exists")

        if not dest.parent.exists():
            await asyncio.to_thread(os.makedirs, str(dest.parent), exist_ok=True)

        await asyncio.to_thread(shutil.move, str(src), str(dest))
        return {"status": "success"}
    except Exception as e:
        _map_error(e)


@router.post("/batch-rename")
async def batch_rename(items: List[BatchRenameItem]):
    """
    Executes a batch of renames using a two-pass algorithm to handle
    circular dependencies (e.g. A->B and B->C).
    """
    results = []
    wait_list = []
    success_count = 0

    async def _do_rename(item: BatchRenameItem, is_retry: bool = False) -> dict:
        try:
            src = file_service.validate_path(item.path)

            # Use Path for OS-independent joining
            if item.target_path:
                dest = Path(item.target_path)
                # Ensure it's inside a safe root
                if not file_service.is_path_safe(dest):
                    # If target_path is absolute but not in safe root, try to resolve it
                    dest = file_service.validate_path(
                        item.target_path, check_existence=False
                    )
            elif item.new_name:
                if ".." in item.new_name:
                    return {
                        "path": item.path,
                        "status": "error",
                        "error": "UNSAFE_PATH",
                    }
                dest = src.parent / item.new_name
            else:
                return {
                    "path": item.path,
                    "status": "error",
                    "error": "MISSING_DESTINATION",
                }

            # Standardize path
            dest = dest.resolve(strict=False)

            # Detect conflicts
            if dest.exists() and src.resolve() != dest.resolve():
                # On first pass, if target exists, it might move later. Add to wait_list.
                if not is_retry:
                    return {"path": item.path, "status": "conflict"}

                # On second pass, check if it's an identical duplicate to clean up
                src_stat = src.stat()
                dest_stat = dest.stat()
                if src_stat.st_size == dest_stat.st_size:
                    if await get_file_hash(str(src)) == await get_file_hash(str(dest)):
                        await asyncio.to_thread(os.remove, str(src))
                        return {
                            "path": item.path,
                            "status": "duplicate_deleted",
                            "new_path": str(dest),
                        }

                return {"path": item.path, "status": "error", "error": "TARGET_EXISTS"}

            # Ensure parent exists
            if not dest.parent.exists():
                await asyncio.to_thread(os.makedirs, str(dest.parent), exist_ok=True)

            await asyncio.to_thread(shutil.move, str(src), str(dest))
            return {"path": item.path, "status": "success", "new_path": str(dest)}

        except Exception as e:
            log.error(f"Rename failed for {item.path}: {e}")
            return {"path": item.path, "status": "error", "error": str(e)}

    # Pass 1: Rename what we can (Chunked to prevent flooding the thread pool and FD limits)
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

    # Pass 2: Retry conflicts sequentially (to resolve chains)
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


@router.post("/delete")
async def delete(payload: PathsPayload):
    results = await file_service.delete_items(payload.paths)
    return {
        "succeeded": [r for r in results if r["success"]],
        "failed": [r for r in results if not r["success"]],
    }


@router.post("/open")
async def open_file(payload: PathPayload):
    try:
        p = file_service.validate_path(payload.path)
        if sys.platform == "win32":
            os.startfile(p)
        elif sys.platform == "darwin":
            subprocess.Popen(
                ["open", str(p)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        else:
            # Use Popen to avoid blocking the event loop and suppress noisy stderr output (like Qt warnings)
            subprocess.Popen(
                ["xdg-open", str(p)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        return {"status": "success"}
    except Exception as e:
        _map_error(e)


@router.post("/paste")
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


@router.get("/download")
async def download(path: str = Query(...)):
    try:
        p = file_service.validate_path(path)
        if not p.is_file():
            raise HTTPException(400, "Not a file")

        async def _iter():
            if AIOFILES_INSTALLED:
                async with aiofiles.open(p, "rb") as f:
                    while chunk := await f.read(65536):
                        yield chunk
            else:
                with p.open("rb") as f:
                    while chunk := f.read(65536):
                        yield chunk

        headers = {
            "Content-Disposition": f'attachment; filename="{urllib.parse.quote(p.name)}"'
        }
        return StreamingResponse(
            _iter(), media_type="application/octet-stream", headers=headers
        )
    except Exception as e:
        _map_error(e)
