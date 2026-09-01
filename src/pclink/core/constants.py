# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import os
import sys
from pathlib import Path

from .version import __app_name__


def get_app_data_path(app_name: str) -> Path:
    """
    Returns the platform-specific application data directory path.
    Does not create the directory.
    """
    if sys.platform == "win32":
        path = Path(os.environ["APPDATA"]) / app_name
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / app_name
    else:
        path = Path.home() / ".config" / app_name
    return path


# --- Application Metadata ---
APP_NAME = __app_name__
APP_AUMID = "BYTEDz.PCLink"

# --- Core Application Settings ---
DEFAULT_PORT = 38080
CONTROL_PORT = 9876
DEVICE_TIMEOUT = 300

# --- File Names ---
CONFIG_FILENAME = "config.json"
MACROS_FILENAME = "macros.json"
CERT_FILENAME = "cert.pem"
KEY_FILENAME = "key.pem"

# --- Application Paths ---
APP_DATA_PATH = get_app_data_path(APP_NAME)
WEB_CACHE_PATH = APP_DATA_PATH / "web_cache"

# Full paths to configuration and data files.
CERT_FILE = APP_DATA_PATH / CERT_FILENAME
KEY_FILE = APP_DATA_PATH / KEY_FILENAME
CONFIG_FILE = APP_DATA_PATH / CONFIG_FILENAME
MACROS_FILE = APP_DATA_PATH / MACROS_FILENAME
ASSETS_PATH = Path(__file__).parent.parent / "assets"

# --- Transfer Paths ---
TRANSFERS_PATH = APP_DATA_PATH / "transfers"
UPLOADS_PATH = TRANSFERS_PATH / "uploads"
DOWNLOADS_PATH = TRANSFERS_PATH / "downloads"

# --- Platform-Specific Paths ---
AUTOSTART_PATH = None
DESKTOP_FILE_PATH = None

if sys.platform == "linux":
    AUTOSTART_PATH = Path.home() / ".config" / "autostart"
    DESKTOP_FILE_PATH = AUTOSTART_PATH / f"{APP_NAME.lower()}.desktop"


def initialize_app_directories():
    """Creates required application directories on disk."""
    APP_DATA_PATH.mkdir(parents=True, exist_ok=True)
    WEB_CACHE_PATH.mkdir(parents=True, exist_ok=True)
    UPLOADS_PATH.mkdir(parents=True, exist_ok=True)
    DOWNLOADS_PATH.mkdir(parents=True, exist_ok=True)
    if AUTOSTART_PATH:
        AUTOSTART_PATH.mkdir(parents=True, exist_ok=True)
