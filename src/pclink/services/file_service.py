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
import time
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

log = logging.getLogger(__name__)

# Optional dependencies
try:
    from PIL import Image

    PIL_INSTALLED = True
except ImportError:
    PIL_INSTALLED = False

try:
    import av

    AV_INSTALLED = True
except ImportError:
    AV_INSTALLED = False

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
        self._roots_cache_time = 0.0
        self._metadata_cache = {}  # (str_path, mtime, size) -> dict / duration

    def get_system_roots(self) -> List[Path]:
        """Get available system roots (drives on Windows, / on Unix) with a short TTL cache."""
        now = time.time()
        if self._roots_cache and (now - self._roots_cache_time < 5.0):
            return self._roots_cache

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
                    if p.exists():
                        roots.append(p)
            self._roots_cache = roots
            self._roots_cache_time = now
            return roots

        roots = [Path("/")]
        self._roots_cache = roots
        self._roots_cache_time = now
        return roots

    def is_path_safe(self, path: Path) -> bool:
        """Checks if a path is within allowed system roots or home."""
        safe_roots = self.get_system_roots() + [HOME_DIR]
        try:
            resolved = path.resolve()
        except Exception:
            resolved = path.absolute()

        for root in safe_roots:
            try:
                resolved.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    def validate_path(self, user_path: str, check_existence: bool = True) -> Path:
        """Validates and resolves a user-provided path string."""
        if not user_path:
            raise ValueError("Path cannot be empty")

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
        if is_dir:
            return "folder"

        mime, _ = mimetypes.guess_type(name)
        if mime:
            if mime.startswith("video/"):
                return "video"
            if mime.startswith("image/"):
                return "image"
            if mime.startswith("audio/"):
                return "audio"
            if mime in (
                "application/zip",
                "application/x-zip-compressed",
                "application/x-tar",
                "application/x-gzip",
                "application/x-bzip2",
                "application/x-7z-compressed",
                "application/x-rar-compressed",
            ):
                return "archive"

        ext = Path(name).suffix.lower()
        if ext in (".mp4", ".mkv", ".avi", ".webm", ".mov", ".flv", ".wmv", ".m4v"):
            return "video"
        if ext in (
            ".jpg",
            ".jpeg",
            ".png",
            ".gif",
            ".webp",
            ".bmp",
            ".tiff",
            ".svg",
            ".ico",
        ):
            return "image"
        if ext in (".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".wma"):
            return "audio"
        if ext in (".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"):
            return "archive"

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
                    item_type = self.get_item_type(entry.name, is_dir)
                    duration_ms = 0

                    if not is_dir and item_type in ("video", "audio") and AV_INSTALLED:
                        file_path = path / entry.name
                        cache_key = (str(file_path), stat.st_mtime, stat.st_size)

                        if cache_key in self._metadata_cache:
                            duration_ms = self._metadata_cache[cache_key].get(
                                "duration", 0
                            )
                        else:
                            try:
                                with av.open(str(file_path)) as container:
                                    if container.duration is not None:
                                        duration_ms = container.duration // 1000
                                    elif container.streams and getattr(
                                        container.streams, "video", None
                                    ):
                                        stream = container.streams.video[0]
                                        if stream.duration and stream.time_base:
                                            duration_ms = int(
                                                float(
                                                    stream.duration * stream.time_base
                                                )
                                                * 1000
                                            )
                                self._metadata_cache[cache_key] = {
                                    "duration": duration_ms
                                }
                            except Exception:
                                pass

                    items.append(
                        {
                            "name": entry.name,
                            "path": str(path / entry.name),
                            "is_dir": is_dir,
                            "size": stat.st_size,
                            "modified_at": stat.st_mtime,
                            "item_type": item_type,
                            "duration": duration_ms,
                        }
                    )
                except Exception:
                    continue

            items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
            return items

        return await asyncio.to_thread(_scan)

    async def get_thumbnail(self, file_path: Path) -> Optional[bytes]:
        """Generates or retrieves a cached thumbnail for an image or a video."""
        if not PIL_INSTALLED or not file_path.is_file():
            return None

        def _get_thumb():
            try:
                stat = file_path.stat()
                key = hashlib.sha1(
                    f"{file_path.resolve()}:{stat.st_mtime}:{stat.st_size}".encode()
                ).hexdigest()
                cache_file = THUMBNAIL_CACHE_DIR / f"{key}.png"

                if cache_file.exists():
                    return cache_file.read_bytes()

                mime, _ = mimetypes.guess_type(file_path.name)
                ext = file_path.suffix.lower()

                if (mime and mime.startswith("image/")) or ext in (
                    ".jpg",
                    ".jpeg",
                    ".png",
                    ".gif",
                    ".webp",
                    ".bmp",
                ):
                    with Image.open(file_path) as img:
                        img.thumbnail((256, 256))
                        buf = BytesIO()
                        img.convert("RGB").save(buf, format="PNG")
                        data = buf.getvalue()
                        cache_file.write_bytes(data)
                        return data
                elif (
                    (mime and mime.startswith("video/"))
                    or ext in (".mp4", ".mkv", ".avi", ".mov")
                ) and AV_INSTALLED:
                    with av.open(str(file_path)) as container:
                        if not container.streams.video:
                            return None
                        stream = container.streams.video[0]

                        if container.duration:
                            try:
                                container.seek(container.duration // 2)
                            except Exception:
                                if stream.duration:
                                    try:
                                        container.seek(
                                            stream.duration // 2,
                                            any_frame=False,
                                            backward=True,
                                            stream=stream,
                                        )
                                    except Exception:
                                        pass
                        elif stream.duration:
                            try:
                                container.seek(
                                    stream.duration // 2,
                                    any_frame=False,
                                    backward=True,
                                    stream=stream,
                                )
                            except Exception:
                                pass

                        for frame in container.decode(stream):
                            img = frame.to_image()
                            img.thumbnail((256, 256))
                            buf = BytesIO()
                            img.convert("RGB").save(buf, format="PNG")
                            data = buf.getvalue()
                            cache_file.write_bytes(data)
                            return data
            except Exception as e:
                log.error(f"Failed to generate thumbnail for {file_path}: {e}")
            return None

        return await asyncio.to_thread(_get_thumb)

    async def get_media_info(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """Extracts media info (duration, resolution) from a video or audio file."""
        if not AV_INSTALLED or not file_path.is_file():
            return None

        def _get_info():
            try:
                stat = file_path.stat()
                cache_key = (str(file_path), stat.st_mtime, stat.st_size)

                if (
                    cache_key in self._metadata_cache
                    and "width" in self._metadata_cache[cache_key]
                ):
                    return self._metadata_cache[cache_key]

                mime, _ = mimetypes.guess_type(file_path.name)
                ext = file_path.suffix.lower()
                is_media = (
                    mime and (mime.startswith("video/") or mime.startswith("audio/"))
                ) or ext in (
                    ".mp4",
                    ".mkv",
                    ".avi",
                    ".mov",
                    ".mp3",
                    ".wav",
                    ".flac",
                    ".m4a",
                )

                if not is_media:
                    return None

                with av.open(str(file_path)) as container:
                    video_streams = container.streams.video
                    stream = video_streams[0] if video_streams else None
                    duration_ms = 0
                    if container.duration is not None:
                        duration_ms = container.duration // 1000
                    elif stream and stream.duration and stream.time_base:
                        duration_ms = int(
                            float(stream.duration * stream.time_base) * 1000
                        )

                    info = {"duration": duration_ms}
                    if stream:
                        info.update({"width": stream.width, "height": stream.height})
                    self._metadata_cache[cache_key] = info
                    return info
            except Exception:
                return None

        return await asyncio.to_thread(_get_info)

    async def compress(
        self, source_paths: List[str], target_zip: str
    ) -> Generator[int, None, None]:
        """Compresses files/folders into a ZIP archive."""

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
                            try:
                                size = fp.stat().st_size
                                total += size
                                files.append((fp, fp.relative_to(p.parent), size))
                            except Exception:
                                continue

            if not total:
                with zipfile.ZipFile(out, "w") as zf:
                    pass
                yield 100
                return

            written = 0
            yield 0
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
                for fp, arcname, size in files:
                    try:
                        zf.write(fp, arcname)
                    except Exception as e:
                        log.error(f"Failed to compress {fp}: {e}")
                    written += size
                    yield int((written / total) * 100)

        return _gen()

    async def extract(
        self, zip_path: Path, dest: Path, password: Optional[str] = None
    ) -> Generator[int, None, None]:
        """Extracts a ZIP archive."""

        def _gen():
            pwd = password.encode() if password else None
            resolved_dest = dest.resolve()
            with zipfile.ZipFile(zip_path, "r") as zf:
                info = zf.infolist()
                total = sum(i.file_size for i in info)
                if not total:
                    zf.extractall(dest, pwd=pwd)
                    yield 100
                    return

                ext = 0
                yield 0
                for m in info:
                    if ".." in m.filename or os.path.isabs(m.filename):
                        continue

                    target_path = Path(dest / m.filename).resolve()
                    try:
                        target_path.relative_to(resolved_dest)
                    except ValueError:
                        continue

                    zf.extract(m, dest, pwd=pwd)
                    ext += m.file_size
                    yield int((ext / total) * 100)

        return _gen()

    async def delete_items(self, paths: List[str]) -> List[Dict[str, Any]]:
        results = []

        async def _do_delete(p_str: str) -> Dict[str, Any]:
            try:
                p = self.validate_path(p_str)
                if p.is_dir():
                    await asyncio.to_thread(shutil.rmtree, p)
                else:
                    await asyncio.to_thread(p.unlink)
                return {"path": p_str, "success": True}
            except Exception as e:
                return {"path": p_str, "success": False, "reason": str(e)}

        chunk_size = 50
        for i in range(0, len(paths), chunk_size):
            chunk = paths[i : i + chunk_size]
            chunk_results = await asyncio.gather(*[_do_delete(p) for p in chunk])
            results.extend(chunk_results)

        return results

    async def move_copy(
        self, sources: List[str], dest_dir: Path, action: str, resolution: str
    ):
        """Standard file operations for move/copy chunked for concurrency limits."""
        results = {"succeeded": [], "failed": [], "conflicts": []}

        async def _do_op(p_str: str) -> Dict[str, Any]:
            res_item = {"action": "success", "val": p_str}
            try:
                src = self.validate_path(p_str)
                target = dest_dir / src.name

                if src.is_dir() and (dest_dir == src or src in dest_dir.parents):
                    return {
                        "action": "failed",
                        "val": {
                            "path": p_str,
                            "reason": "Cannot copy or move a directory into itself",
                        },
                    }

                if target.exists():
                    if resolution == "skip":
                        return {"action": "conflict", "val": src.name}
                    elif resolution == "rename":
                        target = self.get_unique_path(target)
                    elif resolution == "overwrite":
                        if target.is_dir():
                            await asyncio.to_thread(shutil.rmtree, target)
                        else:
                            await asyncio.to_thread(target.unlink)

                if action == "cut":
                    await asyncio.to_thread(shutil.move, str(src), str(target))
                else:
                    if src.is_dir():
                        await asyncio.to_thread(shutil.copytree, str(src), str(target))
                    else:
                        await asyncio.to_thread(shutil.copy2, str(src), str(target))
                return res_item
            except Exception as e:
                return {"action": "failed", "val": {"path": p_str, "reason": str(e)}}

        chunk_size = 50
        for i in range(0, len(sources), chunk_size):
            chunk = sources[i : i + chunk_size]
            chunk_results = await asyncio.gather(*[_do_op(c) for c in chunk])

            for cr in chunk_results:
                if cr["action"] == "conflict":
                    results["conflicts"].append(cr["val"])
                elif cr["action"] == "failed":
                    results["failed"].append(cr["val"])
                else:
                    results["succeeded"].append(cr["val"])

        return results

    async def get_file_iterator(
        self, path: Path, start: int, end: int, chunk_size: int = 65536
    ):
        """Asynchronous iterator to read a byte range from a file."""
        try:
            if AIOFILES_INSTALLED:
                async with aiofiles.open(path, "rb") as f:
                    await f.seek(start)
                    remaining = (end - start) + 1
                    while remaining > 0:
                        chunk = await f.read(min(chunk_size, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        yield chunk
            else:
                log.info("Using non-blocking sync I/O fallback for streaming")

                def _read_chunk(f_obj, size):
                    return f_obj.read(size)

                f = await asyncio.to_thread(path.open, "rb")
                try:
                    await asyncio.to_thread(f.seek, start)
                    remaining = (end - start) + 1
                    while remaining > 0:
                        chunk = await asyncio.to_thread(
                            _read_chunk, f, min(chunk_size, remaining)
                        )
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        yield chunk
                finally:
                    await asyncio.to_thread(f.close)
        except Exception as e:
            log.error(f"Streaming error for {path}: {e}")

    def get_unique_path(self, path: Path) -> Path:
        if not path.exists():
            return path
        stem, suf, count = path.stem, path.suffix, 1
        while (path.parent / f"{stem} ({count}){suf}").exists():
            count += 1
        return path.parent / f"{stem} ({count}){suf}"


# Global instance
file_service = FileService()
