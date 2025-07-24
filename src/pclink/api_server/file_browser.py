"""
PCLink - Remote PC Control Server - File Browser API Module
Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published
by the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.
"""

import json
import logging
import os
import platform
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Dict, List

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..core.validators import validate_filename

log = logging.getLogger(__name__)


# --- Pydantic Models ---
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


class CreateFolderPayload(BaseModel):
    parent_path: str
    folder_name: str = Field(..., min_length=1)


class UploadInitiatePayload(BaseModel):
    file_name: str
    destination_path: str


class UploadInitiateResponse(BaseModel):
    upload_id: str


# --- API Routers ---
router = APIRouter()
upload_router = APIRouter()

# --- Constants and State ---
ROOT_IDENTIFIER = "_ROOT_"
HOME_DIR = Path.home().resolve()
TEMP_UPLOAD_DIR = HOME_DIR / ".pclink_uploads"
TEMP_UPLOAD_DIR.mkdir(exist_ok=True, parents=True)
ACTIVE_UPLOADS: Dict[str, str] = {}  # Maps final_file_path to upload_id


def _get_system_roots() -> List[Path]:
    """Returns the root directories for the current operating system."""
    if platform.system() == "Windows":
        return [
            Path(f"{d}:\\")
            for d in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            if Path(f"{d}:").exists()
        ]
    return [Path("/")]


def _is_path_within_safe_roots(path_to_check: Path, safe_roots: List[Path]) -> bool:
    """Checks if a resolved path is within one of the safe root directories."""
    try:
        resolved_path = path_to_check.resolve()
        return any(resolved_path.is_relative_to(root.resolve()) for root in safe_roots)
    except (OSError, RuntimeError):
        return any(str(path_to_check).startswith(str(root)) for root in safe_roots)


def _validate_and_resolve_path(user_path_str: str) -> Path:
    """Validates a user-provided path to ensure it's safe and absolute."""
    if not user_path_str or ".." in user_path_str:
        raise HTTPException(
            status_code=403, detail="Invalid or disallowed path characters."
        )

    path = Path(user_path_str)
    safe_roots = _get_system_roots() + [HOME_DIR]

    if not path.is_absolute():
        path = HOME_DIR / path

    if not _is_path_within_safe_roots(path, safe_roots):
        raise HTTPException(
            status_code=403, detail="Access to the specified path is denied."
        )

    return path


# --- Chunked File Upload Endpoints ---
@upload_router.post("/initiate", response_model=UploadInitiateResponse)
async def initiate_upload(payload: UploadInitiatePayload):
    dest_path = _validate_and_resolve_path(payload.destination_path)
    if not dest_path.is_dir():
        raise HTTPException(status_code=400, detail="Destination is not a directory")

    safe_filename = validate_filename(payload.file_name)
    final_file_path = dest_path / safe_filename
    final_file_path_str = str(final_file_path)

    # Resume logic: if this exact file is already being uploaded, return the existing ID.
    if final_file_path_str in ACTIVE_UPLOADS:
        existing_id = ACTIVE_UPLOADS[final_file_path_str]
        if (TEMP_UPLOAD_DIR / f"{existing_id}.part").exists():
            log.info(f"Resuming upload for {safe_filename} with ID {existing_id}")
            return UploadInitiateResponse(upload_id=existing_id)
        else:
            del ACTIVE_UPLOADS[final_file_path_str]  # Clean up stale entry

    upload_id = str(uuid.uuid4())
    metadata = {"final_path": final_file_path_str, "file_name": safe_filename}

    (TEMP_UPLOAD_DIR / f"{upload_id}.meta").write_text(
        json.dumps(metadata), encoding="utf-8"
    )
    (TEMP_UPLOAD_DIR / f"{upload_id}.part").touch()

    ACTIVE_UPLOADS[final_file_path_str] = upload_id
    log.info(f"Initiated new upload for {safe_filename} with ID {upload_id}")
    return UploadInitiateResponse(upload_id=upload_id)


@upload_router.get("/status/{upload_id}")
async def get_upload_status(upload_id: str):
    part_file = TEMP_UPLOAD_DIR / f"{upload_id}.part"
    if not part_file.exists():
        raise HTTPException(status_code=404, detail="Upload not found or expired.")
    return {"bytes_received": part_file.stat().st_size}


@upload_router.post("/chunk/{upload_id}")
async def upload_chunk(upload_id: str, request: Request, offset: int = Query(...)):
    part_file = TEMP_UPLOAD_DIR / f"{upload_id}.part"
    if not part_file.exists():
        raise HTTPException(
            status_code=404, detail="Upload session not found or expired."
        )
    try:
        with part_file.open("rb+") as f:
            f.seek(offset)
            async for chunk in request.stream():
                f.write(chunk)
    except Exception as e:
        log.error(f"Error writing chunk for upload {upload_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error writing file chunk: {e}")
    return {"status": "chunk received"}


