# filename: src/pclink/core/config.py
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
from typing import Any, Dict

from PySide6.QtCore import QSettings

from . import constants
from .exceptions import ConfigurationError

log = logging.getLogger(__name__)

# --- Default Configuration Values ---
# Central source of truth for all application settings and their defaults.

DEFAULT_GUI_SETTINGS = {
    "theme": "dark",
    "language": "en",
    "minimize_to_tray": True,
    "window_geometry": None,  # Let Qt handle initial window size/position
    "check_updates_on_startup": True,
    "show_startup_notification": True,
    "skipped_version": "",
}

DEFAULT_CORE_SETTINGS = {
    "allow_insecure_shell": False,
    "server_port": constants.DEFAULT_PORT,
}

# Automatically derive which keys belong to QSettings for clean separation.
QT_SETTING_KEYS = set(DEFAULT_GUI_SETTINGS.keys())
CORE_SETTING_KEYS = set(DEFAULT_CORE_SETTINGS.keys())


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
        """
        Loads configuration from the JSON file into the cache, ensuring that
        defaults are present for any missing keys.
        """
        self._json_cache = DEFAULT_CORE_SETTINGS.copy()
        if not self.config_file.exists():
            log.info("No config file found. Will use and save default core settings.")
            self._save_to_file()
            return

        try:
            with self.config_file.open("r", encoding="utf-8") as f:
                user_config = json.load(f)
                self._json_cache.update(user_config)
            log.info(f"Configuration loaded from {self.config_file}")
        except (IOError, json.JSONDecodeError) as e:
            log.error(f"Failed to load config file, using defaults instead: {e}")
            self._json_cache = DEFAULT_CORE_SETTINGS.copy()

    def _save_to_file(self):
        """Saves the configuration cache to the JSON file."""
        try:
            # Ensure the parent directory exists before writing the file.
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with self.config_file.open("w", encoding="utf-8") as f:
                json.dump(self._json_cache, f, indent=4)
            log.debug(f"Configuration saved to {self.config_file}")
        except IOError as e:
            log.error(f"Failed to save config file: {e}")
            raise ConfigurationError(f"Cannot save configuration: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """
        Gets a configuration value from the appropriate store (QSettings or JSON).
        """
        if key in QT_SETTING_KEYS:
            default_value = DEFAULT_GUI_SETTINGS.get(key, default)
            
            # If a default value exists, infer the type to ensure QSettings returns the
            # correct data type (e.g., bool instead of "true"). This prevents crashes.
            if default_value is not None:
                return self.qt_settings.value(key, default_value, type=type(default_value))
            
            # If no default, we cannot infer a type, so get the raw value.
            return self.qt_settings.value(key, default)

        # The JSON cache is pre-populated with defaults, so types should be correct.
        return self._json_cache.get(key, default)

    def set(self, key: str, value: Any):
        """
        Sets a configuration value in the appropriate store.
        """
        if key not in QT_SETTING_KEYS and key not in CORE_SETTING_KEYS:
            log.warning(f"Setting an unknown configuration key: '{key}'")

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
            # Reset core settings to defaults and save
            self._json_cache = DEFAULT_CORE_SETTINGS.copy()
            self._save_to_file()

            # Clear all GUI-specific settings; they will fallback to defaults on get()
            self.qt_settings.clear()
            log.info("Configuration has been reset to defaults.")
        except Exception as e:
            log.error(f"Failed to reset configuration: {e}")
            raise ConfigurationError(f"Cannot reset configuration: {e}")


# Global singleton instance for easy access across the application.
config_manager = ConfigManager()