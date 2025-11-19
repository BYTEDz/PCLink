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
import zipfile
import tempfile
import hashlib
import mimetypes
from io import BytesIO
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Literal, Generator

from fastapi import (APIRouter, BackgroundTasks, HTTPException, Query, Request,
                     Header, Response)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..core.validators import validate_filename

# --- Performance Enhancement: Use aiofiles if available ---
try:
    import aiofiles
    AIOFILES_INSTALLED = True
except ImportError:
    AIOFILES_INSTALLED = False

# --- Thumbnail Generation Dependencies (Optional) ---
try:
    from PIL import Image
    PIL_INSTALLED = True
except ImportError:
    PIL_INSTALLED = False


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
    conflict_resolution: Literal["abort", "overwrite", "keep_both"] = "abort"


class UploadInitiateResponse(BaseModel):
    upload_id: str
    final_file_name: str | None = None  # The actual filename that will be used (may be different if keep_both)


class FileConflictResponse(BaseModel):
    conflict: bool = True
    existing_file: str
    options: List[str] = ["abort", "overwrite", "keep_both"]
    suggested_name: str | None = None  # For keep_both option


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


class PastePayload(BaseModel):
    source_paths: List[str] = Field(..., min_items=1)
    destination_path: str
    action: Literal["cut", "copy"]
    conflict_resolution: Literal["skip", "overwrite", "rename"] = "skip"


class PathsPayload(BaseModel):
    paths: List[str] = Field(..., min_items=1)


class CompressPayload(BaseModel):
    file_paths: List[str] = Field(..., min_items=1)
    output_path: str


class ExtractPayload(BaseModel):
    zip_path: str
    destination: str
    password: str | None = None


class IsEncryptedResponse(BaseModel):
    is_encrypted: bool


# --- API Routers ---
router = APIRouter()
upload_router = APIRouter()
download_router = APIRouter()


# --- Constants and State ---
ROOT_IDENTIFIER = "_ROOT_"
HOME_DIR = Path.home().resolve()
TEMP_UPLOAD_DIR = HOME_DIR / ".pclink_uploads"
TEMP_UPLOAD_DIR.mkdir(exist_ok=True, parents=True)
DOWNLOAD_SESSION_DIR = HOME_DIR / ".pclink_downloads"
DOWNLOAD_SESSION_DIR.mkdir(exist_ok=True, parents=True)
THUMBNAIL_CACHE_DIR = Path(tempfile.gettempdir()) / "pclink_thumbnails"
THUMBNAIL_CACHE_DIR.mkdir(exist_ok=True, parents=True)

# --- Performance Enhancement: Configurable chunk sizes ---
DOWNLOAD_CHUNK_SIZE = 65536  # 64KB for better throughput
UPLOAD_CHUNK_SIZE = 262144  # 256KB for faster uploads (4x download size)
UPLOAD_BUFFER_SIZE = 1048576  # 1MB buffer for write operations

ACTIVE_UPLOADS: Dict[str, str] = {}
ACTIVE_DOWNLOADS: Dict[str, Dict] = {}
TRANSFER_LOCKS: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
UPLOAD_BUFFERS: Dict[str, bytearray] = {}  # In-memory buffers for faster writes


# --- Utility Functions ---
def _encode_filename_for_header(filename: str) -> str:
    try:
        filename.encode('ascii')
        return f'attachment; filename="{filename}"'
    except UnicodeEncodeError:
        encoded_filename = urllib.parse.quote(filename, safe='')
        return f"attachment; filename*=UTF-8''{encoded_filename}"


def _get_system_roots() -> List[Path]:
    """
    Get a list of available system roots (drives on Windows, / on Unix).
    Safely iterates drives to avoid crashing on locked BitLocker volumes or mapped drives.
    """
    if platform.system() == "Windows":
        roots = []
        for d in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            try:
                p = Path(f"{d}:\\")
                # Checking exists() on a locked BitLocker drive might raise an OSError/PermissionError
                if p.exists():
                    roots.append(p)
            except Exception as e:
                # Log debug but continue; this is expected for locked/disconnected drives
                log.debug(f"Skipping drive {d}: due to error: {e}")
                continue
        return roots
    return [Path("/")]


def _is_path_within_safe_roots(path_to_check: Path) -> bool:
    safe_roots = _get_system_roots() + [HOME_DIR]
    try:
        resolved_path = path_to_check.resolve()
    except (FileNotFoundError, RuntimeError):
        resolved_path = path_to_check.absolute()

    for root in safe_roots:
        # Use str comparison for robustness against different path object types or slight variations
        if str(resolved_path).startswith(str(root)):
            return True
    return False


