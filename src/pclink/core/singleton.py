# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)


class PCLinkSingleton:
    """
    Ensures that only one instance of PCLink is running on the system.
    Uses a named mutex on Windows and a file lock on Unix-like systems.
    """
    _instance = None
    _lock_file_handle = None
    _mutex_handle = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def acquire_lock(self) -> bool:
        """
        Acquires a system-wide lock. Returns True if successful, False otherwise.
        """
        try:
            if sys.platform == "win32":
                return self._acquire_windows_lock()
            else:
                return self._acquire_unix_lock()
        except Exception as e:
            log.warning(f"Failed to acquire system lock due to an unexpected error: {e}")
            return False

    def _acquire_windows_lock(self) -> bool:
        """Acquires a lock using a named mutex on Windows."""
        import ctypes
        kernel32 = ctypes.windll.kernel32
        mutex_name = "Global\\PCLink_SingleInstance_Mutex"
        
        self._mutex_handle = kernel32.CreateMutexW(None, True, mutex_name)
        
        if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(self._mutex_handle)
            self._mutex_handle = None
            log.warning("Another PCLink instance is already running (mutex exists).")
            return False
        
        log.info("Acquired system-wide mutex lock successfully.")
        return True

    def _acquire_unix_lock(self) -> bool:
        """Acquires a lock using a file lock on Unix-like systems."""
        import fcntl
        import tempfile
        import os

        lock_file_path = Path(tempfile.gettempdir()) / "pclink.lock"
        try:
            self._lock_file_handle = open(lock_file_path, 'w')
            fcntl.flock(self._lock_file_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._lock_file_handle.write(str(os.getpid()))
            self._lock_file_handle.flush()
            log.info(f"Acquired file lock successfully: {lock_file_path}")
            return True
        except (IOError, BlockingIOError):
            if self._lock_file_handle:
                self._lock_file_handle.close()
                self._lock_file_handle = None
            log.warning("Another PCLink instance is already running (file locked).")
            return False

    def release_lock(self):
        """Releases the acquired system-wide lock."""
        try:
            if sys.platform == "win32":
                if self._mutex_handle:
                    import ctypes
                    kernel32 = ctypes.windll.kernel32
                    kernel32.ReleaseMutex(self._mutex_handle)
                    kernel32.CloseHandle(self._mutex_handle)
                    self._mutex_handle = None
                    log.info("Released system-wide mutex lock.")
            else:
                if self._lock_file_handle:
                    self._lock_file_handle.close()
                    self._lock_file_handle = None
                    log.info("Released file lock.")
        except Exception as e:
            log.warning(f"Failed to release system lock: {e}")