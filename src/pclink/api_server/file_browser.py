# PCLink - Remote PC Control Server - File Browser API Module
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

import asyncio
import json
import logging
import os
import platform
import shutil
import subprocess
import time
import uuid
import urllib.parse
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

from fastapi import (APIRouter, BackgroundTasks, HTTPException, Query, Request,
                     Header)
from fastapi.responses import FileResponse, StreamingResponse
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
router = APIRouter()
upload_router = APIRouter()
download_router = APIRouter()

# --- Constants and State ---
ROOT_IDENTIFIER = "_ROOT_"
HOME_DIR = Path.home().resolve()
TEMP_UPLOAD_DIR = HOME_DIR / ".pclink_uploads"
TEMP_UPLOAD_DIR.mkdir(exist_ok=True, parents=True)

# In-memory state for active transfers. For robustness in production,
# consider a more persistent store like Redis or a simple database.
ACTIVE_UPLOADS: Dict[str, str] = {}  # Maps final_file_path -> upload_id
ACTIVE_DOWNLOADS: Dict[str, Dict] = {}  # Maps download_id -> download metadata
TRANSFER_LOCKS: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


# --- Utility Functions ---
def _encode_filename_for_header(filename: str) -> str:
    """
    Properly encode filename for Content-Disposition header.
    Uses RFC 5987 encoding for non-ASCII filenames.
    """
    try:
        # Try to encode as ASCII first (for simple filenames)
        filename.encode('ascii')
        return f'attachment; filename="{filename}"'
    except UnicodeEncodeError:
        # Use RFC 5987 encoding for non-ASCII filenames
        encoded_filename = urllib.parse.quote(filename, safe='')
        return f"attachment; filename*=UTF-8''{encoded_filename}"

def _get_system_roots() -> List[Path]:
    """Returns the root directories for the current operating system."""
    if platform.system() == "Windows":
        return [
            Path(f"{d}:\\")
            for d in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            if Path(f"{d}:").exists()
        ]
    return [Path("/")]


def _is_path_within_safe_roots(path_to_check: Path) -> bool:
    """Checks if a resolved path is within one of the safe root directories."""
    safe_roots = _get_system_roots() + [HOME_DIR]
    
    try:
        log.info(f"DEBUG: Checking if path is within safe roots: {path_to_check}")
        
        # Use strict=False to handle Unicode paths better
        try:
            resolved_path = path_to_check.resolve(strict=False)
            log.info(f"DEBUG: Resolved path for safety check: {resolved_path}")
        except Exception as e:
            log.warning(f"DEBUG: Could not resolve path for safety check: {e}")
            resolved_path = path_to_check
        
        # Check against each safe root
        for root in safe_roots:
            try:
                resolved_root = root.resolve(strict=False)
                log.info(f"DEBUG: Checking against safe root: {resolved_root}")
                
                # Check if paths are equal or if root is a parent
                if resolved_path == resolved_root or resolved_root in resolved_path.parents:
                    log.info(f"DEBUG: Path is within safe root: {resolved_root}")
                    return True
                    
            except Exception as e:
                log.warning(f"DEBUG: Error checking safe root {root}: {e}")
                continue
        
        log.warning(f"DEBUG: Path is not within any safe root: {resolved_path}")
        return False
        
    except (FileNotFoundError, RuntimeError, OSError) as e:
        log.warning(f"DEBUG: Exception in safe roots check, using fallback: {e}")
        # Fallback for paths that don't exist yet (e.g., for uploads)
        # This check is less secure but necessary for some operations.
        try:
            path_str = str(path_to_check)
            for root in safe_roots:
                try:
                    root_str = str(root.resolve(strict=False))
                    if path_str.startswith(root_str):
                        log.info(f"DEBUG: Fallback check passed for root: {root_str}")
                        return True
                except Exception as e2:
                    log.warning(f"DEBUG: Error in fallback check for root {root}: {e2}")
                    continue
            
            log.warning(f"DEBUG: Fallback check failed for path: {path_str}")
            return False
            
        except Exception as e:
            log.error(f"DEBUG: Complete failure in safe roots check: {e}")
            return False