def _validate_and_resolve_path(
    user_path_str: str, check_existence: bool = True
) -> Path:
    if not user_path_str:
        raise HTTPException(status_code=400, detail="Path cannot be empty.")
    try:
        expanded_path_str = os.path.expanduser(os.path.expandvars(user_path_str))
        path = Path(expanded_path_str)
        if ".." in path.parts:
            raise HTTPException(status_code=403, detail="Relative pathing ('..') is not allowed.")
        if not path.is_absolute():
            path = HOME_DIR / path
        resolved_path = path.resolve(strict=False)
        if check_existence and not resolved_path.exists():
            raise HTTPException(status_code=404, detail="File or directory not found.")
        if not _is_path_within_safe_roots(resolved_path):
            raise HTTPException(status_code=403, detail="Access to the specified path is denied.")
        return resolved_path
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid path format: {e}")
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Unexpected error validating path '{user_path_str}': {e}")
        raise HTTPException(status_code=500, detail="An error occurred while processing the path.")


async def _cleanup_transfer_session(transfer_id: str):
    if transfer_id in TRANSFER_LOCKS:
        del TRANSFER_LOCKS[transfer_id]


def _save_download_session(download_id: str, session_data: Dict):
    try:
        session_file = DOWNLOAD_SESSION_DIR / f"{download_id}.json"
        session_file.write_text(json.dumps(session_data), encoding="utf-8")
    except Exception as e:
        log.error(f"Failed to save download session {download_id}: {e}")


def _load_download_session(download_id: str) -> Dict | None:
    try:
        session_file = DOWNLOAD_SESSION_DIR / f"{download_id}.json"
        if session_file.exists():
            return json.loads(session_file.read_text(encoding="utf-8"))
    except Exception as e:
        log.error(f"Failed to load download session {download_id}: {e}")
    return None


def _delete_download_session(download_id: str):
    try:
        session_file = DOWNLOAD_SESSION_DIR / f"{download_id}.json"
        session_file.unlink(missing_ok=True)
    except Exception as e:
        log.warning(f"Failed to delete download session {download_id}: {e}")


def restore_sessions():
    restored_uploads = 0
    restored_downloads = 0
    for meta_file in TEMP_UPLOAD_DIR.glob("*.meta"):
        try:
            upload_id = meta_file.stem
            part_file = TEMP_UPLOAD_DIR / f"{upload_id}.part"
            if part_file.exists():
                metadata = json.loads(meta_file.read_text(encoding="utf-8"))
                final_path = metadata.get("final_path")
                if final_path:
                    ACTIVE_UPLOADS[final_path] = upload_id
                    restored_uploads += 1
                    log.info(f"Restored upload session: {upload_id} for {metadata.get('file_name', 'unknown')}")
        except Exception as e:
            log.warning(f"Failed to restore upload session from {meta_file}: {e}")
    for session_file in DOWNLOAD_SESSION_DIR.glob("*.json"):
        try:
            download_id = session_file.stem
            session_data = json.loads(session_file.read_text(encoding="utf-8"))
            file_path = Path(session_data["file_path"])
            if file_path.exists() and file_path.is_file():
                current_stat = file_path.stat()
                if current_stat.st_mtime == session_data.get("file_modified_at"):
                    ACTIVE_DOWNLOADS[download_id] = session_data
                    restored_downloads += 1
                    log.info(f"Restored download session: {download_id} for {session_data.get('file_name', 'unknown')}")
                else:
                    session_file.unlink(missing_ok=True)
                    log.info(f"Removed stale download session {download_id} (file modified)")
            else:
                session_file.unlink(missing_ok=True)
                log.info(f"Removed stale download session {download_id} (file not found)")
        except Exception as e:
            log.warning(f"Failed to restore download session from {session_file}: {e}")
    if restored_uploads or restored_downloads:
        log.info(f"Session restoration complete: {restored_uploads} uploads, {restored_downloads} downloads")
    return {"restored_uploads": restored_uploads, "restored_downloads": restored_downloads}


async def cleanup_stale_sessions():
    current_time = time.time()
    stale_threshold = 7 * 24 * 60 * 60
    stale_uploads, stale_downloads = [], []
    for upload_file in TEMP_UPLOAD_DIR.glob("*.meta"):
        try:
            if current_time - upload_file.stat().st_mtime > stale_threshold:
                upload_id = upload_file.stem
                (TEMP_UPLOAD_DIR / f"{upload_id}.part").unlink(missing_ok=True)
                upload_file.unlink(missing_ok=True)
                for path, uid in list(ACTIVE_UPLOADS.items()):
                    if uid == upload_id: del ACTIVE_UPLOADS[path]
                stale_uploads.append(upload_id)
        except Exception as e:
            log.warning(f"Error cleaning up stale upload {upload_file}: {e}")
    for session_file in DOWNLOAD_SESSION_DIR.glob("*.json"):
        try:
            if current_time - session_file.stat().st_mtime > stale_threshold:
                download_id = session_file.stem
                session_file.unlink(missing_ok=True)
                if download_id in ACTIVE_DOWNLOADS: del ACTIVE_DOWNLOADS[download_id]
                stale_downloads.append(download_id)
        except Exception as e:
            log.warning(f"Error cleaning up stale download {session_file}: {e}")
    if stale_uploads or stale_downloads:
        log.info(f"Cleaned up {len(stale_uploads)} stale uploads and {len(stale_downloads)} stale downloads")
    return {"cleaned_uploads": len(stale_uploads), "cleaned_downloads": len(stale_downloads)}


