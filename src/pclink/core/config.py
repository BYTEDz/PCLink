# src/pclink/core/config.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import gettext
import json
import logging
import threading
from copy import deepcopy
from typing import Any, Dict

from . import constants
from .validators import ConfigurationError

log = logging.getLogger(__name__)
_ = gettext.gettext

# --- Default Configuration Values ---
DEFAULT_SETTINGS: Dict[str, Any] = {
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
    "server_port": constants.DEFAULT_PORT,
    "auto_start": False,
    "auto_open_webui": True,
    "transfer_cleanup_threshold": 7,
    "keyboard_layout": "auto",
    # Default permissions assigned to a new device upon pairing
    "default_device_permissions": [
        "files_read",
        "files_write",
        "info",
        "input",
        "media",
        "apps",
        "screenshot",
        "macros",
        "processes",
    ],
    # Services (13 Canonical API features that can be enabled/disabled)
    "services": {
        "files_read": True,
        "files_write": True,
        "processes": True,
        "power": True,
        "info": True,
        "input": True,
        "media": True,
        "terminal": False,
        "macros": True,
        "extensions": True,
        "apps": True,
        "screenshot": True,
        "desktop_streaming": False,
    },
    # Notification preferences (UI toasts and tray messages)
    "notifications": {
        "device_connect": True,
        "device_disconnect": True,
        "pairing_request": True,
        "updates": True,
    },
}


def _deep_merge_and_sanitize(
    default: Dict[str, Any], user: Dict[str, Any]
) -> Dict[str, Any]:
    """Recursively merges user settings onto default dictionary and enforces type safety."""
    res = deepcopy(default)
    for k, v in user.items():
        if k in res:
            default_val = res[k]
            # Type safety check: Ensure user value matches expected type of default setting
            if isinstance(default_val, dict) and isinstance(v, dict):
                if k == "services":
                    # Strictly limit services to canonical keys defined in default["services"]
                    res[k] = {
                        s_key: v.get(s_key, default_val.get(s_key, True))
                        for s_key in default_val.keys()
                        if isinstance(v.get(s_key, default_val.get(s_key, True)), bool)
                    }
                else:
                    res[k] = _deep_merge_and_sanitize(default_val, v)
            elif type(default_val) is type(v):
                res[k] = v
            elif isinstance(default_val, int) and isinstance(v, str) and v.isdigit():
                # Auto-coerce numeric strings to integers (e.g. port "38080" -> 38080)
                res[k] = int(v)
            else:
                log.warning(
                    f"Config Sanitizer: Type mismatch for key '{k}'. Expected {type(default_val).__name__}, got {type(v).__name__}. Restoring default value."
                )
        else:
            res[k] = v
    return res


class ConfigManager:
    """Thread-safe configuration manager backed by JSON store with structured defaults and type sanitization."""

    def __init__(self):
        self.config_file = constants.CONFIG_FILE
        self._lock = threading.RLock()
        self._json_cache: Dict[str, Any] = {}
        self._load_from_file()

    def _load_from_file(self):
        """Sync filesystem configuration to internal cache with fallback and type sanitization."""
        with self._lock:
            self._json_cache = deepcopy(DEFAULT_SETTINGS)
            if not self.config_file.exists():
                log.info("No config file found. Will use and save default settings.")
                self._save_to_file()
                return

            try:
                with self.config_file.open("r", encoding="utf-8") as f:
                    user_config = json.load(f)
                    if isinstance(user_config, dict):
                        self._json_cache = _deep_merge_and_sanitize(
                            DEFAULT_SETTINGS, user_config
                        )

                log.info(f"Configuration loaded from {self.config_file}")
            except (IOError, json.JSONDecodeError) as e:
                log.error(f"Failed to load config file, using defaults instead: {e}")
                self._json_cache = deepcopy(DEFAULT_SETTINGS)

    def _save_to_file(self):
        """Saves the configuration cache to the JSON file."""
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with self.config_file.open("w", encoding="utf-8") as f:
                json.dump(self._json_cache, f, indent=4)
            log.debug(f"Configuration saved to {self.config_file}")
        except IOError as e:
            log.error(f"Failed to save config file: {e}")
            raise ConfigurationError(
                _("Cannot save configuration: {error}").format(error=e)
            )

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve value from active configuration, guaranteeing ONLY canonical keys for 'services'."""
        with self._lock:
            val = self._json_cache.get(key, default)
            if key == "services" and isinstance(val, dict):
                canonical_keys = DEFAULT_SETTINGS["services"].keys()
                # Filter out any legacy non-canonical keys
                return {
                    k: val.get(k, DEFAULT_SETTINGS["services"][k])
                    for k in canonical_keys
                }
            return val

    def set(self, key: str, value: Any):
        """Update configuration value and persist to disk."""
        with self._lock:
            if key not in DEFAULT_SETTINGS:
                log.warning(f"Setting an unknown configuration key: '{key}'")

            try:
                if key == "services" and isinstance(value, dict):
                    # Purge legacy non-canonical keys before saving
                    canonical_keys = DEFAULT_SETTINGS["services"].keys()
                    value = {
                        k: value.get(k, DEFAULT_SETTINGS["services"][k])
                        for k in canonical_keys
                    }

                self._json_cache[key] = value
                self._save_to_file()
                log.debug(f"Setting '{key}' saved to config file.")
            except ConfigurationError:
                raise
            except Exception as e:
                log.error(f"Error setting config key '{key}': {e}")
                raise ConfigurationError(
                    _("Cannot set configuration: {error}").format(error=e)
                )

    def reset_to_defaults(self):
        """Resets all configurations to their default states."""
        with self._lock:
            try:
                self._json_cache = deepcopy(DEFAULT_SETTINGS)
                self._save_to_file()
                log.info("Configuration has been reset to defaults.")
            except ConfigurationError:
                raise
            except Exception as e:
                log.error(f"Failed to reset configuration: {e}")
                raise ConfigurationError(
                    _("Cannot reset configuration: {error}").format(error=e)
                )


# Global Config singleton.
config_manager = ConfigManager()
