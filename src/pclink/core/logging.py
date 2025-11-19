# src/pclink/core/logging.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

"""
PCLink Logging Configuration
Configures application-wide logging with spam filtering and file rotation
"""

import logging
import sys
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import constants


class CleanConsoleHandler(logging.StreamHandler):
    """
    Console handler that filters out repetitive HTTP requests and other spam
    """
    
    def __init__(self, stream=None):
        super().__init__(stream)
        self.last_message = None
        self.repeat_count = 0
        
        self.spam_patterns = [
            r'GET /status HTTP/1\.1.*200 OK',
            r'GET /ping HTTP/1\.1.*200 OK', 
            r'GET /qr-payload HTTP/1\.1.*200 OK',
            r'connection (open|closed)'
        ]
        self.compiled_patterns = [re.compile(pattern) for pattern in self.spam_patterns]
    
    def emit(self, record):
        """Override emit to filter spam messages"""
        try:
            msg = self.format(record)
            
            for pattern in self.compiled_patterns:
                if pattern.search(msg):
                    return
            
            if msg == self.last_message:
                self.repeat_count += 1
                return
            else:
                if self.repeat_count > 0:
                    print(f"  (previous message repeated {self.repeat_count} times)")
                    self.repeat_count = 0
                
                super().emit(record)
                self.last_message = msg
                
        except Exception:
            self.handleError(record)


def setup_logging(level=logging.INFO):
    """
    Configures application-wide logging with reduced console spam.
    """
    log_dir = Path(constants.APP_DATA_PATH)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "pclink.log"

    file_formatter = logging.Formatter(
        "%(asctime)s - %(name)-22s - %(levelname)-8s - %(message)s"
    )
    
    console_formatter = logging.Formatter(
        "%(asctime)s - %(levelname)-8s - %(message)s",
        datefmt="%H:%M:%S"
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    try:
        file_handler = RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
    except Exception as e:
        logging.basicConfig()
        logging.error(f"Failed to configure file logger: {e}")

    if not getattr(sys, "frozen", False):
        console_handler = CleanConsoleHandler(sys.stdout)
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)

    is_frozen = getattr(sys, "frozen", False)
    if is_frozen:
        logging.getLogger("uvicorn").setLevel(logging.ERROR)
        logging.getLogger("uvicorn.access").setLevel(logging.ERROR)
        logging.getLogger("uvicorn.error").setLevel(logging.ERROR)
        logging.getLogger("fastapi").setLevel(logging.ERROR)
    else:
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    
    if not is_frozen:
        print(f"🚀 PCLink Logging Initialized")
        print(f"📁 Log file: {log_file}")
    
    logging.info("=" * 50)
    logging.info("Logging configured. Log file located at: %s", log_file)
    logging.info("=" * 50)