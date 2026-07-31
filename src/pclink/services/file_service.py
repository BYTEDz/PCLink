# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import gettext
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

from ..core.validators import validate_filename

log = logging.getLogger(__name__)
_ = gettext.gettext

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
    """Logic for file browsing, management, thumbnails, archives, and batch operations."""

    def __init__(self):
        self._roots_cache = None
        self._roots_cache_time = 0.0
        self._metadata_cache = {}  # (str_path, mtime, size) -> dict / duration

    async def get_file_hash(self, path: str) -> str:
        """Fast hashing utilizing native C-implementation in modern Python."""

        def _read():
            with open(path, "rb") as f:
                if hasattr(hashlib, "file_digest"):
                    return hashlib.file_digest(f, "md5").hexdigest()
                hasher = hashlib.md5()
                for chunk in iter(lambda: f.read(131072), b""):
                    hasher.update(chunk)
                return hasher.hexdigest()

        return await asyncio.to_thread(_read)

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
            raise ValueError(_("Path cannot be empty"))

        path = Path(os.path.expanduser(os.path.expandvars(user_path)))

        if ".." in path.parts:
            raise PermissionError(_("Relative pathing ('..') is rejected"))

        if not path.is_absolute():
            path = HOME_DIR / path

        resolved = path.resolve(strict=False)

        if check_existence and not resolved.exists():
            raise FileNotFoundError(_("Path not found: {}").format(user_path))

        if not self.is_path_safe(resolved):
            raise PermissionError(_("Access to path denied: {}").format(user_path))

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
        """Scans a directory and returns items instantly (uses fast cache for durations)."""

        def _scan():
            if not os.access(path, os.R_OK):
                raise PermissionError(_("Read access denied: {}").format(path))

            items = []
            for entry in os.scandir(path):
                try:
                    stat = entry.stat()
                    is_dir = entry.is_dir()
                    item_type = self.get_item_type(entry.name, is_dir)
                    duration_ms = 0

                    if not is_dir and item_type in ("video", "audio"):
                        cache_key = (
                            str(path / entry.name),
                            stat.st_mtime,
                            stat.st_size,
                        )
                        if cache_key in self._metadata_cache:
                            duration_ms = self._metadata_cache[cache_key].get(
                                "duration", 0
                            )

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
                        # Convert palette and transparency images to RGBA to avoid Pillow UserWarnings
                        if (
                            img.mode in ("P", "PA", "1", "L")
                            or "transparency" in img.info
                        ):
                            img = img.convert("RGBA")

                        img.thumbnail((256, 256))
                        buf = BytesIO()

                        if img.mode == "RGBA":
                            img.save(buf, format="PNG")
                        else:
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
        """Extracts media info (duration, resolution) from a video or audio file on demand."""
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

    async def create_folder(self, parent_path: str, folder_name: str) -> None:
        """Creates a new folder under parent_path."""
        parent = self.validate_path(parent_path)
        if not parent.is_dir():
            raise NotADirectoryError(_("Parent path is not a directory"))

        name = validate_filename(folder_name)
        new_p = parent / name
        new_p = self.validate_path(str(new_p), check_existence=False)

        if new_p.exists():
            raise FileExistsError(_("Target already exists"))

        await asyncio.to_thread(new_p.mkdir)

    async def rename_item(self, path: str, new_name: str) -> None:
        """Renames a file or folder."""
        src = self.validate_path(path)

        if "/" in new_name or "\\" in new_name:
            dest = self.validate_path(new_name, check_existence=False)
        else:
            new_n = validate_filename(new_name)
            dest = src.parent / new_n

        dest = self.validate_path(str(dest), check_existence=False)

        if src.resolve() == dest.resolve():
            return

        if dest.exists():
            raise FileExistsError(_("Target already exists"))

        if not dest.parent.exists():
            await asyncio.to_thread(os.makedirs, str(dest.parent), exist_ok=True)

        await asyncio.to_thread(shutil.move, str(src), str(dest))

    async def batch_rename_items(self, items: List[Any]) -> Dict[str, Any]:
        """Renames multiple items in chunks with conflict detection and deduplication."""
        results, wait_list = [], []
        success_count = 0

        async def _do_rename(item: Any, is_retry: bool = False) -> dict:
            item_path = getattr(
                item, "path", item.get("path") if isinstance(item, dict) else None
            )
            target_path = getattr(
                item,
                "target_path",
                item.get("target_path") if isinstance(item, dict) else None,
            )
            new_name = getattr(
                item,
                "new_name",
                item.get("new_name") if isinstance(item, dict) else None,
            )

            try:
                src = self.validate_path(item_path)

                if target_path:
                    dest = self.validate_path(target_path, check_existence=False)
                elif new_name:
                    if ".." in new_name or "/" in new_name or "\\" in new_name:
                        return {
                            "path": item_path,
                            "status": "error",
                            "error": "UNSAFE_PATH",
                        }
                    raw_dest = src.parent / new_name
                    dest = self.validate_path(str(raw_dest), check_existence=False)
                else:
                    return {
                        "path": item_path,
                        "status": "error",
                        "error": "MISSING_DESTINATION",
                    }

                dest = dest.resolve(strict=False)

                if src.resolve() == dest.resolve():
                    return {
                        "path": item_path,
                        "status": "success",
                        "new_path": str(dest),
                    }

                if dest.exists():
                    if not is_retry:
                        return {"path": item_path, "status": "conflict"}

                    src_stat, dest_stat = src.stat(), dest.stat()
                    if src_stat.st_size == dest_stat.st_size:
                        if await self.get_file_hash(
                            str(src)
                        ) == await self.get_file_hash(str(dest)):
                            await asyncio.to_thread(os.remove, str(src))
                            return {
                                "path": item_path,
                                "status": "duplicate_deleted",
                                "new_path": str(dest),
                            }

                    return {
                        "path": item_path,
                        "status": "error",
                        "error": "TARGET_EXISTS",
                    }

                if not dest.parent.exists():
                    await asyncio.to_thread(
                        os.makedirs, str(dest.parent), exist_ok=True
                    )

                await asyncio.to_thread(shutil.move, str(src), str(dest))
                return {"path": item_path, "status": "success", "new_path": str(dest)}

            except Exception as e:
                log.error(f"Rename failed for {item_path}: {e}")
                return {"path": item_path, "status": "error", "error": str(e)}

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


file_service = FileService()
