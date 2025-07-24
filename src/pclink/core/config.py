"""
PCLink - Remote PC Control Server - Configuration Management
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

import json
import logging
from typing import Any, Dict, Optional

from PySide6.QtCore import QSettings

from . import constants
from .exceptions import ConfigurationError

log = logging.getLogger(__name__)

# Define which keys belong to which storage. This creates a single source of truth.
# QSettings is ideal for GUI state (window size, theme) that is user/machine-specific.
# The JSON file is better for server/core settings that might be shared or versioned.
QT_SETTING_KEYS = {
    "theme",
    "language",
    "minimize_to_tray",
    "window_geometry",
    "use_https",
    "allow_insecure_shell",
}


class ConfigManager:
    """
    Manages application settings, intelligently using QSettings for GUI state
    and a JSON file for core application configuration.
    """

    def __init__(self):
        self.config_file = constants.CONFIG_FILE
        self.qt_settings = QSettings(constants.APP_NAME, "AppGUI")
        self._json_cache: Dict[str, Any] = {}
        self._load_from_file()

    def _load_from_file(self):
        """Loads configuration from the JSON file into the cache."""
        try:
            if self.config_file.exists():
                with self.config_file.open("r", encoding="utf-8") as f:
                    self._json_cache = json.load(f)
                log.info(f"Configuration loaded from {self.config_file}")
            else:
                self._json_cache = {}
                log.info("No config file found, using default values.")
        except (IOError, json.JSONDecodeError) as e:
            log.error(f"Failed to load config file, using defaults instead: {e}")
            self._json_cache = {}

    def _save_to_file(self):
        """Saves the configuration cache to the JSON file."""
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with self.config_file.open("w", encoding="utf-8") as f:
                json.dump(self._json_cache, f, indent=4)
            log.debug("Configuration saved to file.")
        except IOError as e:
            log.error(f"Failed to save config file: {e}")
            raise ConfigurationError(f"Cannot save configuration: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """
        Gets a configuration value from the appropriate store (QSettings or JSON).
        """
        if key in QT_SETTING_KEYS:
            # For QSettings, the second argument to value() is the default.
            return self.qt_settings.value(key, default)
        return self._json_cache.get(key, default)

    def set(self, key: str, value: Any):
        """
        Sets a configuration value in the appropriate store.
        """
        try:
            if key in QT_SETTING_KEYS:
                self.qt_settings.setValue(key, value)
                log.debug(f"GUI setting '{key}' set in QSettings.")
            else:
                self._json_cache[key] = value
                self._save_to_file()
                log.debug(f"Core setting '{key}' set in config file.")
        except Exception as e:
            log.error(f"Error setting config key '{key}': {e}")
            raise ConfigurationError(f"Cannot set configuration: {e}")

    def reset_to_defaults(self):
        """Resets all configurations to their default states."""
        try:
            self._json_cache.clear()
            self._save_to_file()
            self.qt_settings.clear()
            log.info("Configuration has been reset to defaults.")
        except Exception as e:
            log.error(f"Failed to reset configuration: {e}")
            raise ConfigurationError(f"Cannot reset configuration: {e}")


# Global singleton instance for easy access across the application.
config_manager = ConfigManager()
