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
    "allow_extensions": True,
    "allow_insecure_shell": False,
    "server_port": constants.DEFAULT_PORT,
    "auto_start": False,
    "auto_open_webui": True,
    "transfer_cleanup_threshold": 7,

    # Services (API features that can be enabled/disabled)
    "services": {
        "files": True,
        "system": True,
        "info": True,
        "input": True,
        "media": True,
        "terminal": False, # Terminal access disabled by default for security
        "macros": True,
        "extensions": True,
        "applications": True,
        "utils": True,
    }
}


class ConfigManager:
    """Setting management via JSON store."""

    def __init__(self):
        self.config_file = constants.CONFIG_FILE
        self._json_cache: Dict[str, Any] = {}
        self._load_from_file()

    def _load_from_file(self):
        """
        Sync filesystem configuration to internal cache with fallback to defaults.
        """
        self._json_cache = DEFAULT_SETTINGS.copy()
        if not self.config_file.exists():
            log.info("No config file found. Will use and save default settings.")
            self._save_to_file()
            return

        try:
            with self.config_file.open("r", encoding="utf-8") as f:
                user_config = json.load(f)
                
                # Merge services to ensure new default services are included
                if "services" in user_config and isinstance(user_config["services"], dict):
                    merged_services = DEFAULT_SETTINGS["services"].copy()
                    merged_services.update(user_config["services"])
                    user_config["services"] = merged_services
                
                self._json_cache.update(user_config)
                
                # Perform initial sync for services and ensure all default services are present
                services = self._json_cache.get("services", {})
                if not isinstance(services, dict): services = {}
                else: services = services.copy()

                # Sync legacy keys
                if "allow_extensions" in self._json_cache:
                    services["extensions"] = self._json_cache["allow_extensions"]
                if "allow_terminal_access" in self._json_cache:
                    services["terminal"] = self._json_cache["allow_terminal_access"]
                
                # Ensure all defaults are present
                for svc, default_val in DEFAULT_SETTINGS["services"].items():
                    if svc not in services:
                        services[svc] = default_val
                        
                self._json_cache["services"] = services
                
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
        """Retrieve value from the active configuration set."""
        return self._json_cache.get(key, default)

    def set(self, key: str, value: Any):
        """Update configuration value and persist to disk."""
        if key not in DEFAULT_SETTINGS:
            log.warning(f"Setting an unknown configuration key: '{key}'")

        try:
            self._json_cache[key] = value
            
            # Sync legacy keys with services dict
            if key == "allow_extensions":
                services = self._json_cache.get("services", {}).copy()
                services["extensions"] = value
                self._json_cache["services"] = services
            elif key == "allow_terminal_access":
                services = self._json_cache.get("services", {}).copy()
                services["terminal"] = value
                self._json_cache["services"] = services
            elif key == "services":
                # Reverse sync: if services dict is updated, update legacy keys
                if "extensions" in value:
                    self._json_cache["allow_extensions"] = value["extensions"]
                if "terminal" in value:
                    self._json_cache["allow_terminal_access"] = value["terminal"]

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


# Global Config singleton.
config_manager = ConfigManager()