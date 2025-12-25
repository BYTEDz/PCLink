# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import json
import logging
from typing import Any, Dict

from . import constants
from .exceptions import ConfigurationError

log = logging.getLogger(__name__)

# --- Default Configuration Values ---
# Central source of truth for all application settings and their defaults.

DEFAULT_SETTINGS = {
    # Web UI settings
    "theme": "dark",
    "language": "en",
    "minimize_to_tray": True,
    "check_updates_on_startup": True,
    "show_startup_notification": True,
    "skipped_version": "",
    
    # Core settings
    "allow_terminal_access": False,
    "allow_insecure_shell": False,
    "server_port": constants.DEFAULT_PORT,
    "auto_start": False,
    "transfer_cleanup_threshold": 7,
}


class ConfigManager:
    """
    Manages application settings using a JSON file for all configuration.
    """

    def __init__(self):
        self.config_file = constants.CONFIG_FILE
        self._json_cache: Dict[str, Any] = {}
        self._load_from_file()

    def _load_from_file(self):
        """
        Loads configuration from the JSON file into the cache, ensuring that
        defaults are present for any missing keys.
        """
        self._json_cache = DEFAULT_SETTINGS.copy()
        if not self.config_file.exists():
            log.info("No config file found. Will use and save default settings.")
            self._save_to_file()
            return

        try:
            with self.config_file.open("r", encoding="utf-8") as f:
                user_config = json.load(f)
                self._json_cache.update(user_config)
            log.info(f"Configuration loaded from {self.config_file}")
        except (IOError, json.JSONDecodeError) as e:
            log.error(f"Failed to load config file, using defaults instead: {e}")
            self._json_cache = DEFAULT_SETTINGS.copy()

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
        Gets a configuration value from the JSON cache.
        """
        return self._json_cache.get(key, default)

    def set(self, key: str, value: Any):
        """
        Sets a configuration value and saves to file.
        """
        if key not in DEFAULT_SETTINGS:
            log.warning(f"Setting an unknown configuration key: '{key}'")

        try:
            self._json_cache[key] = value
            self._save_to_file()
            log.debug(f"Setting '{key}' saved to config file.")
        except Exception as e:
            log.error(f"Error setting config key '{key}': {e}")
            raise ConfigurationError(f"Cannot set configuration: {e}")

    def reset_to_defaults(self):
        """Resets all configurations to their default states."""
        try:
            self._json_cache = DEFAULT_SETTINGS.copy()
            self._save_to_file()
            log.info("Configuration has been reset to defaults.")
        except Exception as e:
            log.error(f"Failed to reset configuration: {e}")
            raise ConfigurationError(f"Cannot reset configuration: {e}")


# Global singleton instance for easy access across the application.
config_manager = ConfigManager()