def _validate_and_resolve_path(user_path_str: str) -> Path:
    """Validates a user-provided path to ensure it's safe and absolute."""
    if not user_path_str:
        raise HTTPException(status_code=400, detail="Path cannot be empty.")
    
    try:
        log.info(f"DEBUG: _validate_and_resolve_path called with: '{user_path_str}'")
        log.info(f"DEBUG: Path type: {type(user_path_str)}, repr: {repr(user_path_str)}")
        
        # Handle potential encoding issues
        if isinstance(user_path_str, bytes):
            try:
                user_path_str = user_path_str.decode('utf-8')
                log.info(f"DEBUG: Decoded bytes to string: '{user_path_str}'")
            except UnicodeDecodeError as e:
                log.error(f"DEBUG: Failed to decode bytes path: {e}")
                raise HTTPException(status_code=400, detail=f"Invalid path encoding: {e}")
        
        # Create Path object with proper Unicode handling
        try:
            path = Path(user_path_str)
            log.info(f"DEBUG: Created Path object: {path}")
        except Exception as e:
            log.error(f"DEBUG: Failed to create Path object from '{user_path_str}': {e}")
            raise HTTPException(status_code=400, detail=f"Invalid path format: {e}")
        
        if ".." in path.parts:
            raise HTTPException(
                status_code=403, detail="Relative pathing ('..') is not allowed."
            )

        if not path.is_absolute():
            path = HOME_DIR / path
            log.info(f"DEBUG: Made path absolute: {path}")

        # Use resolve() with strict=False for better Unicode path handling
        try:
            resolved_path = path.resolve(strict=False)
            log.info(f"DEBUG: Resolved path: {resolved_path}")
        except (OSError, RuntimeError) as e:
            log.error(f"DEBUG: Error resolving path '{user_path_str}': {e}")
            raise HTTPException(status_code=400, detail=f"Invalid path: {e}")

        # Check if the resolved path exists - use a more robust method
        try:
            # Try multiple methods to check existence for Unicode paths
            exists = False
            try:
                exists = resolved_path.exists()
                log.info(f"DEBUG: Path.exists() returned: {exists}")
            except (OSError, UnicodeError) as e1:
                log.warning(f"DEBUG: Path.exists() failed, trying os.path.exists(): {e1}")
                try:
                    import os
                    exists = os.path.exists(str(resolved_path))
                    log.info(f"DEBUG: os.path.exists() returned: {exists}")
                except Exception as e2:
                    log.error(f"DEBUG: os.path.exists() also failed: {e2}")
                    raise e1  # Re-raise the original exception
            
            if not exists:
                log.error(f"DEBUG: Path does not exist: {resolved_path}")
                raise HTTPException(status_code=404, detail="File or directory not found.")
                
        except HTTPException:
            raise  # Re-raise HTTP exceptions
        except Exception as e:
            log.error(f"DEBUG: Error checking path existence for '{resolved_path}': {e}")
            raise HTTPException(status_code=500, detail=f"Error accessing path: {e}")

        # Check if path is within safe roots
        try:
            if not _is_path_within_safe_roots(resolved_path):
                log.error(f"DEBUG: Path not within safe roots: {resolved_path}")
                raise HTTPException(
                    status_code=403, detail="Access to the specified path is denied."
                )
        except Exception as e:
            log.error(f"DEBUG: Error checking safe roots for '{resolved_path}': {e}")
            raise HTTPException(status_code=500, detail=f"Error validating path safety: {e}")

        log.info(f"DEBUG: Path validation successful: {resolved_path}")
        return resolved_path
        
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        log.error(f"DEBUG: Unexpected error validating path '{user_path_str}': {e}")
        log.error(f"DEBUG: Exception type: {type(e)}, args: {e.args}")
        raise HTTPException(status_code=500, detail=f"Error processing path: {e}")