def _get_unique_filename(path: Path) -> Path:
    if not path.exists():
        return path
    parent, stem, suffix, counter = path.parent, path.stem, path.suffix, 1
    while True:
        new_path = parent / f"{stem} ({counter}){suffix}"
        if not new_path.exists(): return new_path
        counter += 1


def _get_item_type(entry_name: str, is_dir: bool) -> str:
    if is_dir:
        return "folder"
    mime_type, _ = mimetypes.guess_type(entry_name)
    if mime_type:
        if mime_type.startswith("video/"):
            return "video"
        if mime_type.startswith("image/"):
            return "image"
        if mime_type.startswith("audio/"):
            return "audio"
        if mime_type == "application/zip":
            return "archive"
    return "file"  # Fallback


# --- Thumbnail, Compression, and Extraction Logic ---

async def generate_thumbnail(file_path: str, size: tuple = (256, 256)) -> bytes | None:
    """
    Generates a thumbnail for image files.
    Caches thumbnails in a temporary directory based on file hash.
    """
    if not PIL_INSTALLED:
        log.warning("Thumbnail generation skipped: Pillow is not installed.")
        return None

    try:
        path = _validate_and_resolve_path(file_path)
        if not path.is_file():
            return None
    except HTTPException:
        return None

    def _create_thumbnail_sync():
        try:
            # --- Cache logic ---
            stat = path.stat()
            cache_key_source = f"{path.resolve()}:{stat.st_mtime}:{stat.st_size}"
            cache_key = hashlib.sha1(cache_key_source.encode()).hexdigest()
            cache_file = THUMBNAIL_CACHE_DIR / f"{cache_key}.png"

            if cache_file.exists():
                return cache_file.read_bytes()

            # --- Generation logic ---
            mime_type, _ = mimetypes.guess_type(path)
            
            # Image Thumbnail (Pillow only)
            if mime_type and mime_type.startswith("image/"):
                with Image.open(path) as img:
                    img.thumbnail(size)
                    buffer = BytesIO()
                    # Convert to RGB to avoid issues with paletted images (e.g. some GIFs)
                    img.convert("RGB").save(buffer, format="PNG")
                    thumbnail_bytes = buffer.getvalue()
                    
                    # Cache the thumbnail
                    cache_file.write_bytes(thumbnail_bytes)
                    return thumbnail_bytes

            return None
        except Exception as e:
            log.error(f"Failed to generate thumbnail for '{path}': {e}")
            return None
            
    return await asyncio.to_thread(_create_thumbnail_sync)


def compress_files(file_paths: list, output_zip: str) -> Generator[int, None, None]:
    """
    Compresses files and directories into a zip archive, yielding progress.
    """
    resolved_paths = [_validate_and_resolve_path(p) for p in file_paths]
    output_path = _validate_and_resolve_path(output_zip, check_existence=False)

    total_size = 0
    files_to_zip = []

    for path in resolved_paths:
        if path.is_file():
            total_size += path.stat().st_size
            files_to_zip.append((path, path.name))
        elif path.is_dir():
            for root, _, files in os.walk(path):
                for file in files:
                    file_path = Path(root) / file
                    try:
                        total_size += file_path.stat().st_size
                        arcname = file_path.relative_to(path.parent)
                        files_to_zip.append((file_path, arcname))
                    except (OSError, PermissionError):
                        continue
    
    if total_size == 0:
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED): pass
        yield 100
        return

    bytes_written = 0
    yield 0
    
    try:
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for file_path, arcname in files_to_zip:
                try:
                    zf.write(file_path, arcname)
                    bytes_written += file_path.stat().st_size
                    yield int((bytes_written / total_size) * 100)
                except (OSError, PermissionError) as e:
                    log.warning(f"Skipping file during compression: {file_path} ({e})")
                    try: bytes_written += file_path.stat().st_size
                    except OSError: pass
    except Exception as e:
        log.error(f"Compression failed for {output_zip}: {e}")
        if output_path.exists(): output_path.unlink()
        raise

    if bytes_written < total_size: yield 100


