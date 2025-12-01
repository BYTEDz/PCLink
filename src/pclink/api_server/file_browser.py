# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import json
import logging
import os
import platform
import shutil
import subprocess
import hashlib
import mimetypes
import tempfile
import urllib.parse
import zipfile
from io import BytesIO
from pathlib import Path
from typing import List, Literal, Generator

from fastapi import APIRouter, HTTPException, Query, Response
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


# --- API Router ---
router = APIRouter()


# --- Constants ---
ROOT_IDENTIFIER = "_ROOT_"
HOME_DIR = Path.home().resolve()
THUMBNAIL_CACHE_DIR = Path(tempfile.gettempdir()) / "pclink_thumbnails"
THUMBNAIL_CACHE_DIR.mkdir(exist_ok=True, parents=True)
DOWNLOAD_CHUNK_SIZE = 65536  # Kept for simple download endpoint


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
    Uses Windows API for fast and safe drive detection.
    """
    if platform.system() == "Windows":
        roots = []
        try:
            import string
            from ctypes import windll
            
            drives_bitmask = windll.kernel32.GetLogicalDrives()
            for i, letter in enumerate(string.ascii_uppercase):
                if drives_bitmask & (1 << i):
                    roots.append(Path(f"{letter}:\\"))
            return roots
        except Exception as e:
            log.warning(f"Windows API drive detection failed, using fallback: {e}")
            for d in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                try:
                    p = Path(f"{d}:\\")
                    if p.exists():
                        roots.append(p)
                except Exception:
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
    return "file"


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
            stat = path.stat()
            cache_key_source = f"{path.resolve()}:{stat.st_mtime}:{stat.st_size}"
            cache_key = hashlib.sha1(cache_key_source.encode()).hexdigest()
            cache_file = THUMBNAIL_CACHE_DIR / f"{cache_key}.png"

            if cache_file.exists():
                return cache_file.read_bytes()

            mime_type, _ = mimetypes.guess_type(path)
            
            if mime_type and mime_type.startswith("image/"):
                with Image.open(path) as img:
                    img.thumbnail(size)
                    buffer = BytesIO()
                    img.convert("RGB").save(buffer, format="PNG")
                    thumbnail_bytes = buffer.getvalue()
                    
                    cache_file.write_bytes(thumbnail_bytes)
                    return thumbnail_bytes

            return None
        except Exception as e:
            log.error(f"Failed to generate thumbnail for '{path}': {e}")
            return None
            
    return await asyncio.to_thread(_create_thumbnail_sync)


def compress_files(file_paths: list, output_zip: str) -> Generator[int, None, None]:
    resolved_paths = [_validate_and_resolve_path(p) for p in file_paths]
    output_path = _validate_and_resolve_path(output_zip, check_existence=False)

    total_size = 0
    files_to_zip = []

    for path in resolved_paths:
        if path.is_file():
            try:
                size = path.stat().st_size
                total_size += size
                files_to_zip.append((path, path.name, size))
            except (OSError, PermissionError):
                continue
        elif path.is_dir():
            for root, _, files in os.walk(path):
                for file in files:
                    file_path = Path(root) / file
                    try:
                        size = file_path.stat().st_size
                        total_size += size
                        arcname = file_path.relative_to(path.parent)
                        files_to_zip.append((file_path, arcname, size))
                    except (OSError, PermissionError):
                        continue
    
    if total_size == 0:
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED):
            pass
        yield 100
        return

    bytes_written = 0
    last_progress = 0
    yield 0
    
    try:
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for file_path, arcname, size in files_to_zip:
                try:
                    zf.write(file_path, arcname)
                    bytes_written += size
                    current_progress = int((bytes_written / total_size) * 100)
                    if current_progress > last_progress:
                        yield current_progress
                        last_progress = current_progress
                except (OSError, PermissionError) as e:
                    log.warning(f"Skipping file during compression: {file_path} ({e})")
                    bytes_written += size
    except Exception as e:
        log.error(f"Compression failed for {output_zip}: {e}")
        if output_path.exists():
            output_path.unlink()
        raise

    if last_progress < 100:
        yield 100


def _is_zip_encrypted(zip_path: Path) -> bool:
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            for zinfo in zf.infolist():
                if zinfo.flag_bits & 0x1:
                    return True
    except (zipfile.BadZipFile, FileNotFoundError):
        return False
    except Exception as e:
        log.warning(f"Could not check zip encryption for {zip_path}: {e}")
        return False
    return False


def extract_archive(
    zip_path: str, destination: str, password: str | None = None
) -> Generator[int, None, None]:
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
            last_progress = 0
            yield 0

            for member in infolist:
                if ".." in member.filename or os.path.isabs(member.filename):
                    log.warning(f"Skipping potentially malicious path in zip: {member.filename}")
                    continue
                
                zf.extract(member, dest_path, pwd=pwd_bytes)
                extracted_size += member.file_size
                
                current_progress = int((extracted_size / total_size) * 100)
                if current_progress > last_progress:
                    yield current_progress
                    last_progress = current_progress

            if last_progress < 100:
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


# --- File Browsing and Management Endpoints ---
def _scan_directory(path: Path):
    """Blocking function to scan a directory."""
    content = []
    try:
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
        headers = {
            "Cache-Control": "public, max-age=3600",
            "ETag": hashlib.md5(thumbnail_bytes).hexdigest()
        }
        return Response(content=thumbnail_bytes, media_type="image/png", headers=headers)
    else:
        raise HTTPException(status_code=404, detail="Thumbnail not available for this file.")


@router.post("/compress")
async def stream_compress_files(payload: CompressPayload):
    async def progress_generator():
        last_progress = -1
        try:
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
                    loop.call_soon_threadsafe(queue.put_nowait, None)
            
            asyncio.create_task(asyncio.to_thread(run_compression))
            
            while True:
                data = await queue.get()
                if data is None:
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
                    loop.call_soon_threadsafe(queue.put_nowait, None)
            
            asyncio.create_task(asyncio.to_thread(run_extraction))
            
            while True:
                data = await queue.get()
                if data is None:
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
    tasks = [_delete_item_task(path_str) for path_str in payload.paths]
    results = await asyncio.gather(*tasks)
    
    succeeded = [res for res in results if res["success"]]
    failed = [{"path": res["path"], "reason": res["reason"]} for res in results if not res["success"]]

    if not succeeded and failed:
        raise HTTPException(status_code=500, detail={"message": "All delete operations failed.", "details": failed})
    
    return {"succeeded": succeeded, "failed": failed}


@router.get("/download")
async def download_file(path: str = Query(...)):
    """
    Simple file download endpoint.
    For large files or resuming support, use the transfers/download endpoints.
    """
    file_path = _validate_and_resolve_path(path)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="The specified path is not a file.")
    
    file_size = file_path.stat().st_size
    
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
                    if await asyncio.to_thread(final_dest_path.is_dir):
                        await asyncio.to_thread(shutil.rmtree, final_dest_path)
                    else:
                        await asyncio.to_thread(os.remove, final_dest_path)
                elif payload.conflict_resolution == "rename":
                    final_dest_path = await asyncio.to_thread(_get_unique_filename, final_dest_path)

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