async def _cleanup_transfer_session(transfer_id: str):
    """Removes a transfer session and its lock."""
    if transfer_id in TRANSFER_LOCKS:
        del TRANSFER_LOCKS[transfer_id]


# --- Chunked File Upload Endpoints ---
@upload_router.post("/initiate", response_model=UploadInitiateResponse)
async def initiate_upload(payload: UploadInitiatePayload):
    dest_path = _validate_and_resolve_path(payload.destination_path)
    if not dest_path.is_dir():
        raise HTTPException(status_code=400, detail="Destination is not a directory")

    safe_filename = validate_filename(payload.file_name)
    final_file_path = dest_path / safe_filename
    final_file_path_str = str(final_file_path)

    # Lock based on the final file path to prevent race conditions on initiation
    init_lock = TRANSFER_LOCKS[f"init_upload_{final_file_path_str}"]
    async with init_lock:
        if final_file_path_str in ACTIVE_UPLOADS:
            existing_id = ACTIVE_UPLOADS[final_file_path_str]
            if (TEMP_UPLOAD_DIR / f"{existing_id}.part").exists():
                log.info(f"Resuming upload for {safe_filename} with ID {existing_id}")
                return UploadInitiateResponse(upload_id=existing_id)
            else: # Clean up stale entry
                del ACTIVE_UPLOADS[final_file_path_str]

        upload_id = str(uuid.uuid4())
        metadata = {"final_path": final_file_path_str, "file_name": safe_filename}
        (TEMP_UPLOAD_DIR / f"{upload_id}.meta").write_text(json.dumps(metadata), encoding="utf-8")
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
    meta_file = TEMP_UPLOAD_DIR / f"{upload_id}.meta"
    
    lock = TRANSFER_LOCKS[upload_id]
    async with lock:
        if not part_file.exists() or not meta_file.exists():
            raise HTTPException(status_code=404, detail="Upload session not found or expired.")
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
            final_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(part_file), final_path_str)
        except Exception as e:
            part_file.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail=f"Error moving completed file: {e}")
        finally:
            meta_file.unlink(missing_ok=True)
            if final_path_str in ACTIVE_UPLOADS:
                del ACTIVE_UPLOADS[final_path_str]

    background_tasks.add_task(_cleanup_transfer_session, upload_id)
    log.info(f"Completed upload for {final_path.name}")
    return {"status": "completed", "path": final_path_str}


@upload_router.delete("/cancel/{upload_id}")
async def cancel_upload(upload_id: str, background_tasks: BackgroundTasks):
    part_file = TEMP_UPLOAD_DIR / f"{upload_id}.part"
    meta_file = TEMP_UPLOAD_DIR / f"{upload_id}.meta"

    lock = TRANSFER_LOCKS[upload_id]
    async with lock:
        final_path_str = None
        if meta_file.exists():
            try:
                metadata = json.loads(meta_file.read_text(encoding="utf-8"))
                final_path_str = metadata.get("final_path")
            except Exception as e:
                log.warning(f"Could not read metadata for cancelled upload {upload_id}: {e}")
            meta_file.unlink(missing_ok=True)

        part_file.unlink(missing_ok=True)

        if final_path_str and final_path_str in ACTIVE_UPLOADS:
            del ACTIVE_UPLOADS[final_path_str]

    background_tasks.add_task(_cleanup_transfer_session, upload_id)
    log.info(f"Cancelled upload {upload_id}")
    return {"status": "cancelled"}


