# src/pclink/core/device_manager.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import json
import logging
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import constants

log = logging.getLogger(__name__)


class Device:
    """Represents a paired device with specific permissions."""
    
    def __init__(self, device_id: str, device_name: str, api_key: str, 
                 device_fingerprint: str = "", platform: str = "", 
                 client_version: str = "", current_ip: str = "", 
                 is_approved: bool = False, created_at: datetime = None,
                 last_seen: datetime = None, hardware_id: str = "",
                 permissions: List[str] = None):
        self.device_id = device_id
        self.device_name = device_name
        self.api_key = api_key
        self.device_fingerprint = device_fingerprint
        self.platform = platform
        self.client_version = client_version
        self.current_ip = current_ip
        self.is_approved = is_approved
        self.created_at = created_at or datetime.now(timezone.utc)
        self.last_seen = last_seen or datetime.now(timezone.utc)
        self.hardware_id = hardware_id
        self.permissions = permissions or []
    
    def to_dict(self) -> Dict:
        return {
            "device_id": self.device_id,
            "device_name": self.device_name,
            "api_key": self.api_key,
            "device_fingerprint": self.device_fingerprint,
            "platform": self.platform,
            "client_version": self.client_version,
            "current_ip": self.current_ip,
            "is_approved": self.is_approved,
            "created_at": self.created_at.isoformat(),
            "last_seen": self.last_seen.isoformat(),
            "hardware_id": self.hardware_id,
            "permissions": ",".join(self.permissions) 
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Device':
        created_at = datetime.fromisoformat(data.get("created_at", datetime.now(timezone.utc).isoformat()))
        last_seen = datetime.fromisoformat(data.get("last_seen", datetime.now(timezone.utc).isoformat()))
        
        perms_raw = data.get("permissions", "")
        permissions = [p.strip() for p in perms_raw.split(",")] if perms_raw else []
        
        return cls(
            device_id=data["device_id"],
            device_name=data["device_name"],
            api_key=data["api_key"],
            device_fingerprint=data.get("device_fingerprint", ""),
            platform=data.get("platform", ""),
            client_version=data.get("client_version", ""),
            current_ip=data.get("current_ip", ""),
            is_approved=data.get("is_approved", False),
            created_at=created_at,
            last_seen=last_seen,
            hardware_id=data.get("hardware_id", ""),
            permissions=permissions
        )


class IPChangeLog:
    """Represents an IP change event."""
    
    def __init__(self, device_id: str, old_ip: str, new_ip: str, 
                 timestamp: datetime = None):
        self.device_id = device_id
        self.old_ip = old_ip
        self.new_ip = new_ip
        self.timestamp = timestamp or datetime.now(timezone.utc)
    
    def to_dict(self) -> Dict:
        return {
            "device_id": self.device_id,
            "old_ip": self.old_ip,
            "new_ip": self.new_ip,
            "timestamp": self.timestamp.isoformat()
        }


class DeviceManager:
    """Manages device registration, authentication, and permission tracking."""
    
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (constants.APP_DATA_PATH / "devices.db")
        self._lock = threading.RLock()
        self._init_database()
    
    def _init_database(self):
        """Init sqlite and apply column migrations."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY,
                    device_name TEXT NOT NULL,
                    api_key TEXT UNIQUE NOT NULL,
                    device_fingerprint TEXT,
                    platform TEXT,
                    client_version TEXT,
                    current_ip TEXT,
                    is_approved BOOLEAN DEFAULT FALSE,
                    created_at TEXT NOT NULL,
                    last_seen TEXT NOT NULL
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ip_change_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    old_ip TEXT NOT NULL,
                    new_ip TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY (device_id) REFERENCES devices(device_id)
                )
            """)
            
            conn.execute("CREATE INDEX IF NOT EXISTS idx_devices_api_key ON devices(api_key)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ip_change_device_id ON ip_change_log(device_id)")
            
            # migration: ensure hardware_id and permissions exist
            for col, col_type in [("hardware_id", "TEXT DEFAULT ''"), ("permissions", "TEXT DEFAULT ''")]:
                try:
                    conn.execute(f"ALTER TABLE devices ADD COLUMN {col} {col_type}")
                    log.info(f"Database migration: Added {col} column")
                except sqlite3.OperationalError:
                    pass 
            
            conn.commit()
    
    def register_device(self, device_id: str, device_name: str, 
                       device_fingerprint: str = "", platform: str = "",
                       client_version: str = "", current_ip: str = "",
                       hardware_id: str = "") -> Device:
        """Register a new device and assign the default permission set."""
        with self._lock:
            existing = self.get_device_by_id(device_id)
            if existing:
                existing.device_name = device_name
                existing.device_fingerprint = device_fingerprint
                existing.platform = platform
                existing.client_version = client_version
                existing.current_ip = current_ip
                existing.last_seen = datetime.now(timezone.utc)
                if hardware_id: existing.hardware_id = hardware_id
                self._save_device(existing)
                return existing
            
            from .config import config_manager
            defaults = config_manager.get("default_device_permissions", [])

            api_key = str(uuid.uuid4())
            device = Device(
                device_id=device_id,
                device_name=device_name,
                api_key=api_key,
                device_fingerprint=device_fingerprint,
                platform=platform,
                client_version=client_version,
                current_ip=current_ip,
                is_approved=False,
                hardware_id=hardware_id,
                permissions=defaults
            )
            
            self._save_device(device)
            log.info(f"Registered new device: {device_name}")
            return device
    
    def approve_device(self, device_id: str) -> bool:
        with self._lock:
            device = self.get_device_by_id(device_id)
            if not device: return False
            device.is_approved = True
            self._save_device(device)
            log.info(f"Approved device: {device.device_name}")
            self._trigger_update()
            return True
    
    def revoke_device(self, device_id: str) -> bool:
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("DELETE FROM devices WHERE device_id = ?", (device_id,))
                deleted = cursor.rowcount > 0
                conn.commit()
            if deleted:
                log.info(f"Revoked device: {device_id}")
                self._trigger_update()
            return deleted

    def _trigger_update(self):
        try:
            from .state import emit_device_list_updated
            emit_device_list_updated()
        except Exception: pass

    def update_device_last_seen(self, device_id: str) -> bool:
        with self._lock:
            device = self.get_device_by_id(device_id)
            if not device: return False
            device.last_seen = datetime.now(timezone.utc)
            self._save_device(device)
            return True
    
    def get_device_by_id(self, device_id: str) -> Optional[Device]:
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT * FROM devices WHERE device_id = ?", (device_id,))
                row = cursor.fetchone()
                return Device.from_dict(dict(row)) if row else None
    
    def get_device_by_api_key(self, api_key: str) -> Optional[Device]:
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT * FROM devices WHERE api_key = ?", (api_key,))
                row = cursor.fetchone()
                return Device.from_dict(dict(row)) if row else None
    
    def update_device_ip(self, device_id: str, new_ip: str) -> bool:
        with self._lock:
            device = self.get_device_by_id(device_id)
            if not device: return False
            if device.current_ip != new_ip:
                self._log_ip_change(device_id, device.current_ip, new_ip)
                device.current_ip = new_ip
                device.last_seen = datetime.now(timezone.utc)
                self._save_device(device)
                self._trigger_update()
            return True
    
    def get_all_devices(self) -> List[Device]:
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT * FROM devices ORDER BY last_seen DESC")
                return [Device.from_dict(dict(row)) for row in cursor.fetchall()]
    
    def get_approved_devices(self) -> List[Device]:
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT * FROM devices WHERE is_approved = 1 ORDER BY last_seen DESC")
                return [Device.from_dict(dict(row)) for row in cursor.fetchall()]
    
    def get_ip_change_history(self, device_id: str, limit: int = 50) -> List[IPChangeLog]:
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT * FROM ip_change_log WHERE device_id = ? ORDER BY timestamp DESC LIMIT ?", (device_id, limit))
                return [IPChangeLog(row["device_id"], row["old_ip"], row["new_ip"], datetime.fromisoformat(row["timestamp"])) for row in cursor.fetchall()]
    
    def cleanup_old_devices(self, days: int = 30) -> int:
        cutoff = datetime.now(timezone.utc).timestamp() - (days * 24 * 60 * 60)
        cutoff_iso = datetime.fromtimestamp(cutoff, timezone.utc).isoformat()
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("DELETE FROM devices WHERE last_seen < ?", (cutoff_iso,))
                deleted = cursor.rowcount
                conn.commit()
                if deleted > 0: log.info(f"Cleaned up {deleted} old device records")
                return deleted
    
    def _save_device(self, device: Device):
        data = device.to_dict()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO devices 
                (device_id, device_name, api_key, device_fingerprint, platform, 
                 client_version, current_ip, is_approved, created_at, last_seen, 
                 hardware_id, permissions)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data["device_id"], data["device_name"], data["api_key"],
                data["device_fingerprint"], data["platform"], data["client_version"],
                data["current_ip"], data["is_approved"], data["created_at"],
                data["last_seen"], data["hardware_id"], data["permissions"]
            ))
            conn.commit()
    
    def _log_ip_change(self, device_id: str, old_ip: str, new_ip: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO ip_change_log (device_id, old_ip, new_ip, timestamp)
                VALUES (?, ?, ?, ?)
            """, (device_id, old_ip, new_ip, datetime.now(timezone.utc).isoformat()))
            conn.commit()


device_manager = DeviceManager()