def _is_zip_encrypted(zip_path: Path) -> bool:
    """Checks if a zip file is password protected by reading its metadata."""
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            for zinfo in zf.infolist():
                # The first bit of flag_bits (0x1) indicates encryption
                if zinfo.flag_bits & 0x1:
                    return True
    except (zipfile.BadZipFile, FileNotFoundError):
        return False # Not a valid zip, so not encrypted for our purposes
    except Exception as e:
        log.warning(f"Could not check zip encryption for {zip_path}: {e}")
        return False
    return False

def extract_archive(
    zip_path: str, destination: str, password: str | None = None
) -> Generator[int, None, None]:
    """
    Extracts a zip archive to a destination, yielding progress.
    Handles password-protected archives.
    """
    zip_file_path = _validate_and_resolve_path(zip_path)
    dest_path = _validate_and_resolve_path(destination, check_existence=False)

    if not dest_path.parent.is_dir():
        raise ValueError("Destination parent directory does not exist.")

    try:
        os.makedirs(dest_path, exist_ok=True)
    except OSError as e:
        log.error(f"Could not create destination directory {dest_path}: {e}")
        raise ValueError(f"Could not create destination directory: {e}") from e

    pwd_bytes = password.encode("utf-8") if password else None

    try:
        with zipfile.ZipFile(zip_file_path, 'r') as zf:
            infolist = zf.infolist()
            total_size = sum(file.file_size for file in infolist)

            if total_size == 0:
                zf.extractall(dest_path, pwd=pwd_bytes)
                yield 100
                return

            extracted_size = 0
            yield 0

            for member in infolist:
                if ".." in member.filename or os.path.isabs(member.filename):
                    log.warning(f"Skipping potentially malicious path in zip: {member.filename}")
                    continue
                zf.extract(member, dest_path, pwd=pwd_bytes)
                extracted_size += member.file_size
                yield int((extracted_size / total_size) * 100)

            yield 100
    except RuntimeError as e:
        if "password" in str(e).lower():
            log.warning(f"Incorrect password provided for zip file {zip_path}")
            raise ValueError("Incorrect password provided for the archive.") from e
        log.error(f"Extraction failed for {zip_path}: {e}")
        raise
    except Exception as e:
        log.error(f"Extraction failed for {zip_path}: {e}")
        raise