# --- Chunked File Download Endpoints ---
@download_router.post("/test-path")
async def test_path_handling(payload: DownloadInitiatePayload):
    """Test endpoint to debug Unicode path handling issues."""
    try:
        log.info(f"DEBUG TEST: Received path: {payload.file_path}")
        log.info(f"DEBUG TEST: Path type: {type(payload.file_path)}")
        log.info(f"DEBUG TEST: Path repr: {repr(payload.file_path)}")
        
        # Test basic Path creation
        path = Path(payload.file_path)
        log.info(f"DEBUG TEST: Path object created: {path}")
        
        # Test path resolution
        resolved = path.resolve(strict=False)
        log.info(f"DEBUG TEST: Path resolved: {resolved}")
        
        # Test existence check
        exists = resolved.exists()
        log.info(f"DEBUG TEST: Path exists: {exists}")
        
        if exists:
            # Test file operations
            is_file = resolved.is_file()
            log.info(f"DEBUG TEST: Is file: {is_file}")
            
            if is_file:
                stat_info = resolved.stat()
                log.info(f"DEBUG TEST: File size: {stat_info.st_size}")
        
        return {
            "status": "success",
            "path": str(resolved),
            "exists": exists,
            "is_file": exists and resolved.is_file() if exists else False
        }
        
    except Exception as e:
        log.error(f"DEBUG TEST: Error in path test: {e}")
        return {
            "status": "error",
            "error": str(e),
            "error_type": type(e).__name__
        }

@download_router.post("/initiate", response_model=DownloadInitiateResponse)
async def initiate_download(payload: DownloadInitiatePayload):
    log.info(f"DEBUG: Initiating download for path: {payload.file_path}")
    
    # Handle potential encoding issues with the file path
    try:
        # Ensure the file path is properly decoded if it comes as bytes
        if isinstance(payload.file_path, bytes):
            file_path_str = payload.file_path.decode('utf-8')
        else:
            file_path_str = payload.file_path
        
        log.info(f"DEBUG: Processing file path: {file_path_str}")
        
        # On Windows, try to handle Unicode paths properly
        if platform.system() == "Windows":
            # Convert to raw string to handle Unicode properly
            try:
                # Use os.fspath to handle Path objects properly
                import os
                file_path_str = os.fspath(file_path_str)
            except (TypeError, ValueError):
                pass  # Keep original string if conversion fails
        
        file_path = _validate_and_resolve_path(file_path_str)
        log.info(f"DEBUG: Resolved path: {file_path}")
        
    except HTTPException as e:
        log.error(f"DEBUG: Path validation failed for '{payload.file_path}': {e.detail}")
        raise
    except UnicodeDecodeError as e:
        log.error(f"DEBUG: Unicode decode error for path '{payload.file_path}': {e}")
        raise HTTPException(status_code=400, detail=f"Invalid character encoding in file path: {e}")
    except Exception as e:
        log.error(f"DEBUG: Unexpected error during path validation: {e}")
        raise HTTPException(status_code=500, detail=f"Error processing path: {e}")
    
    try:
        if not file_path.is_file():
            log.error(f"DEBUG: Path is not a file: {file_path}")
            raise HTTPException(status_code=404, detail="File not found or is not a file")
    except (OSError, UnicodeError) as e:
        log.error(f"DEBUG: Error checking if path is file: {e}")
        raise HTTPException(status_code=500, detail=f"Error accessing file: {e}")

    try:
        file_stat = file_path.stat()
        file_size = file_stat.st_size
        log.info(f"DEBUG: File size: {file_size} bytes")
    except Exception as e:
        log.error(f"DEBUG: Error accessing file stats for '{file_path}': {e}")
        raise HTTPException(status_code=500, detail=f"Error accessing file: {e}")

    download_id = str(uuid.uuid4())
    
    try:
        # Store paths as strings to avoid potential serialization issues
        file_path_str = str(file_path)
        file_name = file_path.name
        
        # Ensure file name is properly encoded
        if isinstance(file_name, bytes):
            file_name = file_name.decode('utf-8')
        
        ACTIVE_DOWNLOADS[download_id] = {
            "file_path": file_path_str,
            "file_name": file_name,
            "file_size": file_size,
            "bytes_downloaded": 0,
            "status": "active",
            "file_modified_at": file_stat.st_mtime,
            "session_created_at": time.time(),
        }

        log.info(f"DEBUG: Successfully created download session for '{file_name}' with ID {download_id}")
        return DownloadInitiateResponse(download_id=download_id, file_size=file_size, file_name=file_name)
        
    except Exception as e:
        log.error(f"DEBUG: Error creating download session: {e}")
        raise HTTPException(status_code=500, detail=f"Error creating download session: {e}")


