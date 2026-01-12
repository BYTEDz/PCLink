# src/pclink/api_server/file_browser.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import json
import logging
import os
import platform
import subprocess
import urllib.parse
from pathlib import Path
from typing import List, Literal

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..core.validators import validate_filename
from ..services.file_service import file_service, HOME_DIR, THUMBNAIL_CACHE_DIR, AIOFILES_INSTALLED

if AIOFILES_INSTALLED:
    import aiofiles

log = logging.getLogger(__name__)
router = APIRouter()

ROOT_IDENTIFIER = "_ROOT_"

class FileItem(BaseModel):
    name: str; path: str; is_dir: bool; size: int; modified_at: float; item_type: str

class DirectoryListing(BaseModel):
    current_path: str; parent_path: str | None; items: List[FileItem]

class PathPayload(BaseModel): path: str

class RenamePayload(BaseModel):
    path: str; new_name: str = Field(..., min_length=1)

class CreateFolderPayload(BaseModel):
    parent_path: str; folder_name: str = Field(..., min_length=1)

class PastePayload(BaseModel):
    source_paths: List[str] = Field(..., min_items=1)
    destination_path: str; action: Literal["cut", "copy"]
    conflict_resolution: Literal["skip", "overwrite", "rename"] = "skip"

class PathsPayload(BaseModel): paths: List[str] = Field(..., min_items=1)

class CompressPayload(BaseModel):
    file_paths: List[str] = Field(..., min_items=1); output_path: str

class ExtractPayload(BaseModel):
    zip_path: str; destination: str; password: str | None = None

class IsEncryptedResponse(BaseModel): is_encrypted: bool

def _map_error(e: Exception):
    if isinstance(e, FileNotFoundError): raise HTTPException(status_code=404, detail=str(e))
    if isinstance(e, PermissionError): raise HTTPException(status_code=403, detail=str(e))
    if isinstance(e, ValueError): raise HTTPException(status_code=400, detail=str(e))
    log.error(f"Internal file error: {e}")
    raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/browse", response_model=DirectoryListing)
async def browse_directory(path: str | None = Query(None)):
    if not path or path == ROOT_IDENTIFIER:
        items = [FileItem(name=str(r), path=str(r), is_dir=True, size=0, modified_at=0, item_type="drive") 
                 for r in file_service.get_system_roots()]
        if HOME_DIR.exists():
            st = HOME_DIR.stat()
            items.append(FileItem(name="Home", path=str(HOME_DIR), is_dir=True, size=st.st_size, modified_at=st.st_mtime, item_type="home"))
        return DirectoryListing(current_path=ROOT_IDENTIFIER, parent_path=None, items=items)

    try:
        p = file_service.validate_path(path)
        items = await file_service.scan_directory(p)
        
        is_root = any(str(p) == str(r) for r in file_service.get_system_roots())
        parent = str(p.parent) if not is_root else ROOT_IDENTIFIER
        if p.samefile(HOME_DIR): parent = ROOT_IDENTIFIER
        
        return DirectoryListing(current_path=str(p), parent_path=parent, items=[FileItem(**i) for i in items])
    except Exception as e: _map_error(e)

@router.get("/thumbnail")
async def get_thumbnail(path: str = Query(...)):
    try:
        p = file_service.validate_path(path)
        data = await file_service.get_thumbnail(p)
        if not data: raise HTTPException(404, "Thumbnail not available")
        return Response(content=data, media_type="image/png")
    except Exception as e: _map_error(e)

@router.post("/compress")
async def compress(payload: CompressPayload):
    async def _stream():
        try:
            gen = await file_service.compress(payload.file_paths, payload.output_path)
            for prog in gen: yield f"data: {json.dumps({'progress': prog})}\n\n"
            yield f"data: {json.dumps({'status': 'complete', 'progress': 100})}\n\n"
        except Exception as e: yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"
    return StreamingResponse(_stream(), media_type="text/event-stream")

@router.post("/extract")
async def extract(payload: ExtractPayload):
    async def _stream():
        try:
            p = file_service.validate_path(payload.zip_path)
            dest = file_service.validate_path(payload.destination, check_existence=False)
            gen = await file_service.extract(p, dest, payload.password)
            for prog in gen: yield f"data: {json.dumps({'progress': prog})}\n\n"
            yield f"data: {json.dumps({'status': 'complete', 'progress': 100})}\n\n"
        except Exception as e: yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"
    return StreamingResponse(_stream(), media_type="text/event-stream")

@router.post("/create-folder")
async def create_folder(payload: CreateFolderPayload):
    try:
        parent = file_service.validate_path(payload.parent_path)
        name = validate_filename(payload.folder_name)
        new_p = parent / name
        if new_p.exists(): raise HTTPException(409, "Target already exists")
        await asyncio.to_thread(new_p.mkdir)
        return {"status": "success"}
    except Exception as e: _map_error(e)

@router.patch("/rename")
async def rename(payload: RenamePayload):
    try:
        src = file_service.validate_path(payload.path)
        new_n = validate_filename(payload.new_name)
        dest = src.parent / new_n
        if dest.exists(): raise HTTPException(409, "Target already exists")
        await asyncio.to_thread(src.rename, dest)
        return {"status": "success"}
    except Exception as e: _map_error(e)

@router.post("/delete")
async def delete(payload: PathsPayload):
    results = await file_service.delete_items(payload.paths)
    return {"succeeded": [r for r in results if r["success"]], "failed": [r for r in results if not r["success"]]}

@router.post("/open")
async def open_file(payload: PathPayload):
    try:
        p = file_service.validate_path(payload.path)
        if sys.platform == "win32": os.startfile(p)
        elif sys.platform == "darwin": subprocess.run(["open", str(p)])
        else: subprocess.run(["xdg-open", str(p)])
        return {"status": "success"}
    except Exception as e: _map_error(e)

@router.post("/paste")
async def paste(payload: PastePayload):
    try:
        dest = file_service.validate_path(payload.destination_path)
        res = await file_service.move_copy(payload.source_paths, dest, payload.action, payload.conflict_resolution)
        if res["conflicts"]: raise HTTPException(409, {"message": "Conflicts", "conflicting_items": res["conflicts"]})
        return res
    except Exception as e: _map_error(e)

@router.get("/download")
async def download(path: str = Query(...)):
    try:
        p = file_service.validate_path(path)
        if not p.is_file(): raise HTTPException(400, "Not a file")
        
        async def _iter():
            if AIOFILES_INSTALLED:
                async with aiofiles.open(p, "rb") as f:
                    while chunk := await f.read(65536): yield chunk
            else:
                with p.open("rb") as f:
                    while chunk := f.read(65536): yield chunk
                    
        headers = {"Content-Disposition": f'attachment; filename="{urllib.parse.quote(p.name)}"'}
        return StreamingResponse(_iter(), media_type="application/octet-stream", headers=headers)
    except Exception as e: _map_error(e)