# --- Chunked File Upload Endpoints ---
@upload_router.get("/config")
async def get_upload_config():
    """Return optimal upload configuration for clients."""
    return {
        "recommended_chunk_size": UPLOAD_CHUNK_SIZE,
        "max_chunk_size": UPLOAD_CHUNK_SIZE * 2,  # Allow up to 512KB chunks
        "min_chunk_size": 65536,  # Minimum 64KB
        "buffer_size": UPLOAD_BUFFER_SIZE,
        "supports_concurrent_chunks": False,  # Sequential for data integrity
        "supports_resume": True,
        "supports_pause": True
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
    
    # Initialize buffer if not exists
    if upload_id not in UPLOAD_BUFFERS:
        UPLOAD_BUFFERS[upload_id] = bytearray()
    
    bytes_written = 0
    
    async with lock:
        if not part_file.exists() or not meta_file.exists():
            raise HTTPException(status_code=404, detail="Upload session not found or expired.")
        
        try:
            # Collect all chunks into buffer first for better performance
            buffer = UPLOAD_BUFFERS[upload_id]
            buffer.clear()
            
            async for chunk in request.stream():
                buffer.extend(chunk)
                bytes_written += len(chunk)
            
            # Write buffered data in one operation for better I/O performance
            if AIOFILES_INSTALLED:
                async with aiofiles.open(part_file, "rb+") as f:
                    await f.seek(offset)
                    await f.write(buffer)
            else:
                # Fallback: use thread pool for blocking I/O
                def write_sync():
                    with part_file.open("rb+") as f:
                        f.seek(offset)
                        f.write(buffer)
                await asyncio.to_thread(write_sync)
            
            # Clear buffer after successful write
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
            # --- Performance Enhancement: Run blocking I/O in a thread ---
            await asyncio.to_thread(final_path.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(shutil.move, str(part_file), final_path_str)
        except Exception as e:
            if part_file.exists(): part_file.unlink()
            raise HTTPException(status_code=500, detail=f"Error moving completed file: {e}")
        finally:
            if meta_file.exists(): meta_file.unlink()
            if final_path_str in ACTIVE_UPLOADS:
                del ACTIVE_UPLOADS[final_path_str]
            # Clean up buffer
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
        # Clean up buffer
        if upload_id in UPLOAD_BUFFERS:
            del UPLOAD_BUFFERS[upload_id]
    background_tasks.add_task(_cleanup_transfer_session, upload_id)
    log.info(f"Cancelled upload {upload_id}")
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


@download_router.get("/list-active")
async def list_active_downloads():
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


@upload_router.post("/stream/{upload_id}")
async def stream_upload(upload_id: str, request: Request):
    part_file = TEMP_UPLOAD_DIR / f"{upload_id}.part"
    meta_file = TEMP_UPLOAD_DIR / f"{upload_id}.meta"
    if not part_file.exists() or not meta_file.exists():
        raise HTTPException(status_code=404, detail="Upload session not found or expired.")
    
    # Initialize buffer for this upload
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
                    
                    # Flush buffer when it reaches threshold for better memory management
                    if len(buffer) >= UPLOAD_BUFFER_SIZE:
                        await f.write(buffer)
                        buffer.clear()
                
                # Write remaining data
                if buffer:
                    await f.write(buffer)
                    buffer.clear()
        else:
            # Fallback: use thread pool for blocking I/O with buffering
            def write_stream_sync():
                nonlocal bytes_written
                with part_file.open("wb") as f:
                    if buffer:
                        f.write(buffer)
                        bytes_written = len(buffer)
            
            async for chunk in request.stream():
                buffer.extend(chunk)
                
                # Flush buffer when it reaches threshold
                if len(buffer) >= UPLOAD_BUFFER_SIZE:
                    await asyncio.to_thread(write_stream_sync)
                    buffer.clear()
            
            # Write remaining data
            if buffer:
                await asyncio.to_thread(write_stream_sync)
                buffer.clear()
        
        log.info(f"Streamed {bytes_written} bytes for upload {upload_id}")
        return {"status": "stream received", "bytes_written": bytes_written}
    except Exception as e:
        log.error(f"Error in stream upload {upload_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error streaming file: {e}")
    finally:
        # Clean up buffer
        if upload_id in UPLOAD_BUFFERS:
            UPLOAD_BUFFERS[upload_id].clear()


@upload_router.post("/direct")
async def direct_upload(request: Request, destination_path: str = Query(...), file_name: str = Query(...),
                      conflict_resolution: str = Query("keep_both", regex="^(abort|overwrite|keep_both)$")):
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
                    
                    # Flush buffer when it reaches threshold
                    if len(buffer) >= UPLOAD_BUFFER_SIZE:
                        await f.write(buffer)
                        buffer.clear()
                
                # Write remaining data
                if buffer:
                    await f.write(buffer)
        else:
            # Fallback: use thread pool with buffering
            def write_buffered_sync():
                with final_file_path.open("ab") as f:
                    f.write(buffer)
            
            async for chunk in request.stream():
                buffer.extend(chunk)
                bytes_written += len(chunk)
                
                # Flush buffer when it reaches threshold
                if len(buffer) >= UPLOAD_BUFFER_SIZE:
                    await asyncio.to_thread(write_buffered_sync)
                    buffer.clear()
            
            # Write remaining data
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


# --- Chunked File Download Endpoints ---
@download_router.post("/test-path")
async def test_path_handling(payload: DownloadInitiatePayload):
    try:
        log.info(f"DEBUG TEST: Received path: {payload.file_path!r}")
        path = Path(payload.file_path)
        log.info(f"DEBUG TEST: Path object created: {path}")
        resolved = await asyncio.to_thread(path.resolve, strict=False)
        log.info(f"DEBUG TEST: Path resolved: {resolved}")
        exists = await asyncio.to_thread(resolved.exists)
        log.info(f"DEBUG TEST: Path exists: {exists}")
        is_file = await asyncio.to_thread(resolved.is_file) if exists else False
        log.info(f"DEBUG TEST: Is file: {is_file}")
        if is_file:
            stat_info = await asyncio.to_thread(resolved.stat)
            log.info(f"DEBUG TEST: File size: {stat_info.st_size}")
        return {"status": "success", "path": str(resolved), "exists": exists, "is_file": is_file}
    except Exception as e:
        log.error(f"DEBUG TEST: Error in path test: {e}")
        return {"status": "error", "error": str(e), "error_type": type(e).__name__}


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
            else: # Fallback for non-aiofiles environment
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

    headers = {
        "Content-Range": f"bytes {start_byte}-{end_byte}/{file_size}",
        "Accept-Ranges": "bytes", "Content-Length": str(chunk_size),
        "Content-Disposition": _encode_filename_for_header(info["file_name"])
    }
    return StreamingResponse(stream_file_range(), status_code=206, headers=headers, media_type="application/octet-stream")


@download_router.post("/complete/{download_id}")
async def complete_download(download_id: str, background_tasks: BackgroundTasks):
    if download_id not in ACTIVE_DOWNLOADS:
        raise HTTPException(status_code=404, detail="Download session not found")
    _delete_download_session(download_id)
    del ACTIVE_DOWNLOADS[download_id]
    background_tasks.add_task(_cleanup_transfer_session, download_id)
    log.info(f"Completed download {download_id}")
    return {"status": "completed"}


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
    file_path = Path(info["file_path"])
    if not file_path.exists():
        _delete_download_session(download_id)
        del ACTIVE_DOWNLOADS[download_id]
        raise HTTPException(status_code=404, detail="File no longer exists")
    current_stat = file_path.stat()
    if current_stat.st_mtime != info.get("file_modified_at"):
        _delete_download_session(download_id)
        del ACTIVE_DOWNLOADS[download_id]
        raise HTTPException(status_code=409, detail="File has been modified since download started")
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


# --- File Browsing and Management Endpoints ---
def _scan_directory(path: Path):
    """Blocking function to scan a directory."""
    content = []
    try:
        # Check if directory is accessible first
        if not os.access(path, os.R_OK):
             raise PermissionError(f"Access denied to {path}")
             
        for entry in os.scandir(path):
            try:
                stat = entry.stat()
                is_dir = entry.is_dir()
                item_type = _get_item_type(entry.name, is_dir)
                full_path = path / entry.name
                content.append(FileItem(
                    name=entry.name, 
                    path=str(full_path), 
                    is_dir=is_dir, 
                    size=stat.st_size,
                    modified_at=stat.st_mtime, 
                    item_type=item_type
                ))
            except (OSError, PermissionError) as e:
                log.warning(f"Could not access item {entry.path}: {e}")
    except Exception as e:
        # Propagate exception to be handled by the async wrapper
        raise HTTPException(status_code=500, detail=f"Error reading directory: {e}") from e
    content.sort(key=lambda x: (not x.is_dir, x.name.lower()))
    return content

@router.get("/browse", response_model=DirectoryListing)
async def browse_directory(path: str | None = Query(None)):
    if not path or path == ROOT_IDENTIFIER:
        items = [FileItem(name=str(r), path=str(r), is_dir=True, size=0, modified_at=0, item_type="drive") for r in _get_system_roots()]
        if HOME_DIR.exists():
            home_stat = HOME_DIR.stat()
            items.append(FileItem(name="Home", path=str(HOME_DIR), is_dir=True, size=home_stat.st_size,
                                  modified_at=home_stat.st_mtime, item_type="home"))
        return DirectoryListing(current_path=ROOT_IDENTIFIER, parent_path=None, items=items)

    current_path = _validate_and_resolve_path(path)
    if not current_path.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory.")

    # --- Performance Enhancement: Run blocking scandir in a thread ---
    content = await asyncio.to_thread(_scan_directory, current_path)

    is_root_drive = any(str(current_path).startswith(str(r)) for r in _get_system_roots() if str(current_path) == str(r))
    parent_path_str = str(current_path.parent) if not is_root_drive else ROOT_IDENTIFIER
    if HOME_DIR.exists() and current_path.samefile(HOME_DIR):
        parent_path_str = ROOT_IDENTIFIER
    return DirectoryListing(current_path=str(current_path), parent_path=parent_path_str, items=content)


@router.get("/thumbnail")
async def get_thumbnail(path: str = Query(...)):
    thumbnail_bytes = await generate_thumbnail(path)
    if thumbnail_bytes:
        # Add cache headers to prevent infinite re-requests
        headers = {
            "Cache-Control": "public, max-age=3600",  # Cache for 1 hour
            "ETag": hashlib.md5(thumbnail_bytes).hexdigest()  # Add ETag for validation
        }
        return Response(content=thumbnail_bytes, media_type="image/png", headers=headers)
    else:
        raise HTTPException(status_code=404, detail="Thumbnail not available for this file.")


@router.post("/compress")
async def stream_compress_files(payload: CompressPayload):
    async def progress_generator():
        last_progress = -1
        try:
            # Run blocking compression in thread pool
            loop = asyncio.get_event_loop()
            queue = asyncio.Queue()
            
            def run_compression():
                try:
                    for progress in compress_files(payload.file_paths, payload.output_path):
                        loop.call_soon_threadsafe(queue.put_nowait, {'progress': progress})
                    loop.call_soon_threadsafe(queue.put_nowait, {'status': 'complete', 'progress': 100})
                except Exception as e:
                    loop.call_soon_threadsafe(queue.put_nowait, {'status': 'error', 'message': str(e)})
                finally:
                    loop.call_soon_threadsafe(queue.put_nowait, None)  # Signal completion
            
            # Start compression in background thread
            asyncio.create_task(asyncio.to_thread(run_compression))
            
            # Stream progress updates
            while True:
                data = await queue.get()
                if data is None:  # Completion signal
                    break
                if 'progress' in data and data['progress'] > last_progress:
                    yield f"data: {json.dumps(data)}\n\n"
                    last_progress = data['progress']
                elif 'status' in data:
                    yield f"data: {json.dumps(data)}\n\n"
                    break
                    
        except Exception as e:
            log.error(f"Compression stream failed: {e}")
            yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(progress_generator(), media_type="text/event-stream")


@router.get("/is-encrypted", response_model=IsEncryptedResponse)
async def is_archive_encrypted(path: str = Query(...)):
    zip_file_path = _validate_and_resolve_path(path)
    if not zip_file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    
    is_encrypted = await asyncio.to_thread(_is_zip_encrypted, zip_file_path)
    
    return IsEncryptedResponse(is_encrypted=is_encrypted)


@router.post("/extract")
async def stream_extract_archive(payload: ExtractPayload):
    async def progress_generator():
        last_progress = -1
        try:
            # Run blocking extraction in thread pool
            loop = asyncio.get_event_loop()
            queue = asyncio.Queue()
            
            def run_extraction():
                try:
                    for progress in extract_archive(
                        payload.zip_path, payload.destination, payload.password
                    ):
                        loop.call_soon_threadsafe(queue.put_nowait, {'progress': progress})
                    loop.call_soon_threadsafe(queue.put_nowait, {'status': 'complete', 'progress': 100})
                except ValueError as e:
                    loop.call_soon_threadsafe(queue.put_nowait, {'status': 'error', 'message': str(e)})
                except Exception as e:
                    loop.call_soon_threadsafe(queue.put_nowait, {'status': 'error', 'message': str(e)})
                finally:
                    loop.call_soon_threadsafe(queue.put_nowait, None)  # Signal completion
            
            # Start extraction in background thread
            asyncio.create_task(asyncio.to_thread(run_extraction))
            
            # Stream progress updates
            while True:
                data = await queue.get()
                if data is None:  # Completion signal
                    break
                if 'progress' in data and data['progress'] > last_progress:
                    yield f"data: {json.dumps(data)}\n\n"
                    last_progress = data['progress']
                elif 'status' in data:
                    yield f"data: {json.dumps(data)}\n\n"
                    break
                    
        except Exception as e:
            log.error(f"Extraction stream failed: {e}")
            yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"
            
    return StreamingResponse(progress_generator(), media_type="text/event-stream")


@router.post("/create-folder")
async def create_folder(payload: CreateFolderPayload):
    parent_dir = _validate_and_resolve_path(payload.parent_path)
    safe_folder_name = validate_filename(payload.folder_name)
    new_folder_path = _validate_and_resolve_path(str(parent_dir / safe_folder_name), check_existence=False)
    if new_folder_path.exists():
        raise HTTPException(status_code=409, detail="A file or folder with this name already exists.")
    try:
        # --- Performance Enhancement: Run blocking mkdir in a thread ---
        await asyncio.to_thread(new_folder_path.mkdir)
        return {"status": "success", "message": f"Folder '{safe_folder_name}' created."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create folder: {e}")


@router.patch("/rename")
async def rename_item(payload: RenamePayload):
    source_path = _validate_and_resolve_path(payload.path)
    safe_new_name = validate_filename(payload.new_name)
    dest_path = _validate_and_resolve_path(str(source_path.parent / safe_new_name), check_existence=False)
    if dest_path.exists():
        raise HTTPException(status_code=409, detail="An item with the new name already exists.")
    try:
        # --- Performance Enhancement: Run blocking rename in a thread ---
        await asyncio.to_thread(source_path.rename, dest_path)
        return {"status": "success", "message": "Item renamed successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to rename item: {e}")

async def _delete_item_task(path_str: str) -> dict:
    """Async wrapper for a single delete operation."""
    try:
        target_path = _validate_and_resolve_path(path_str)
        if not await asyncio.to_thread(target_path.exists):
            return {"path": path_str, "status": "Already deleted", "success": True}
        
        if await asyncio.to_thread(target_path.is_dir):
            await asyncio.to_thread(shutil.rmtree, target_path)
        else:
            await asyncio.to_thread(target_path.unlink)
        return {"path": path_str, "status": "Deleted successfully", "success": True}
    except HTTPException as e:
        return {"path": path_str, "reason": e.detail, "success": False}
    except Exception as e:
        log.error(f"Failed to delete item '{path_str}': {e}")
        return {"path": path_str, "reason": str(e), "success": False}

@router.post("/delete")
async def delete_items(payload: PathsPayload):
    # --- Performance Enhancement: Run deletions concurrently ---
    tasks = [_delete_item_task(path_str) for path_str in payload.paths]
    results = await asyncio.gather(*tasks)
    
    succeeded = [res for res in results if res["success"]]
    failed = [{"path": res["path"], "reason": res["reason"]} for res in results if not res["success"]]

    if not succeeded and failed:
        raise HTTPException(status_code=500, detail={"message": "All delete operations failed.", "details": failed})
    
    return {"succeeded": succeeded, "failed": failed}


@router.get("/download")
async def download_file(path: str = Query(...)):
    file_path = _validate_and_resolve_path(path)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="The specified path is not a file.")
    
    file_size = file_path.stat().st_size
    if file_size > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail={
            "message": "File is large. Use the chunked download API for reliability.",
            "file_size": file_size, "chunked_download_required": True
        })
    
    async def create_file_iterator():
        if AIOFILES_INSTALLED:
            async with aiofiles.open(file_path, "rb") as f:
                while chunk := await f.read(DOWNLOAD_CHUNK_SIZE):
                    yield chunk
        else:
            with file_path.open("rb") as f:
                while chunk := f.read(DOWNLOAD_CHUNK_SIZE):
                    yield chunk
    
    headers = {"Content-Disposition": _encode_filename_for_header(file_path.name)}
    return StreamingResponse(create_file_iterator(), media_type="application/octet-stream", headers=headers)


@router.post("/open")
async def open_file_on_server(payload: PathPayload):
    target_path = _validate_and_resolve_path(payload.path)
    if not target_path.exists():
        raise HTTPException(status_code=404, detail="File or directory not found.")
    try:
        # This operation is inherently OS-dependent and quick, so threading is optional
        if platform.system() == "Windows":
            os.startfile(target_path)
        elif platform.system() == "Darwin":
            subprocess.run(["open", str(target_path)], check=True)
        else:
            subprocess.run(["xdg-open", str(target_path)], check=True)
        return {"status": "success", "message": f"'{target_path.name}' is being opened."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not open '{target_path.name}': {e}")


@router.post("/paste")
async def paste_items(payload: PastePayload):
    dest_dir = _validate_and_resolve_path(payload.destination_path)
    if not dest_dir.is_dir():
        raise HTTPException(status_code=400, detail="Destination path must be a directory.")

    succeeded, failed, conflicts = [], [], []
    first_src_path = _validate_and_resolve_path(payload.source_paths[0])
    is_same_dir = first_src_path.parent.samefile(dest_dir)

    for src_path_str in payload.source_paths:
        try:
            src_path = _validate_and_resolve_path(src_path_str)
            final_dest_path = dest_dir / src_path.name

            if src_path.is_dir() and dest_dir.resolve().is_relative_to(src_path.resolve()):
                failed.append({"path": src_path_str, "reason": "Cannot paste a parent directory into its own child."})
                continue
            
            if final_dest_path.exists():
                if payload.conflict_resolution == "skip":
                    conflicts.append(final_dest_path.name)
                    continue
                elif payload.conflict_resolution == "overwrite":
                    if is_same_dir:
                        failed.append({"path": src_path_str, "reason": "Cannot overwrite an item with itself."})
                        continue
                    # --- Performance Enhancement: Run blocking I/O in a thread ---
                    if await asyncio.to_thread(final_dest_path.is_dir):
                        await asyncio.to_thread(shutil.rmtree, final_dest_path)
                    else:
                        await asyncio.to_thread(os.remove, final_dest_path)
                elif payload.conflict_resolution == "rename":
                    final_dest_path = await asyncio.to_thread(_get_unique_filename, final_dest_path)

            # --- Performance Enhancement: Run blocking I/O in a thread ---
            if payload.action == "cut":
                await asyncio.to_thread(shutil.move, str(src_path), str(final_dest_path))
                succeeded.append({"path": src_path_str, "action": "moved"})
            elif payload.action == "copy":
                if src_path.is_dir():
                    await asyncio.to_thread(shutil.copytree, str(src_path), str(final_dest_path))
                else:   
                    await asyncio.to_thread(shutil.copy2, str(src_path), str(final_dest_path))
                succeeded.append({"path": src_path_str, "action": "copied"})
        except Exception as e:
            log.error(f"Error processing paste for '{src_path_str}': {e}")
            failed.append({"path": src_path_str, "reason": str(e)})

    if conflicts:
        raise HTTPException(status_code=409, detail={
            "message": "Some items were skipped due to existing files.",
            "conflicting_items": list(set(conflicts)),
            "succeeded": succeeded, "failed": failed,
        })
    if not succeeded and failed:
        raise HTTPException(status_code=500, detail={"message": "All paste operations failed.", "details": failed})

    return {"succeeded": succeeded, "failed": failed}