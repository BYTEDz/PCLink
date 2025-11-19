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
    """Represents a paired device"""
    
    def __init__(self, device_id: str, device_name: str, api_key: str, 
                 device_fingerprint: str = "", platform: str = "", 
                 client_version: str = "", current_ip: str = "", 
                 is_approved: bool = False, created_at: datetime = None,
                 last_seen: datetime = None):
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
    
    def to_dict(self) -> Dict:
        """Convert device to dictionary"""
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
            "last_seen": self.last_seen.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Device':
        """Create device from dictionary"""
        created_at = datetime.fromisoformat(data.get("created_at", datetime.now(timezone.utc).isoformat()))
        last_seen = datetime.fromisoformat(data.get("last_seen", datetime.now(timezone.utc).isoformat()))
        
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
            last_seen=last_seen
        )


class IPChangeLog:
    """Represents an IP change event"""
    
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
    """Manages device registration, authentication, and IP tracking"""
    
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (constants.APP_DATA_PATH / "devices.db")
        self._lock = threading.RLock()
        self._init_database()
    
    def _init_database(self):
        """Initialize SQLite database"""
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
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_devices_api_key ON devices(api_key)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ip_change_device_id ON ip_change_log(device_id)
            """)
            
            conn.commit()
    
    def register_device(self, device_id: str, device_name: str, 
                       device_fingerprint: str = "", platform: str = "",
                       client_version: str = "", current_ip: str = "") -> Device:
        """Register a new device (pending approval)"""
        with self._lock:
            # Check if device already exists
            existing = self.get_device_by_id(device_id)
            if existing:
                # Update existing device info
                existing.device_name = device_name
                existing.device_fingerprint = device_fingerprint
                existing.platform = platform
                existing.client_version = client_version
                existing.current_ip = current_ip
                existing.last_seen = datetime.now(timezone.utc)
                self._save_device(existing)
                return existing
            
            # Create new device
            api_key = str(uuid.uuid4())
            device = Device(
                device_id=device_id,
                device_name=device_name,
                api_key=api_key,
                device_fingerprint=device_fingerprint,
                platform=platform,
                client_version=client_version,
                current_ip=current_ip,
                is_approved=False
            )
            
            self._save_device(device)
            log.info(f"Registered new device: {device_name} ({device_id[:8]}...)")
            return device
    
    def approve_device(self, device_id: str) -> bool:
        """Approve a device for access"""
        with self._lock:
            device = self.get_device_by_id(device_id)
            if not device:
                return False
            
            device.is_approved = True
            self._save_device(device)
            log.info(f"Approved device: {device.device_name} ({device_id[:8]}...)")
            
            # Emit signal to update GUI
            try:
                from .state import emit_device_list_updated
                emit_device_list_updated()
            except Exception as e:
                log.warning(f"Failed to emit device list update signal: {e}")
            
            return True
    
    def revoke_device(self, device_id: str) -> bool:
        """Revoke device access"""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("DELETE FROM devices WHERE device_id = ?", (device_id,))
                deleted = cursor.rowcount > 0
                conn.commit()
            
            if deleted:
                log.info(f"Revoked device: {device_id[:8]}...")
                
                # Emit signal to update GUI
                try:
                    from .state import emit_device_list_updated
                    emit_device_list_updated()
                except Exception as e:
                    log.warning(f"Failed to emit device list update signal: {e}")
            
            return deleted
    
    def update_device_last_seen(self, device_id: str) -> bool:
        """Update device last seen timestamp"""
        with self._lock:
            device = self.get_device_by_id(device_id)
            if not device:
                return False
            
            device.last_seen = datetime.now(timezone.utc)
            self._save_device(device)
            return True
    
    def get_device_by_id(self, device_id: str) -> Optional[Device]:
        """Get device by device ID"""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT * FROM devices WHERE device_id = ?", (device_id,))
                row = cursor.fetchone()
                
                if row:
                    return Device.from_dict(dict(row))
                return None
    
    def get_device_by_api_key(self, api_key: str) -> Optional[Device]:
        """Get device by API key"""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT * FROM devices WHERE api_key = ?", (api_key,))
                row = cursor.fetchone()
                
                if row:
                    return Device.from_dict(dict(row))
                return None
    
    def update_device_ip(self, device_id: str, new_ip: str) -> bool:
        """Update device IP and log the change"""
        with self._lock:
            device = self.get_device_by_id(device_id)
            if not device:
                return False
            
            old_ip = device.current_ip
            if old_ip != new_ip:
                # Log IP change
                self._log_ip_change(device_id, old_ip, new_ip)
                log.info(f"IP change for {device.device_name}: {old_ip} -> {new_ip}")
            
            # Update device
            device.current_ip = new_ip
            device.last_seen = datetime.now(timezone.utc)
            self._save_device(device)
            
            # Emit signal to update GUI
            try:
                from .state import emit_device_list_updated
                emit_device_list_updated()
            except Exception as e:
                log.warning(f"Failed to emit device list update signal: {e}")
            
            return True
    
    def get_all_devices(self) -> List[Device]:
        """Get all registered devices"""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT * FROM devices ORDER BY last_seen DESC")
                rows = cursor.fetchall()
                
                return [Device.from_dict(dict(row)) for row in rows]
    
    def get_approved_devices(self) -> List[Device]:
        """Get all approved devices"""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT * FROM devices WHERE is_approved = 1 ORDER BY last_seen DESC")
                rows = cursor.fetchall()
                
                return [Device.from_dict(dict(row)) for row in rows]
    
    def get_ip_change_history(self, device_id: str, limit: int = 50) -> List[IPChangeLog]:
        """Get IP change history for a device"""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT * FROM ip_change_log 
                    WHERE device_id = ? 
                    ORDER BY timestamp DESC 
                    LIMIT ?
                """, (device_id, limit))
                rows = cursor.fetchall()
                
                changes = []
                for row in rows:
                    changes.append(IPChangeLog(
                        device_id=row["device_id"],
                        old_ip=row["old_ip"],
                        new_ip=row["new_ip"],
                        timestamp=datetime.fromisoformat(row["timestamp"])
                    ))
                return changes
    
    def cleanup_old_devices(self, days: int = 30) -> int:
        """Remove devices not seen for specified days"""
        cutoff = datetime.now(timezone.utc).timestamp() - (days * 24 * 60 * 60)
        cutoff_iso = datetime.fromtimestamp(cutoff, timezone.utc).isoformat()
        
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("DELETE FROM devices WHERE last_seen < ?", (cutoff_iso,))
                deleted = cursor.rowcount
                conn.commit()
                
                if deleted > 0:
                    log.info(f"Cleaned up {deleted} old devices")
                return deleted
    
    def _save_device(self, device: Device):
        """Save device to database"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO devices 
                (device_id, device_name, api_key, device_fingerprint, platform, 
                 client_version, current_ip, is_approved, created_at, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                device.device_id, device.device_name, device.api_key,
                device.device_fingerprint, device.platform, device.client_version,
                device.current_ip, device.is_approved,
                device.created_at.isoformat(), device.last_seen.isoformat()
            ))
            conn.commit()
    
    def _log_ip_change(self, device_id: str, old_ip: str, new_ip: str):
        """Log IP change to database"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO ip_change_log (device_id, old_ip, new_ip, timestamp)
                VALUES (?, ?, ?, ?)
            """, (device_id, old_ip, new_ip, datetime.now(timezone.utc).isoformat()))
            conn.commit()


# Global device manager instance
device_manager = DeviceManager()