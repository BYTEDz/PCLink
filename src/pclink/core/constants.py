# filename: src/pclink/core/constants.py
"""
PCLink - Remote PC Control Server - Constants Module
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

import sys
from pathlib import Path

from .utils import get_app_data_path
from .version import __app_name__

# --- Application Metadata ---
APP_NAME = __app_name__

# --- Core Application Settings ---
DEFAULT_PORT = 8000
DEVICE_TIMEOUT = 300  # in seconds

# --- File Names ---
CONFIG_FILENAME = "config.json"
API_KEY_FILENAME = ".env"
PORT_FILENAME = ".port"
CERT_FILENAME = "cert.pem"
KEY_FILENAME = "key.pem"

# --- Application Paths ---
# Base directory for all application data, configurations, and certificates.
APP_DATA_PATH = get_app_data_path(APP_NAME)

# Full paths to configuration and data files.
API_KEY_FILE = APP_DATA_PATH / API_KEY_FILENAME
PORT_FILE = APP_DATA_PATH / PORT_FILENAME
CERT_FILE = APP_DATA_PATH / CERT_FILENAME
KEY_FILE = APP_DATA_PATH / KEY_FILENAME
CONFIG_FILE = APP_DATA_PATH / CONFIG_FILENAME

# --- Platform-Specific Paths ---
# These paths are used for platform-specific integrations like autostart.
AUTOSTART_PATH = None
DESKTOP_FILE_PATH = None

if sys.platform == "linux":
    AUTOSTART_PATH = Path.home() / ".config" / "autostart"
    DESKTOP_FILE_PATH = AUTOSTART_PATH / f"{APP_NAME.lower()}.desktop"
# NOTE: Add other platforms like 'win32' or 'darwin' here as needed.


def initialize_app_directories():
    """
    Creates required application directories.
    This function should be called once at the application's entry point
    to ensure all necessary folders exist before they are accessed.
    """
    APP_DATA_PATH.mkdir(parents=True, exist_ok=True)
    if AUTOSTART_PATH:
        AUTOSTART_PATH.mkdir(parents=True, exist_ok=True)