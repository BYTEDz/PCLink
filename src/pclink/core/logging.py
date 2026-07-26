# src/pclink/core/logging.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

"""
PCLink Logging Configuration
Configures application-wide logging with structured ring-buffer caching,
sensitive data redaction, deduplication, and file rotation.
"""

import gettext
import logging
import re
import sys
import time
from collections import deque
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional

from . import constants

_ = gettext.gettext


def _safe_print(msg: str) -> None:
    if sys.stdout is None or not hasattr(sys.stdout, "write"):
        return
    try:
        print(msg)
    except Exception:
        pass


class SensitiveDataFilter(logging.Filter):
    """
    Filter that redacts sensitive keywords (tokens, passwords, keys)
    from log records before emission.
    """

    PATTERNS = [
        (
            re.compile(r"(password[\"']?\s*[:=]\s*[\"']?)[^\s\"'&]+", re.IGNORECASE),
            r"\1***REDACTED***",
        ),
        (
            re.compile(r"(token[\"']?\s*[:=]\s*[\"']?)[^\s\"'&]+", re.IGNORECASE),
            r"\1***REDACTED***",
        ),
        (
            re.compile(r"(api_key[\"']?\s*[:=]\s*[\"']?)[^\s\"'&]+", re.IGNORECASE),
            r"\1***REDACTED***",
        ),
        (
            re.compile(r"(X-API-Key\s*[:=]\s*)[^\s\"'&]+", re.IGNORECASE),
            r"\1***REDACTED***",
        ),
        (
            re.compile(r"(Bearer\s+)[a-zA-Z0-9\-\._~\+\/]+=*", re.IGNORECASE),
            r"\1***REDACTED***",
        ),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            for pattern, repl in self.PATTERNS:
                record.msg = pattern.sub(repl, record.msg)
        return True


class MemoryLogHandler(logging.Handler):
    """
    In-memory thread-safe circular log buffer for high-performance API queries.
    Avoids reading disk files repeatedly.
    """

    def __init__(self, capacity: int = 1000):
        super().__init__()
        self.capacity = capacity
        self.buffer: deque = deque(maxlen=capacity)
        self.lock = RLock()

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            entry = {
                "timestamp": record.created,
                "time_str": time.strftime("%H:%M:%S", time.localtime(record.created)),
                "level": record.levelname,
                "level_no": record.levelno,
                "logger": record.name,
                "message": msg,
            }
            with self.lock:
                self.buffer.append(entry)
        except Exception:
            self.handleError(record)

    def get_logs(
        self,
        level: Optional[str] = None,
        min_level: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        target_level = level.upper() if level else None
        level_num = getattr(logging, min_level.upper(), 0) if min_level else 0
        search_lower = search.lower() if search else None

        results = []
        with self.lock:
            for entry in reversed(self.buffer):
                if target_level and entry["level"].upper() != target_level:
                    continue
                if level_num and entry["level_no"] < level_num:
                    continue
                if search_lower and search_lower not in entry["message"].lower():
                    continue
                results.append(entry)
                if len(results) >= limit:
                    break

        results.reverse()
        return results


memory_log_handler = MemoryLogHandler(capacity=1000)


class CleanConsoleHandler(logging.StreamHandler):
    """
    Console handler that filters redundant HTTP requests and repeated log entries.
    """

    def __init__(self, stream=None):
        super().__init__(stream)
        self.last_message = None
        self.repeat_count = 0

        self.filter_patterns = [
            re.compile(r"GET /status HTTP/1\.1.*200 OK"),
            re.compile(r"GET /ping HTTP/1\.1.*200 OK"),
            re.compile(r"GET /qr-payload HTTP/1\.1.*200 OK"),
            re.compile(r"connection (open|closed)"),
        ]

    def emit(self, record):
        try:
            msg = self.format(record)

            for pattern in self.filter_patterns:
                if pattern.search(msg):
                    return

            if msg == self.last_message:
                self.repeat_count += 1
                return

            if self.repeat_count > 0:
                repeat_msg = (
                    _("  (previous message repeated {count} times)").format(
                        count=self.repeat_count
                    )
                    + self.terminator
                )
                self.stream.write(repeat_msg)
                self.flush()
                self.repeat_count = 0

            self.last_message = msg
            super().emit(record)

        except Exception:
            self.handleError(record)

    def close(self):
        try:
            self.acquire()
            if self.repeat_count > 0:
                try:
                    repeat_msg = (
                        _("  (previous message repeated {count} times)").format(
                            count=self.repeat_count
                        )
                        + self.terminator
                    )
                    self.stream.write(repeat_msg)
                    self.flush()
                except Exception:
                    pass
                self.repeat_count = 0
            super().close()
        finally:
            self.release()


def setup_logging(level=logging.INFO):
    log_dir = Path(constants.APP_DATA_PATH)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "pclink.log"

    file_formatter = logging.Formatter(
        "%(asctime)s - %(name)-22s - %(levelname)-8s - %(message)s"
    )

    console_formatter = logging.Formatter(
        "%(asctime)s - %(levelname)-8s - %(message)s", datefmt="%H:%M:%S"
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    sensitive_filter = SensitiveDataFilter()

    memory_log_handler.setFormatter(file_formatter)
    memory_log_handler.addFilter(sensitive_filter)
    root_logger.addHandler(memory_log_handler)

    try:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
            delay=True,
        )
        file_handler.setFormatter(file_formatter)
        file_handler.addFilter(sensitive_filter)
        root_logger.addHandler(file_handler)
    except Exception as e:
        err_msg = _("Failed to configure file logger: {error}").format(error=e)
        if sys.stderr and hasattr(sys.stderr, "write"):
            sys.stderr.write(f"ERROR: {err_msg}\n")

    show_console = sys.stdout is not None and hasattr(sys.stdout, "write")
    if show_console:
        console_handler = CleanConsoleHandler(sys.stdout)
        console_handler.setFormatter(console_formatter)
        console_handler.addFilter(sensitive_filter)
        root_logger.addHandler(console_handler)

    is_frozen = getattr(sys, "frozen", False)
    if level == logging.DEBUG:
        logging.getLogger("uvicorn.access").setLevel(logging.INFO)
        logging.getLogger("uvicorn.error").setLevel(logging.DEBUG)
        logging.getLogger("asyncio").setLevel(logging.WARNING)
    elif is_frozen:
        logging.getLogger("uvicorn").setLevel(logging.ERROR)
        logging.getLogger("uvicorn.access").setLevel(logging.ERROR)
        logging.getLogger("uvicorn.error").setLevel(logging.ERROR)
        logging.getLogger("fastapi").setLevel(logging.ERROR)
        logging.getLogger("asyncio").setLevel(logging.CRITICAL)
    else:
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        logging.getLogger("uvicorn.error").setLevel(logging.INFO)
        logging.getLogger("asyncio").setLevel(logging.CRITICAL)

    if show_console and not is_frozen:
        _safe_print(_("[+] PCLink Logging Initialized"))
        _safe_print(_("[-] Log file: {path}").format(path=log_file))

    log_separator = "=" * 50
    logging.info(log_separator)
    logging.info(
        _("Logging configured. Log file located at: {path}").format(path=log_file)
    )
    logging.info(log_separator)
