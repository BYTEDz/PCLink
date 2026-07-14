# src/pclink/core/logging.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

"""
PCLink Logging Configuration
Configures application-wide logging with message deduplication and file rotation.
"""

import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import constants

# Localization catalog for application logging messages
_STRINGS = {
    "prev_repeated": "  (previous message repeated {count} times)",
    "log_init": "[+] PCLink Logging Initialized",
    "log_file_loc": "[-] Log file: {path}",
    "fail_file_logger": "Failed to configure file logger: {error}",
    "log_separator": "=" * 50,
    "log_configured": "Logging configured. Log file located at: {path}",
}


def _(key: str, **kwargs) -> str:
    """Retrieves and formats a localized string from the logging catalog."""
    return _STRINGS.get(key, key).format(**kwargs)


def _safe_print(msg: str) -> None:
    """Prints text to stdout, ignoring errors if stdout is unavailable or closed."""
    if sys.stdout is None or not hasattr(sys.stdout, "write"):
        return
    try:
        print(msg)
    except Exception:
        pass


class CleanConsoleHandler(logging.StreamHandler):
    """
    Console handler that filters redundant HTTP requests and repeated log entries.
    Deduplicates identical consecutive log entries to prevent console flooding.
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
        """Processes and writes log records, filtering repetitive entries."""
        try:
            msg = self.format(record)

            # Drop logs matching the defined filter patterns
            for pattern in self.filter_patterns:
                if pattern.search(msg):
                    return

            # Check for consecutive identical entries
            if msg == self.last_message:
                self.repeat_count += 1
                return

            # Output the repetition count before emitting the new log record
            if self.repeat_count > 0:
                repeat_msg = (
                    _("prev_repeated", count=self.repeat_count) + self.terminator
                )
                self.stream.write(repeat_msg)
                self.flush()
                self.repeat_count = 0

            self.last_message = msg
            super().emit(record)

        except Exception:
            self.handleError(record)

    def close(self):
        """Flushes any remaining repetition counts upon handler closure."""
        try:
            self.acquire()
            if self.repeat_count > 0:
                try:
                    repeat_msg = (
                        _("prev_repeated", count=self.repeat_count) + self.terminator
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
    """
    Configures application-wide logging with reduced console logging.
    """
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

    # Configure rotating file logging
    try:
        file_handler = RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
    except Exception as e:
        err_msg = _("fail_file_logger", error=e)
        if sys.stderr and hasattr(sys.stderr, "write"):
            sys.stderr.write(f"ERROR: {err_msg}\n")

    # Add console logging if a functional output stream is active
    show_console = sys.stdout is not None and hasattr(sys.stdout, "write")
    if show_console:
        console_handler = CleanConsoleHandler(sys.stdout)
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)

    # Configure third-party log levels dynamically
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
        _safe_print(_("log_init"))
        _safe_print(_("log_file_loc", path=log_file))

    logging.info(_("log_separator"))
    logging.info(_("log_configured", path=log_file))
    logging.info(_("log_separator"))
