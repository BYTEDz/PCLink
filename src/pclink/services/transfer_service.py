# src/pclink/services/transfer_service.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import hashlib
import json
import logging
import os
import shutil
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, Any, Optional, List

from ..core.constants import APP_DATA_PATH, UPLOADS_PATH, DOWNLOADS_PATH
from ..services.file_service import file_service, AIOFILES_INSTALLED

if AIOFILES_INSTALLED:
    import aiofiles

log = logging.getLogger(__name__)

# Constants
UPLOAD_CHUNK_SIZE = 1024 * 1024  # 1MB
DOWNLOAD_CHUNK_SIZE = 1024 * 1024 # 1MB
UPLOAD_BUFFER_SIZE = 4 * 1024 * 1024 # 4MB

# Storage Paths
TEMP_UPLOAD_DIR = UPLOADS_PATH
DOWNLOAD_SESSION_DIR = DOWNLOADS_PATH
TEMP_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOAD_SESSION_DIR.mkdir(parents=True, exist_ok=True)

class TransferService:
    def __init__(self):
        # Memory State
        self.active_uploads: Dict[str, Dict[str, str]] = defaultdict(dict) # client_id -> {final_path: upload_id}
        self.active_downloads: Dict[str, Dict[str, Dict]] = defaultdict(dict) # client_id -> {download_id: session}
        
        self.transfer_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.chunk_buffers: Dict[str, Dict[int, bytes]] = {}
        self.next_write_offset: Dict[str, int] = {}
        
    @asynccontextmanager
    async def lock(self, resource_id: str):
        if resource_id not in self.transfer_locks:
            self.transfer_locks[resource_id] = asyncio.Lock()
        async with self.transfer_locks[resource_id]:
            yield

    def _get_files(self, transfer_id: str, type: str):
        base_dir = TEMP_UPLOAD_DIR if type == "upload" else DOWNLOAD_SESSION_DIR
        return base_dir / f"{transfer_id}.meta", base_dir / f"{transfer_id}.part"

    def manage_session(self, transfer_id: str, data: Optional[Dict] = None, op: str = "read", type: str = "upload"):
        meta_file, _ = self._get_files(transfer_id, type)
        try:
            if op == "read":
                if meta_file.exists():
                    return json.loads(meta_file.read_text(encoding="utf-8"))
                return None
            elif op == "save":
                meta_file.write_text(json.dumps(data), encoding="utf-8")
                return data
            elif op == "delete":
                if meta_file.exists(): meta_file.unlink()
        except Exception as e:
            log.error(f"Session op {op} failed for {transfer_id}: {e}")
            return None

    def verify_ownership(self, metadata: Dict, client_id: str) -> bool:
        return metadata.get("client_id") == client_id

    async def cleanup_session(self, transfer_id: str, type: str = "upload"):
        meta_file, part_file = self._get_files(transfer_id, type)
        if meta_file.exists(): meta_file.unlink()
        if part_file.exists(): part_file.unlink()
        
        if type == "upload":
            self.chunk_buffers.pop(transfer_id, None)
            self.next_write_offset.pop(transfer_id, None)
            self.transfer_locks.pop(transfer_id, None)

    # --- UPLOAD ---

    async def initiate_upload(self, client_id: str, dest_path: str, file_name: str, file_size: int, conflict: str):
        dest = file_service.validate_path(dest_path)
        if not dest.is_dir(): raise ValueError("Destination not a directory")
        
        from ..core.validators import validate_filename
        safe_name = validate_filename(file_name)
        final_path = dest / safe_name
        
        if final_path.exists():
            if conflict == "abort": raise FileExistsError("File exists")
            elif conflict == "keep_both": final_path = file_service.get_unique_path(final_path)
            
        final_path_str = str(final_path)
        
        async with self.lock(f"init_{final_path_str}"):
            # Resume capability
            if final_path_str in self.active_uploads[client_id]:
                exist_id = self.active_uploads[client_id][final_path_str]
                _, part = self._get_files(exist_id, "upload")
                if part.exists():
                    return {"upload_id": exist_id, "final_file_name": final_path.name}

            # New session
            upload_id = str(uuid.uuid4())
            meta = {
                "client_id": client_id,
                "final_path": final_path_str,
                "file_name": final_path.name,
                "created_at": time.time(),
                "file_size": file_size,
                "status": "active"
            }
            self.manage_session(upload_id, meta, "save", "upload")
            _, part = self._get_files(upload_id, "upload")
            part.write_bytes(b"")
            
            self.active_uploads[client_id][final_path_str] = upload_id
            self.next_write_offset[upload_id] = 0
            self.chunk_buffers[upload_id] = {}
            
            return {"upload_id": upload_id, "final_file_name": final_path.name}

    async def write_chunk(self, upload_id: str, offset: int, data: bytes) -> Dict:
        async with self.lock(upload_id):
            if upload_id not in self.chunk_buffers: self.chunk_buffers[upload_id] = {}
            
            # Recovery
            if upload_id not in self.next_write_offset:
                _, part = self._get_files(upload_id, "upload")
                self.next_write_offset[upload_id] = part.stat().st_size if part.exists() else 0

            expected = self.next_write_offset[upload_id]
            if offset < expected: return {"status": "ignored"}

            self.chunk_buffers[upload_id][offset] = data
            
            # Flush
            _, part_file = self._get_files(upload_id, "upload")
            written = 0
            curr = expected
            
            while curr in self.chunk_buffers[upload_id]:
                chunk = self.chunk_buffers[upload_id].pop(curr)
                if AIOFILES_INSTALLED:
                    async with aiofiles.open(part_file, "ab") as f: await f.write(chunk)
                else:
                    with part_file.open("ab") as f: f.write(chunk)
                
                written += len(chunk)
                curr += len(chunk)
            
            self.next_write_offset[upload_id] = curr
            return {"status": "received", "bytes_written": written, "next_offset": curr}

    async def complete_upload(self, upload_id: str):
        async with self.lock(upload_id):
            meta = self.manage_session(upload_id, op="read", type="upload")
            if not meta: raise FileNotFoundError("Session not found")
            
            if self.chunk_buffers.get(upload_id): raise ValueError("Incomplete chunks")
            
            _, part_file = self._get_files(upload_id, "upload")
            final_path = Path(meta["final_path"])
            
            if (sz := meta.get("file_size")) and part_file.stat().st_size != sz:
                raise ValueError("Size mismatch")

            final_path.parent.mkdir(parents=True, exist_ok=True)
            if final_path.exists(): final_path.unlink()
            await asyncio.to_thread(shutil.move, str(part_file), str(final_path))
            
            cid = meta["client_id"]
            if cid in self.active_uploads:
                self.active_uploads[cid].pop(str(final_path), None)
            
            self.manage_session(upload_id, op="delete", type="upload")
            await self.cleanup_session(upload_id, "upload")
            return str(final_path)

    # --- DOWNLOAD ---

    async def initiate_download(self, client_id: str, file_path: str):
        path = file_service.validate_path(file_path)
        if not path.is_file(): raise FileNotFoundError("File not found")
        
        stat = path.stat()
        dl_id = str(uuid.uuid4())
        session = {
            "client_id": client_id,
            "file_path": str(path),
            "file_name": path.name,
            "file_size": stat.st_size,
            "file_modified_at": stat.st_mtime,
            "bytes_downloaded": 0,
            "status": "active",
            "created_at": time.time()
        }
        
        self.active_downloads[client_id][dl_id] = session
        await asyncio.to_thread(self.manage_session, dl_id, session, "save", "download")
        
        return {"download_id": dl_id, "file_size": stat.st_size, "file_name": path.name}

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
                    self.active_uploads[cli][data["final_path"]] = f.stem
                    count_up += 1
            except: pass
            
        # Downloads
        for f in DOWNLOAD_SESSION_DIR.glob("*.meta"):
            try:
                data = json.loads(f.read_text("utf-8"))
                if data.get("status") == "active":
                    cli = data["client_id"]
                    self.active_downloads[cli][f.stem] = data
                    count_down += 1
            except: pass
            
        return {"restored_uploads": count_up, "restored_downloads": count_down}

# Global instance
transfer_service = TransferService()
