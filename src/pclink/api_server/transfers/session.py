import asyncio
import json
import logging
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict

from fastapi import Header, HTTPException

# Performance: Use aiofiles if available
try:
    import aiofiles
    AIOFILES_INSTALLED = True
except ImportError:
    AIOFILES_INSTALLED = False

log = logging.getLogger(__name__)

# --- Constants ---
HOME_DIR = Path.home().resolve()
TEMP_UPLOAD_DIR = HOME_DIR / ".pclink_uploads"
DOWNLOAD_SESSION_DIR = HOME_DIR / ".pclink_downloads"

TEMP_UPLOAD_DIR.mkdir(exist_ok=True, parents=True)
DOWNLOAD_SESSION_DIR.mkdir(exist_ok=True, parents=True)

# --- Configuration ---
DOWNLOAD_CHUNK_SIZE = 65536
UPLOAD_CHUNK_SIZE = 262144
UPLOAD_BUFFER_SIZE = 1048576

# --- Global State ---
# {client_id: {file_path: upload_id}}
ACTIVE_UPLOADS: Dict[str, Dict[str, str]] = defaultdict(dict)
# {client_id: {download_id: session_info}}
ACTIVE_DOWNLOADS: Dict[str, Dict[str, Dict]] = defaultdict(dict)

TRANSFER_LOCKS: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
UPLOAD_BUFFERS: Dict[str, bytearray] = {}
CHUNK_BUFFERS: Dict[str, Dict[int, bytes]] = {}
NEXT_WRITE_OFFSET: Dict[str, int] = {}


async def get_client_id(
    x_device_id: str = Header(None, alias="X-Device-ID"),
    x_api_key: str = Header(None, alias="X-API-Key")
) -> str:
    if x_device_id and x_device_id.strip():
        return x_device_id.strip()
    if x_api_key and x_api_key.strip():
        return x_api_key.strip()
    
    log.warning("Transfer request received without valid client identifier")
    raise HTTPException(status_code=403, detail="Missing client identifier.")


def verify_session_ownership(session_metadata: Dict | None, client_id: str) -> bool:
    if not session_metadata:
        return False
    session_client = session_metadata.get("client_id")
    return session_client and session_client == client_id


async def cleanup_transfer_session(transfer_id: str):
    TRANSFER_LOCKS.pop(transfer_id, None)
    UPLOAD_BUFFERS.pop(transfer_id, None)
    CHUNK_BUFFERS.pop(transfer_id, None)
    NEXT_WRITE_OFFSET.pop(transfer_id, None)


def manage_session_file(session_id: str, data: Dict | None = None, operation: str = "read", session_type: str = "download"):
    directory = DOWNLOAD_SESSION_DIR if session_type == "download" else TEMP_UPLOAD_DIR
    extension = ".json" if session_type == "download" else ".meta"
    session_file = directory / f"{session_id}{extension}"
    
    try:
        if operation == "delete":
            session_file.unlink(missing_ok=True)
            if session_type == "upload":
                (directory / f"{session_id}.part").unlink(missing_ok=True)
        elif operation == "save" and data:
            if "client_id" not in data:
                raise ValueError("Session metadata must contain 'client_id'")
            session_file.write_text(json.dumps(data), encoding="utf-8")
        elif operation == "read":
            if session_file.exists():
                return json.loads(session_file.read_text(encoding="utf-8"))
    except Exception as e:
        log.error(f"Session {operation} failed for {session_id}: {e}")
        raise
    return None


def restore_sessions():
    restored_uploads = 0
    restored_downloads = 0
    
    # Uploads
    for meta_file in TEMP_UPLOAD_DIR.glob("*.meta"):
        try:
            upload_id = meta_file.stem
            part_file = TEMP_UPLOAD_DIR / f"{upload_id}.part"
            if part_file.exists():
                metadata = manage_session_file(upload_id, operation="read", session_type="upload")
                if metadata and (client_id := metadata.get("client_id")) and (path := metadata.get("final_path")):
                    ACTIVE_UPLOADS[client_id][path] = upload_id
                    NEXT_WRITE_OFFSET[upload_id] = part_file.stat().st_size
                    restored_uploads += 1
        except Exception:
            pass

    # Downloads
    for session_file in DOWNLOAD_SESSION_DIR.glob("*.json"):
        try:
            download_id = session_file.stem
            data = manage_session_file(download_id, operation="read", session_type="download")
            if data and (client_id := data.get("client_id")):
                path = Path(data["file_path"])
                if path.exists() and path.stat().st_mtime == data.get("file_modified_at"):
                    ACTIVE_DOWNLOADS[client_id][download_id] = data
                    restored_downloads += 1
                else:
                    manage_session_file(download_id, operation="delete", session_type="download")
        except Exception:
            pass
            
    return {"restored_uploads": restored_uploads, "restored_downloads": restored_downloads}


async def cleanup_stale_sessions(threshold_days: int = 7):
    current_time = time.time()
    threshold = threshold_days * 24 * 60 * 60
    cleaned = {"uploads": 0, "downloads": 0}

    for meta in TEMP_UPLOAD_DIR.glob("*.meta"):
        if current_time - meta.stat().st_mtime > threshold:
            manage_session_file(meta.stem, operation="delete", session_type="upload")
            cleaned["uploads"] += 1
            
    for sess in DOWNLOAD_SESSION_DIR.glob("*.json"):
        if current_time - sess.stat().st_mtime > threshold:
            manage_session_file(sess.stem, operation="delete", session_type="download")
            cleaned["downloads"] += 1
            
    return cleaned