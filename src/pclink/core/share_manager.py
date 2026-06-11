# src/pclink/core/share_manager.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import sqlite3
import secrets
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from . import constants


class ShareManager:
    """Manages secure, scoped share tokens for file downloads."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (constants.APP_DATA_PATH / "shares.db")
        self._lock = threading.RLock()
        self._init_database()

    def _init_database(self):
        """Initialize the shares database."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
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
        """
        Create a secure share token for a specific file.

        Args:
            path: The absolute path to the file.
            device_id: The ID of the device creating the link.
            expires_in: Expiration time in seconds. None for permanent.

        Returns:
            The generated share token.
        """
        token = secrets.token_urlsafe(32)
        created_at = datetime.now(timezone.utc)
        expires_at = None

        if expires_in is not None:
            expires_at = created_at + timedelta(seconds=expires_in)

        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
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
        """
        Validate a share token against a requested path and expiration.
        """
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "SELECT file_path, expires_at FROM shared_links WHERE token = ?",
                    (token,),
                )
                row = cursor.fetchone()

                if not row:
                    return False

                stored_path, expires_at_str = row

                # 1. Path must match exactly
                if stored_path != path:
                    return False

                # 2. Check expiration
                if expires_at_str:
                    expires_at = datetime.fromisoformat(expires_at_str)
                    if datetime.now(timezone.utc) > expires_at:
                        # Token expired, we could delete it here
                        self.revoke_share_link(token)
                        return False

                return True

    def revoke_share_link(self, token: str):
        """Revoke a specific share token."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM shared_links WHERE token = ?", (token,))
                conn.commit()

    def revoke_all_for_device(self, device_id: str):
        """Revoke all share links created by a specific device."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "DELETE FROM shared_links WHERE device_id = ?", (device_id,)
                )
                conn.commit()

    def list_shares_for_device(self, device_id: str) -> list[dict]:
        """List all active (non-expired) share links for a device."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    """
                    SELECT token, file_path, created_at, expires_at
                    FROM shared_links
                    WHERE device_id = ?
                      AND (expires_at IS NULL OR expires_at > ?)
                    ORDER BY created_at DESC
                    """,
                    (device_id, now),
                )
                return [dict(row) for row in cursor.fetchall()]


# Global instance
share_manager = ShareManager()
