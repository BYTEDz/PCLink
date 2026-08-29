# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import constants

log = logging.getLogger(__name__)


class ExtensionDatabase:
    """Manages persistent extension lifecycle state, granted capabilities, and quarantine status."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (constants.APP_DATA_PATH / "extensions.db")
        self._lock = threading.RLock()
        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_database(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS extension_state (
                    extension_id TEXT PRIMARY KEY,
                    enabled BOOLEAN NOT NULL DEFAULT 1,
                    granted_permissions TEXT NOT NULL DEFAULT '',
                    quarantined BOOLEAN NOT NULL DEFAULT 0,
                    quarantine_reason TEXT,
                    crash_count INTEGER NOT NULL DEFAULT 0,
                    last_crash_timestamp REAL,
                    installed_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS extension_crash_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    extension_id TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    exit_code INTEGER,
                    error_summary TEXT,
                    FOREIGN KEY (extension_id) REFERENCES extension_state(extension_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ext_crash_id ON extension_crash_log(extension_id)"
            )
            conn.commit()

    def get_state(self, extension_id: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM extension_state WHERE extension_id = ?",
                (extension_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            data = dict(row)
            data["enabled"] = bool(data["enabled"])
            data["quarantined"] = bool(data["quarantined"])
            raw_perms = data.get("granted_permissions", "")
            data["granted_permissions"] = (
                [p.strip() for p in raw_perms.split(",") if p.strip()]
                if raw_perms
                else []
            )
            return data

    def get_all_states(self) -> Dict[str, Dict[str, Any]]:
        states: Dict[str, Dict[str, Any]] = {}
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM extension_state")
            for row in cursor.fetchall():
                data = dict(row)
                data["enabled"] = bool(data["enabled"])
                data["quarantined"] = bool(data["quarantined"])
                raw_perms = data.get("granted_permissions", "")
                data["granted_permissions"] = (
                    [p.strip() for p in raw_perms.split(",") if p.strip()]
                    if raw_perms
                    else []
                )
                states[data["extension_id"]] = data
        return states

    def register_extension(
        self,
        extension_id: str,
        enabled: bool = True,
        granted_permissions: Optional[List[str]] = None,
        quarantined: bool = False,
        quarantine_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = time.time()
        perms_str = ",".join(
            [p.strip() for p in (granted_permissions or []) if p.strip()]
        )

        with self._lock, self._get_connection() as conn:
            existing = self.get_state(extension_id)
            if existing:
                conn.execute(
                    """
                    UPDATE extension_state
                    SET updated_at = ?
                    WHERE extension_id = ?
                    """,
                    (now, extension_id),
                )
                conn.commit()
                return self.get_state(extension_id)  # type: ignore[return-value]

            conn.execute(
                """
                INSERT INTO extension_state
                (extension_id, enabled, granted_permissions, quarantined, quarantine_reason,
                 crash_count, last_crash_timestamp, installed_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 0, NULL, ?, ?)
                """,
                (
                    extension_id,
                    int(enabled),
                    perms_str,
                    int(quarantined),
                    quarantine_reason,
                    now,
                    now,
                ),
            )
            conn.commit()

        return self.get_state(extension_id)  # type: ignore[return-value]

    def set_enabled(self, extension_id: str, enabled: bool) -> bool:
        now = time.time()
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE extension_state
                SET enabled = ?, updated_at = ?
                WHERE extension_id = ?
                """,
                (int(enabled), now, extension_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def set_quarantined(
        self,
        extension_id: str,
        quarantined: bool,
        reason: Optional[str] = None,
    ) -> bool:
        now = time.time()
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE extension_state
                SET quarantined = ?, quarantine_reason = ?, updated_at = ?
                WHERE extension_id = ?
                """,
                (int(quarantined), reason, now, extension_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def set_granted_permissions(
        self, extension_id: str, permissions: List[str]
    ) -> bool:
        now = time.time()
        perms_str = ",".join([p.strip() for p in permissions if p.strip()])
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE extension_state
                SET granted_permissions = ?, updated_at = ?
                WHERE extension_id = ?
                """,
                (perms_str, now, extension_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def record_crash(
        self,
        extension_id: str,
        exit_code: Optional[int] = None,
        error_summary: Optional[str] = None,
    ) -> int:
        now = time.time()
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO extension_crash_log
                (extension_id, timestamp, exit_code, error_summary)
                VALUES (?, ?, ?, ?)
                """,
                (extension_id, now, exit_code, error_summary),
            )
            conn.execute(
                """
                UPDATE extension_state
                SET crash_count = crash_count + 1,
                    last_crash_timestamp = ?,
                    updated_at = ?
                WHERE extension_id = ?
                """,
                (now, now, extension_id),
            )
            cursor = conn.execute(
                "SELECT crash_count FROM extension_state WHERE extension_id = ?",
                (extension_id,),
            )
            row = cursor.fetchone()
            conn.commit()
            return int(row["crash_count"]) if row else 1

    def reset_crashes(self, extension_id: str) -> bool:
        now = time.time()
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE extension_state
                SET crash_count = 0, last_crash_timestamp = NULL, updated_at = ?
                WHERE extension_id = ?
                """,
                (now, extension_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_state(self, extension_id: str) -> bool:
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM extension_state WHERE extension_id = ?",
                (extension_id,),
            )
            conn.execute(
                "DELETE FROM extension_crash_log WHERE extension_id = ?",
                (extension_id,),
            )
            conn.commit()
            return cursor.rowcount > 0


extension_db = ExtensionDatabase()