@upload_router.post("/complete/{upload_id}")
async def complete_upload(upload_id: str):
    part_file = TEMP_UPLOAD_DIR / f"{upload_id}.part"
    meta_file = TEMP_UPLOAD_DIR / f"{upload_id}.meta"
    if not part_file.exists() or not meta_file.exists():
        raise HTTPException(status_code=404, detail="Upload not found or expired.")

    metadata = json.loads(meta_file.read_text(encoding="utf-8"))
    final_path = Path(metadata["final_path"])

    try:
        final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(part_file), str(final_path))
    except Exception as e:
        part_file.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Error moving completed file: {e}")
    finally:
        meta_file.unlink(missing_ok=True)
        if (final_path_str := metadata.get("final_path")) in ACTIVE_UPLOADS:
            del ACTIVE_UPLOADS[final_path_str]

    log.info(f"Completed upload for {final_path.name}")
    return {"status": "completed", "path": str(final_path)}


@upload_router.delete("/cancel/{upload_id}")
async def cancel_upload(upload_id: str):
    part_file = TEMP_UPLOAD_DIR / f"{upload_id}.part"
    meta_file = TEMP_UPLOAD_DIR / f"{upload_id}.meta"

    final_path_str = None
    if meta_file.exists():
        try:
            metadata = json.loads(meta_file.read_text(encoding="utf-8"))
            final_path_str = metadata.get("final_path")
        except Exception as e:
            log.warning(
                f"Could not read metadata for cancelled upload {upload_id}: {e}"
            )
        meta_file.unlink(missing_ok=True)

    part_file.unlink(missing_ok=True)

    if final_path_str and final_path_str in ACTIVE_UPLOADS:
        del ACTIVE_UPLOADS[final_path_str]

    log.info(f"Cancelled upload {upload_id}")
    return {"status": "cancelled"}


# --- File Browsing and Management Endpoints ---
# (These remain unchanged as they were not part of the upload logic issue)
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
            for r in _get_system_roots()
        ]
        home_stat = HOME_DIR.stat()
        items.append(
            FileItem(
                name="Home",
                path=str(HOME_DIR),
                is_dir=True,
                size=home_stat.st_size,
                modified_at=home_stat.st_mtime,
                item_type="home",
            )
        )
        return DirectoryListing(
            current_path=ROOT_IDENTIFIER, parent_path=None, items=items
        )

    current_path = _validate_and_resolve_path(path)
    if not current_path.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory.")

    content = []
    try:
        for entry in os.scandir(current_path):
            try:
                stat = entry.stat()
                is_dir = entry.is_dir()
                content.append(
                    FileItem(
                        name=entry.name,
                        path=entry.path,
                        is_dir=is_dir,
                        size=stat.st_size,
                        modified_at=stat.st_mtime,
                        item_type="folder" if is_dir else "file",
                    )
                )
            except (OSError, PermissionError):
                continue
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading directory: {e}")

    content.sort(key=lambda x: (not x.is_dir, x.name.lower()))
    is_root = any(current_path == root for root in _get_system_roots() + [HOME_DIR])
    parent_path_str = str(current_path.parent) if not is_root else ROOT_IDENTIFIER

    return DirectoryListing(
        current_path=str(current_path), parent_path=parent_path_str, items=content
    )


@router.post("/create-folder")
async def create_folder(payload: CreateFolderPayload):
    parent_dir = _validate_and_resolve_path(payload.parent_path)
    safe_folder_name = validate_filename(payload.folder_name)
    new_folder_path = parent_dir / safe_folder_name

    if new_folder_path.exists():
        raise HTTPException(
            status_code=409, detail="A file or folder with this name already exists."
        )
    try:
        new_folder_path.mkdir()
        return {"status": "success", "message": f"Folder '{safe_folder_name}' created."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create folder: {e}")


@router.patch("/rename")
async def rename_item(payload: RenamePayload):
    source_path = _validate_and_resolve_path(payload.path)
    safe_new_name = validate_filename(payload.new_name)
    dest_path = source_path.parent / safe_new_name

    if not source_path.exists():
        raise HTTPException(status_code=404, detail="Item to rename not found.")
    if dest_path.exists():
        raise HTTPException(
            status_code=409, detail="An item with the new name already exists."
        )
    try:
        source_path.rename(dest_path)
        return {"status": "success", "message": "Item renamed successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to rename item: {e}")


@router.post("/delete")
async def delete_item(payload: PathPayload):
    # This endpoint now uses the POST method with a body to be more explicit.
    target_path = _validate_and_resolve_path(payload.path)
    if not target_path.exists():
        raise HTTPException(status_code=404, detail="Item to delete not found.")
    try:
        if target_path.is_dir():
            shutil.rmtree(target_path)
        else:
            target_path.unlink()
        return {"status": "success", "message": "Item deleted successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete item: {e}")


@router.get("/download")
async def download_file(path: str = Query(...)):
    file_path = _validate_and_resolve_path(path)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="The specified path is not a file.")
    return FileResponse(path=file_path, filename=file_path.name)


@router.post("/open")
async def open_file_on_server(payload: PathPayload):
    target_path = _validate_and_resolve_path(payload.path)
    if not target_path.exists():
        raise HTTPException(status_code=404, detail="File or directory not found.")
    try:
        if platform.system() == "Windows":
            os.startfile(target_path)
        elif platform.system() == "Darwin":
            subprocess.run(["open", str(target_path)], check=True)
        else:
            subprocess.run(["xdg-open", str(target_path)], check=True)
        return {
            "status": "success",
            "message": f"'{target_path.name}' is being opened.",
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Could not open '{target_path.name}': {e}"
        )
