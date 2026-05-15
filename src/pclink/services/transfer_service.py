# src/pclink/services/transfer_service.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import json
import logging
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, Optional

from ..core.constants import DOWNLOADS_PATH, UPLOADS_PATH
from ..services.file_service import AIOFILES_INSTALLED, file_service

if AIOFILES_INSTALLED:
    import aiofiles

log = logging.getLogger(__name__)

# Constants
UPLOAD_CHUNK_SIZE = 1024 * 1024  # 1MB
DOWNLOAD_CHUNK_SIZE = 1024 * 1024  # 1MB
UPLOAD_BUFFER_SIZE = 4 * 1024 * 1024  # 4MB

# Storage Paths
TEMP_UPLOAD_DIR = UPLOADS_PATH
DOWNLOAD_SESSION_DIR = DOWNLOADS_PATH
TEMP_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOAD_SESSION_DIR.mkdir(parents=True, exist_ok=True)


class TransferService:
    def __init__(self):
        # Memory State (Avoid defaultdict to prevent implicit memory leaks)
        self.active_uploads: Dict[str, Dict[str, str]] = {}
        self.active_downloads: Dict[str, Dict[str, Dict]] = {}

        self.transfer_locks: Dict[str, asyncio.Lock] = {}
        self._lock_creation_lock = asyncio.Lock()  # Protects dynamic lock creation

        self.chunk_buffers: Dict[str, Dict[int, bytes]] = {}
        self.buffer_sizes: Dict[str, int] = {}  # Tracks memory usage per upload
        self.next_write_offset: Dict[str, int] = {}

    @asynccontextmanager
    async def lock(self, resource_id: str):
        async with self._lock_creation_lock:
            if resource_id not in self.transfer_locks:
                self.transfer_locks[resource_id] = asyncio.Lock()
            lock = self.transfer_locks[resource_id]
        async with lock:
            yield

    def _validate_transfer_id(self, transfer_id: str) -> str:
        """Prevent Path Traversal by ensuring ID is a valid UUID format."""
        if not transfer_id or not transfer_id.replace("-", "").isalnum():
            raise ValueError("Invalid transfer ID structure.")
        return transfer_id

    def _get_files(self, transfer_id: str, type: str):
        transfer_id = self._validate_transfer_id(transfer_id)
        base_dir = TEMP_UPLOAD_DIR if type == "upload" else DOWNLOAD_SESSION_DIR
        return base_dir / f"{transfer_id}.meta", base_dir / f"{transfer_id}.part"

    async def read_metadata(self, transfer_id: str, type: str) -> Optional[Dict]:
        meta_file, _ = self._get_files(transfer_id, type)
        if not meta_file.exists():
            return None

        def _read_sync():
            return json.loads(meta_file.read_text(encoding="utf-8"))

        try:
            if AIOFILES_INSTALLED:
                async with aiofiles.open(meta_file, "r", encoding="utf-8") as f:
                    return json.loads(await f.read())
            return await asyncio.to_thread(_read_sync)
        except Exception as e:
            log.error(f"Failed to read session {transfer_id}: {e}")
            return None

    async def save_metadata(self, transfer_id: str, data: Dict, type: str):
        meta_file, _ = self._get_files(transfer_id, type)

        def _save_sync():
            meta_file.write_text(json.dumps(data), encoding="utf-8")

        try:
            if AIOFILES_INSTALLED:
                async with aiofiles.open(meta_file, "w", encoding="utf-8") as f:
                    await f.write(json.dumps(data))
            else:
                await asyncio.to_thread(_save_sync)
        except Exception as e:
            log.error(f"Failed to save session {transfer_id}: {e}")

    def verify_ownership(self, metadata: Dict, client_id: str) -> bool:
        return metadata.get("client_id") == client_id

    async def get_received_bytes(self, upload_id: str) -> int:
        """Public accessor for partial file size to avoid leaky abstractions."""
        _, part = self._get_files(upload_id, "upload")
        return part.stat().st_size if part.exists() else 0

    async def cleanup_session(self, transfer_id: str, type: str = "upload"):
        meta_file, part_file = self._get_files(transfer_id, type)

        def _unlink_sync():
            meta_file.unlink(missing_ok=True)
            part_file.unlink(missing_ok=True)

        await asyncio.to_thread(_unlink_sync)

        # Ensure complete memory footprint cleanup
        async with self._lock_creation_lock:
            self.chunk_buffers.pop(transfer_id, None)
            self.buffer_sizes.pop(transfer_id, None)
            self.next_write_offset.pop(transfer_id, None)
            self.transfer_locks.pop(transfer_id, None)

    # --- UPLOAD ---

    async def initiate_upload(
        self,
        client_id: str,
        dest_path: str,
        file_name: str,
        file_size: int,
        conflict: str,
    ):
        dest = file_service.validate_path(dest_path)
        if not dest.is_dir():
            raise ValueError("Destination not a directory")

        from ..core.validators import validate_filename

        safe_name = validate_filename(file_name)
        final_path = dest / safe_name

        if final_path.exists():
            if conflict == "abort":
                raise FileExistsError("File exists")
            elif conflict == "keep_both":
                final_path = file_service.get_unique_path(final_path)

        final_path_str = str(final_path)

        async with self.lock(f"init_{final_path_str}"):
            # Resume capability
            if (
                client_id in self.active_uploads
                and final_path_str in self.active_uploads[client_id]
            ):
                exist_id = self.active_uploads[client_id][final_path_str]
                _, part = self._get_files(exist_id, "upload")
                if part.exists():
                    return {"upload_id": exist_id, "final_file_name": final_path.name}

            # New session
            import uuid

            upload_id = str(uuid.uuid4())
            meta = {
                "client_id": client_id,
                "final_path": final_path_str,
                "file_name": final_path.name,
                "created_at": time.time(),
                "file_size": file_size,
                "status": "active",
            }
            await self.save_metadata(upload_id, meta, "upload")
            _, part = self._get_files(upload_id, "upload")

            def _init_part_sync():
                part.write_bytes(b"")

            await asyncio.to_thread(_init_part_sync)

            if client_id not in self.active_uploads:
                self.active_uploads[client_id] = {}
            self.active_uploads[client_id][final_path_str] = upload_id

            self.next_write_offset[upload_id] = 0
            self.chunk_buffers[upload_id] = {}
            self.buffer_sizes[upload_id] = 0

            return {"upload_id": upload_id, "final_file_name": final_path.name}

    async def write_chunk(self, upload_id: str, offset: int, data: bytes) -> Dict:
        async with self.lock(upload_id):
            if upload_id not in self.chunk_buffers:
                self.chunk_buffers[upload_id] = {}
                self.buffer_sizes[upload_id] = 0

            # State Recovery
            if upload_id not in self.next_write_offset:
                _, part = self._get_files(upload_id, "upload")
                self.next_write_offset[upload_id] = (
                    part.stat().st_size if part.exists() else 0
                )

            expected = self.next_write_offset[upload_id]
            if offset < expected:
                return {"status": "ignored"}

            chunk_size = len(data)
            current_buffer = self.buffer_sizes.get(upload_id, 0)

            # Security Fix: Prevent OOM (Memory Exhaustion) Attacks

            if offset > expected and (current_buffer + chunk_size) > UPLOAD_BUFFER_SIZE:
                raise BufferError("Upload buffer exceeded. Missing chunks detected.")

            self.chunk_buffers[upload_id][offset] = data
            self.buffer_sizes[upload_id] += chunk_size

            # Performance Fix: Batch-flush sequential chunks efficiently
            _, part_file = self._get_files(upload_id, "upload")
            written, curr = 0, expected
            chunks_to_write = []

            while curr in self.chunk_buffers[upload_id]:
                chunk = self.chunk_buffers[upload_id].pop(curr)
                chunks_to_write.append(chunk)
                written += len(chunk)
                curr += len(chunk)

            if chunks_to_write:
                combined_data = b"".join(chunks_to_write)
                if AIOFILES_INSTALLED:
                    async with aiofiles.open(part_file, "ab") as f:
                        await f.write(combined_data)
                else:

                    def _append_sync():
                        with part_file.open("ab") as f:
                            f.write(combined_data)

                    await asyncio.to_thread(_append_sync)

                self.next_write_offset[upload_id] = curr
                self.buffer_sizes[upload_id] -= written

            return {"status": "received", "bytes_written": written, "next_offset": curr}

    async def complete_upload(self, upload_id: str):
        async with self.lock(upload_id):
            meta = await self.read_metadata(upload_id, "upload")
            if not meta:
                raise FileNotFoundError("Session not found")

            if self.chunk_buffers.get(upload_id):
                raise ValueError("Incomplete chunks left in memory")

            _, part_file = self._get_files(upload_id, "upload")
            final_path = Path(meta["final_path"])

            if (sz := meta.get("file_size")) and part_file.stat().st_size != sz:
                raise ValueError("Final size mismatch")

            # Execute blocking folder/file creation in thread
            def _finalize_file():
                final_path.parent.mkdir(parents=True, exist_ok=True)
                if final_path.exists():
                    final_path.unlink()
                shutil.move(str(part_file), str(final_path))

            await asyncio.to_thread(_finalize_file)

            cid = meta["client_id"]
            if cid in self.active_uploads:
                self.active_uploads[cid].pop(str(final_path), None)
                if not self.active_uploads[cid]:  # Clean empty client dicts
                    del self.active_uploads[cid]

            await self.cleanup_session(upload_id, "upload")
            return str(final_path)

    # --- DOWNLOAD ---

    async def initiate_download(self, client_id: str, file_path: str):
        path = file_service.validate_path(file_path)
        if not path.is_file():
            raise FileNotFoundError("File not found")

        stat = path.stat()
        import uuid

        dl_id = str(uuid.uuid4())
        session = {
            "client_id": client_id,
            "file_path": str(path),
            "file_name": path.name,
            "file_size": stat.st_size,
            "file_modified_at": stat.st_mtime,
            "bytes_downloaded": 0,
            "status": "active",
            "created_at": time.time(),
        }

        if client_id not in self.active_downloads:
            self.active_downloads[client_id] = {}
        self.active_downloads[client_id][dl_id] = session
        await self.save_metadata(dl_id, session, "download")

        return {"download_id": dl_id, "file_size": stat.st_size, "file_name": path.name}

    async def cleanup_stale_sessions(self, threshold_days: int = 7) -> int:
        """Deletes session files older than the specified threshold."""
        threshold_seconds = threshold_days * 24 * 60 * 60
        current_time = time.time()
        deleted_count = 0

        for dir_path in [TEMP_UPLOAD_DIR, DOWNLOAD_SESSION_DIR]:
            if not dir_path.exists():
                continue
            for f in dir_path.glob("*"):
                if f.is_file() and (
                    current_time - f.stat().st_mtime > threshold_seconds
                ):
                    try:
                        f.unlink()
                        deleted_count += 1
                    except Exception as e:
                        log.error(f"Failed to delete stale file {f}: {e}")
        return deleted_count

    async def restore_sessions(self):
        # Scan disk for active sessions on startup
        count_up = 0
        count_down = 0

        # Uploads
        for f in TEMP_UPLOAD_DIR.glob("*.meta"):
            try:
                data = json.loads(f.read_text("utf-8"))
                if data.get("status") == "active":
                    cli = data["client_id"]
                    if cli not in self.active_uploads:
                        self.active_uploads[cli] = {}
                    self.active_uploads[cli][data["final_path"]] = f.stem
                    count_up += 1
            except Exception:
                pass

        # Downloads
        for f in DOWNLOAD_SESSION_DIR.glob("*.meta"):
            try:
                data = json.loads(f.read_text("utf-8"))
                if data.get("status") == "active":
                    cli = data["client_id"]
                    if cli not in self.active_downloads:
                        self.active_downloads[cli] = {}
                    self.active_downloads[cli][f.stem] = data
                    count_down += 1
            except Exception:
                pass

        return {"restored_uploads": count_up, "restored_downloads": count_down}


# Global instance
transfer_service = TransferService()
