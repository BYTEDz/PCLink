# src/pclink/services/file_service.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import hashlib
import logging
import mimetypes
import os
import platform
import shutil
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Generator

from ..core.validators import validate_filename

log = logging.getLogger(__name__)

# Optional dependencies
try:
    from PIL import Image
    PIL_INSTALLED = True
except ImportError:
    PIL_INSTALLED = False

try:
    import aiofiles
    AIOFILES_INSTALLED = True
except ImportError:
    AIOFILES_INSTALLED = False

# Constants
HOME_DIR = Path.home().resolve()
THUMBNAIL_CACHE_DIR = Path(tempfile.gettempdir()) / "pclink_thumbnails"
THUMBNAIL_CACHE_DIR.mkdir(exist_ok=True, parents=True)

class FileService:
    """Logic for file browsing, management, thumbnails, and archives."""

    def __init__(self):
        self._roots_cache = None

    def get_system_roots(self) -> List[Path]:
        """Get available system roots (drives on Windows, / on Unix)."""
        if self._roots_cache: return self._roots_cache
        
        if platform.system() == "Windows":
            roots = []
            try:
                import string
                from ctypes import windll
                drives_bitmask = windll.kernel32.GetLogicalDrives()
                for i, letter in enumerate(string.ascii_uppercase):
                    if drives_bitmask & (1 << i):
                        roots.append(Path(f"{letter}:\\"))
            except Exception:
                for d in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                    p = Path(f"{d}:\\")
                    if p.exists(): roots.append(p)
            self._roots_cache = roots
            return roots
        return [Path("/")]

    def is_path_safe(self, path: Path) -> bool:
        """Checks if a path is within allowed system roots or home."""
        safe_roots = self.get_system_roots() + [HOME_DIR]
        try:
            resolved = path.resolve()
        except Exception:
            resolved = path.absolute()

        for root in safe_roots:
            if str(resolved).startswith(str(root)):
                return True
        return False

    def validate_path(self, user_path: str, check_existence: bool = True) -> Path:
        """Validates and resolves a user-provided path string."""
        if not user_path: raise ValueError("Path cannot be empty")
        
        # Expand vars and user (~), then normalize
        path = Path(os.path.expanduser(os.path.expandvars(user_path)))
        
        if ".." in path.parts:
            raise PermissionError("Relative pathing ('..') is rejected")
            
        if not path.is_absolute():
            path = HOME_DIR / path
            
        resolved = path.resolve(strict=False)
        
        if check_existence and not resolved.exists():
            raise FileNotFoundError(f"Path not found: {user_path}")
            
        if not self.is_path_safe(resolved):
            raise PermissionError(f"Access to path denied: {user_path}")
            
        return resolved

    def get_item_type(self, name: str, is_dir: bool) -> str:
        if is_dir: return "folder"
        mime, _ = mimetypes.guess_type(name)
        if mime:
            if mime.startswith("video/"): return "video"
            if mime.startswith("image/"): return "image"
            if mime.startswith("audio/"): return "audio"
            if mime == "application/zip": return "archive"
        return "file"

    async def scan_directory(self, path: Path) -> List[Dict[str, Any]]:
        """Scans a directory and returns its items."""
        def _scan():
            if not os.access(path, os.R_OK):
                raise PermissionError(f"Read access denied: {path}")
            
            items = []
            for entry in os.scandir(path):
                try:
                    stat = entry.stat()
                    is_dir = entry.is_dir()
                    items.append({
                        "name": entry.name,
                        "path": str(path / entry.name),
                        "is_dir": is_dir,
                        "size": stat.st_size,
                        "modified_at": stat.st_mtime,
                        "item_type": self.get_item_type(entry.name, is_dir)
                    })
                except Exception: continue
            
            items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
            return items
            
        return await asyncio.to_thread(_scan)

    async def get_thumbnail(self, file_path: Path) -> Optional[bytes]:
        """Generates or retrieves a cached thumbnail for an image."""
        if not PIL_INSTALLED or not file_path.is_file(): return None
        
        def _get_thumb():
            try:
                stat = file_path.stat()
                key = hashlib.sha1(f"{file_path.resolve()}:{stat.st_mtime}:{stat.st_size}".encode()).hexdigest()
                cache_file = THUMBNAIL_CACHE_DIR / f"{key}.png"
                
                if cache_file.exists(): return cache_file.read_bytes()
                
                mime, _ = mimetypes.guess_type(file_path.name)
                if mime and mime.startswith("image/"):
                    with Image.open(file_path) as img:
                        img.thumbnail((256, 256))
                        buf = BytesIO()
                        img.convert("RGB").save(buf, format="PNG")
                        data = buf.getvalue()
                        cache_file.write_bytes(data)
                        return data
            except Exception: pass
            return None
            
        return await asyncio.to_thread(_get_thumb)

    async def compress(self, source_paths: List[str], target_zip: str) -> Generator[int, None, None]:
        """Compresses files/folders into a ZIP archive."""
        # This will be used with StreamingResponse in router
        from .system_service import system_service # For circular import safety if needed

        def _gen():
            resolved = [self.validate_path(p) for p in source_paths]
            out = self.validate_path(target_zip, check_existence=False)
            
            files = []
            total = 0
            for p in resolved:
                if p.is_file():
                    total += p.stat().st_size
                    files.append((p, p.name, p.stat().st_size))
                elif p.is_dir():
                    for root, _, fs in os.walk(p):
                        for f in fs:
                            fp = Path(root) / f
                            size = fp.stat().st_size
                            total += size
                            files.append((fp, fp.relative_to(p.parent), size))
            
            if not total:
                with zipfile.ZipFile(out, 'w') as zf: pass
                yield 100; return

            written = 0
            yield 0
            with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zf:
                for fp, arcname, size in files:
                    zf.write(fp, arcname)
                    written += size
                    yield int((written / total) * 100)
        
        return _gen()

    async def extract(self, zip_path: Path, dest: Path, password: Optional[str] = None) -> Generator[int, None, None]:
        """Extracts a ZIP archive."""
        def _gen():
            pwd = password.encode() if password else None
            with zipfile.ZipFile(zip_path, 'r') as zf:
                info = zf.infolist()
                total = sum(i.file_size for i in info)
                if not total:
                    zf.extractall(dest, pwd=pwd); yield 100; return
                
                ext = 0
                yield 0
                for m in info:
                    if ".." in m.filename or os.path.isabs(m.filename): continue
                    zf.extract(m, dest, pwd=pwd)
                    ext += m.file_size
                    yield int((ext / total) * 100)
        return _gen()

    async def delete_items(self, paths: List[str]) -> List[Dict[str, Any]]:
        results = []
        for p_str in paths:
            try:
                p = self.validate_path(p_str)
                if p.is_dir(): await asyncio.to_thread(shutil.rmtree, p)
                else: await asyncio.to_thread(p.unlink)
                results.append({"path": p_str, "success": True})
            except Exception as e:
                results.append({"path": p_str, "success": False, "reason": str(e)})
        return results

    async def move_copy(self, sources: List[str], dest_dir: Path, action: str, resolution: str):
        """Standard file operations for move/copy."""
        results = {"succeeded": [], "failed": [], "conflicts": []}
        
        for p_str in sources:
            try:
                src = self.validate_path(p_str)
                target = dest_dir / src.name
                
                if target.exists():
                    if resolution == "skip":
                        results["conflicts"].append(src.name); continue
                    elif resolution == "rename":
                        target = self.get_unique_path(target)
                    elif resolution == "overwrite":
                        if target.is_dir(): shutil.rmtree(target)
                        else: target.unlink()

                if action == "cut":
                    await asyncio.to_thread(shutil.move, str(src), str(target))
                    results["succeeded"].append(p_str)
                else:
                    if src.is_dir(): await asyncio.to_thread(shutil.copytree, str(src), str(target))
                    else: await asyncio.to_thread(shutil.copy2, str(src), str(target))
                    results["succeeded"].append(p_str)
            except Exception as e:
                results["failed"].append({"path": p_str, "reason": str(e)})
        return results

    async def get_file_iterator(self, path: Path, start: int, end: int, chunk_size: int = 65536):
        """Asynchronous iterator to read a byte range from a file."""
        try:
            if AIOFILES_INSTALLED:
                async with aiofiles.open(path, "rb") as f:
                    await f.seek(start)
                    remaining = (end - start) + 1
                    while remaining > 0:
                        chunk = await f.read(min(chunk_size, remaining))
                        if not chunk: break
                        remaining -= len(chunk)
                        yield chunk
            else:
                log.info("Using sync I/O fallback for streaming")
                with path.open("rb") as f:
                    f.seek(start)
                    remaining = (end - start) + 1
                    while remaining > 0:
                        data = f.read(min(chunk_size, remaining))
                        if not data: break
                        remaining -= len(data)
                        yield data
        except Exception as e:
            log.error(f"Streaming error for {path}: {e}")

    def get_unique_path(self, path: Path) -> Path:
        if not path.exists(): return path
        stem, suf, count = path.stem, path.suffix, 1
        while (path.parent / f"{stem} ({count}){suf}").exists(): count += 1
        return path.parent / f"{stem} ({count}){suf}"

# Global instance
file_service = FileService()