@download_router.get("/status/{download_id}", response_model=DownloadStatusResponse)
async def get_download_status(download_id: str):
    if download_id not in ACTIVE_DOWNLOADS:
        raise HTTPException(status_code=404, detail="Download session not found")

    info = ACTIVE_DOWNLOADS[download_id]
    progress = (info["bytes_downloaded"] / info["file_size"]) * 100 if info["file_size"] > 0 else 0
    return DownloadStatusResponse(
        download_id=download_id,
        file_size=info["file_size"],
        bytes_downloaded=info["bytes_downloaded"],
        progress_percent=round(progress, 2),
        status=info["status"],
    )


@download_router.get("/chunk/{download_id}")
async def download_chunk(download_id: str, request: Request, range_header: str = Header(None, alias="Range")):
    if download_id not in ACTIVE_DOWNLOADS:
        raise HTTPException(status_code=404, detail="Download session not found")

    info = ACTIVE_DOWNLOADS[download_id]
    file_path = Path(info["file_path"])
    file_size = info["file_size"]

    try:
        current_stat = file_path.stat()
        if current_stat.st_size != file_size or current_stat.st_mtime != info["file_modified_at"]:
            raise HTTPException(status_code=409, detail="File has changed since download was initiated.")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File no longer exists.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not stat file: {e}")

    start_byte, end_byte = 0, file_size - 1
    if range_header:
        try:
            range_val = range_header.replace("bytes=", "").split("-")
            start_byte = int(range_val[0])
            end_byte = int(range_val[1]) if len(range_val) > 1 and range_val[1] else file_size - 1
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Range header.")

    if start_byte >= file_size or start_byte > end_byte:
        raise HTTPException(status_code=416, detail="Requested range not satisfiable.")
    
    chunk_size = (end_byte - start_byte) + 1

    def stream_file_range():
        try:
            with file_path.open("rb") as f:
                f.seek(start_byte)
                bytes_to_send = chunk_size
                while bytes_to_send > 0:
                    data = f.read(min(8192, bytes_to_send))
                    if not data:
                        break
                    bytes_to_send -= len(data)
                    yield data
            # This server-side progress tracking relies on the client making distinct
            # range requests. The client is responsible for its own real-time progress.
            info["bytes_downloaded"] = end_byte + 1
        except Exception as e:
            log.error(f"Error streaming file chunk for download {download_id}: {e}")

    headers = {
        "Content-Range": f"bytes {start_byte}-{end_byte}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(chunk_size),
        "Content-Disposition": _encode_filename_for_header(info["file_name"])
    }

    return StreamingResponse(
        stream_file_range(),
        status_code=206, # Partial Content
        headers=headers,
        media_type="application/octet-stream"
    )


@download_router.post("/complete/{download_id}")
async def complete_download(download_id: str, background_tasks: BackgroundTasks):
    if download_id not in ACTIVE_DOWNLOADS:
        raise HTTPException(status_code=404, detail="Download session not found")
    
    ACTIVE_DOWNLOADS[download_id]["status"] = "completed"
    background_tasks.add_task(_cleanup_transfer_session, download_id)
    log.info(f"Completed download {download_id} for {ACTIVE_DOWNLOADS[download_id]['file_name']}")
    return {"status": "completed"}


