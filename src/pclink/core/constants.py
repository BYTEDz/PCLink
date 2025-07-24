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

# --- Application Constants ---
APP_NAME = __app_name__
DEFAULT_PORT = 8000
DEVICE_TIMEOUT = 300
CONFIG_FILENAME = "config.json"

# --- Static File Paths ---
# Use the utility to get the base data path.
APP_DATA_PATH = get_app_data_path(APP_NAME)
APP_DATA_PATH.mkdir(parents=True, exist_ok=True)

API_KEY_FILE = APP_DATA_PATH / ".env"
PORT_FILE = APP_DATA_PATH / ".port"
CERT_FILE = APP_DATA_PATH / "cert.pem"
KEY_FILE = APP_DATA_PATH / "key.pem"
CONFIG_FILE = APP_DATA_PATH / CONFIG_FILENAME

# --- Platform-Specific Paths ---
if sys.platform == "linux":
    AUTOSTART_PATH = Path.home() / ".config" / "autostart"
    DESKTOP_FILE_PATH = AUTOSTART_PATH / f"{APP_NAME.lower()}.desktop"
