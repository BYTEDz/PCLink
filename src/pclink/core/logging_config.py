"""
PCLink - Remote PC Control Server - Logging Configuration
Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published
by the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import constants


def setup_logging(level=logging.INFO):
    """
    Configures application-wide logging to a file and optionally the console.
    This should be called once at application startup.
    """
    log_dir = Path(constants.APP_DATA_PATH)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "pclink.log"

    log_formatter = logging.Formatter(
        "%(asctime)s - %(name)-22s - %(levelname)-8s - %(message)s"
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # Always add a rotating file handler to save logs.
    try:
        file_handler = RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(log_formatter)
        root_logger.addHandler(file_handler)
    except Exception as e:
        # If file logging fails, log the error to the console as a last resort.
        logging.basicConfig()
        logging.error(f"Failed to configure file logger: {e}")

    # Add a console handler only for development builds (not frozen).
    # This prevents console-related issues in packaged applications.
    if not getattr(sys, "frozen", False):
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(log_formatter)
        root_logger.addHandler(console_handler)

    logging.info("=" * 50)
    logging.info("Logging configured. Log file located at: %s", log_file)
    logging.info("=" * 50)