@download_router.delete("/cancel/{download_id}")
async def cancel_download(download_id: str, background_tasks: BackgroundTasks):
    if download_id not in ACTIVE_DOWNLOADS:
        raise HTTPException(status_code=404, detail="Download session not found")
    
    log.info(f"Cancelled download {download_id} for {ACTIVE_DOWNLOADS[download_id]['file_name']}")
    del ACTIVE_DOWNLOADS[download_id]
    background_tasks.add_task(_cleanup_transfer_session, download_id)
    return {"status": "cancelled"}


# --- File Browsing and Management Endpoints ---
@router.get("/browse", response_model=DirectoryListing)
async def browse_directory(path: str | None = Query(None)):
    if not path or path == ROOT_IDENTIFIER:
        items = [
            FileItem(name=str(r), path=str(r), is_dir=True, size=0, modified_at=0, item_type="drive")
            for r in _get_system_roots()
        ]
        home_stat = HOME_DIR.stat()
        items.append(
            FileItem(
                name="Home", path=str(HOME_DIR), is_dir=True, size=home_stat.st_size,
                modified_at=home_stat.st_mtime, item_type="home"
            )
        )
        return DirectoryListing(current_path=ROOT_IDENTIFIER, parent_path=None, items=items)

    current_path = _validate_and_resolve_path(path)
    if not current_path.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory.")

    content = []
    try:
        for entry in os.scandir(current_path):
            try:
                stat = entry.stat()
                is_dir = entry.is_dir()
                content.append(FileItem(
                    name=entry.name, path=entry.path, is_dir=is_dir, size=stat.st_size,
                    modified_at=stat.st_mtime, item_type="folder" if is_dir else "file"
                ))
            except (OSError, PermissionError):
                continue
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading directory: {e}")

    content.sort(key=lambda x: (not x.is_dir, x.name.lower()))
    is_root = any(current_path.resolve() == r.resolve() for r in _get_system_roots())
    parent_path_str = str(current_path.parent) if not is_root else ROOT_IDENTIFIER
    if current_path.resolve() == HOME_DIR.resolve():
        parent_path_str = ROOT_IDENTIFIER

    return DirectoryListing(current_path=str(current_path), parent_path=parent_path_str, items=content)


@router.post("/create-folder")
async def create_folder(payload: CreateFolderPayload):
    parent_dir = _validate_and_resolve_path(payload.parent_path)
    safe_folder_name = validate_filename(payload.folder_name)
    new_folder_path = parent_dir / safe_folder_name
    if new_folder_path.exists():
        raise HTTPException(status_code=409, detail="A file or folder with this name already exists.")
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
        raise HTTPException(status_code=409, detail="An item with the new name already exists.")
    try:
        source_path.rename(dest_path)
        return {"status": "success", "message": "Item renamed successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to rename item: {e}")


@router.post("/delete")
async def delete_item(payload: PathPayload):
    target_path = _validate_and_resolve_path(payload.path)
    if not target_path.exists():
        return {"status": "success", "message": "Item already deleted."}
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
    """Simple download for smaller files. Recommends chunked download for large files."""
    file_path = _validate_and_resolve_path(path)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="The specified path is not a file.")
    
    file_size = file_path.stat().st_size
    if file_size > 50 * 1024 * 1024:  # 50MB
        raise HTTPException(
            status_code=400,
            detail={
                "message": "File is large. Use the chunked download API for reliability.",
                "file_size": file_size,
                "chunked_download_required": True
            }
        )
    
    # Create a custom FileResponse with proper filename encoding
    from fastapi.responses import Response
    
    def create_file_iterator():
        with file_path.open("rb") as f:
            while chunk := f.read(8192):
                yield chunk
    
    headers = {
        "Content-Disposition": _encode_filename_for_header(file_path.name)
    }
    
    return StreamingResponse(
        create_file_iterator(),
        media_type="application/octet-stream",
        headers=headers
    )


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
        return {"status": "success", "message": f"'{target_path.name}' is being opened."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not open '{target_path.name}': {e}")