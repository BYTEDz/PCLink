# src/pclink/core/share_manager.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import gettext
import logging
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from . import constants

log = logging.getLogger(__name__)
_ = gettext.gettext


class ShareManager:
    """Manages secure, scoped share tokens for file downloads with WAL-optimized SQLite backend."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (constants.APP_DATA_PATH / "shares.db")
        self._lock = threading.RLock()
        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
        """Helper to create SQLite connections with WAL mode and row factory configured."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_database(self):
        """Initialize the shares database schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS shared_links (
                    token TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    device_id TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def create_share_link(
        self, path: str, device_id: str, expires_in: Optional[int] = None
    ) -> str:
        """Create a secure share token for a specific file."""
        token = secrets.token_urlsafe(32)
        created_at = datetime.now(timezone.utc)
        expires_at = (
            created_at + timedelta(seconds=expires_in)
            if expires_in is not None
            else None
        )

        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO shared_links (token, file_path, created_at, expires_at, device_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    token,
                    path,
                    created_at.isoformat(),
                    expires_at.isoformat() if expires_at else None,
                    device_id,
                ),
            )
            conn.commit()

        return token

    def validate_share_token(self, token: str, path: str) -> bool:
        """Validate a share token against requested path and expiration."""
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT file_path, expires_at FROM shared_links WHERE token = ?",
                (token,),
            )
            row = cursor.fetchone()

            if not row:
                return False

            # 1. Path must match exactly
            if row["file_path"] != path:
                return False

            # 2. Check expiration
            expires_at_str = row["expires_at"]
            if expires_at_str:
                expires_at = datetime.fromisoformat(expires_at_str)
                if datetime.now(timezone.utc) > expires_at:
                    self.revoke_share_link(token)
                    return False

            return True

    def revoke_share_link(self, token: str):
        """Revoke a specific share token."""
        with self._lock, self._get_connection() as conn:
            conn.execute("DELETE FROM shared_links WHERE token = ?", (token,))
            conn.commit()

    def revoke_all_for_device(self, device_id: str):
        """Revoke all share links created by a specific device."""
        with self._lock, self._get_connection() as conn:
            conn.execute("DELETE FROM shared_links WHERE device_id = ?", (device_id,))
            conn.commit()

    def list_shares_for_device(self, device_id: Optional[str] = None) -> List[dict]:
        """List active non-expired share links for a device, or all devices if None."""
        now = datetime.now(timezone.utc).isoformat()
        query = """
            SELECT token, file_path, created_at, expires_at, device_id
            FROM shared_links
            WHERE (expires_at IS NULL OR expires_at > ?)
        """
        params = [now]

        if device_id is not None:
            query += " AND device_id = ?"
            params.append(device_id)

        query += " ORDER BY created_at DESC"

        with self._lock, self._get_connection() as conn:
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]


# Global instance
share_manager = ShareManager()
