# src/pclink/core/linux_notifier.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
import os
import subprocess
import sys
from pathlib import Path
from .utils import resource_path

log = logging.getLogger(__name__)

NOTIFY_AVAILABLE = False
USE_GI_NOTIFY = False

try:
    import gi
    try:
        gi.require_version('Notify', '0.7')
        from gi.repository import Notify
        Notify.init("PCLink")
        NOTIFY_AVAILABLE = True
        USE_GI_NOTIFY = True
        log.info("Linux Notify (libnotify via gi) initialized.")
    except (ImportError, ValueError) as e:
        log.warning(f"gi.repository.Notify not available: {e}. Falling back to notify-send.")
        # Check if notify-send exists
        if subprocess.run(["which", "notify-send"], capture_output=True).returncode == 0:
            NOTIFY_AVAILABLE = True
            log.info("notify-send found. Using it as fallback.")
        else:
            log.warning("notify-send not found. Native Linux notifications will be disabled.")
except ImportError:
    # If gi is not available at all
    if subprocess.run(["which", "notify-send"], capture_output=True).returncode == 0:
        NOTIFY_AVAILABLE = True
        log.info("notify-send found. Using it as fallback (gi not available).")
    else:
        log.warning("gi not available and notify-send not found. Native Linux notifications disabled.")


class LinuxNotifier:
    """A wrapper for sending native Linux notifications."""

    def __init__(self):
        self.icon_path = resource_path("src/pclink/assets/icon.png")
        if not self.icon_path.exists():
            self.icon_path = None
        
        # Ensure DBUS_SESSION_BUS_ADDRESS is set if possible
        # This is vital for systemd user services to talk to the desktop notifications
        self._ensure_dbus_env()

    def _ensure_dbus_env(self):
        """Try to fix DBUS_SESSION_BUS_ADDRESS if missing."""
        if "DBUS_SESSION_BUS_ADDRESS" not in os.environ:
            uid = os.getuid()
            dbus_path = f"/run/user/{uid}/bus"
            if os.path.exists(dbus_path):
                os.environ["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={dbus_path}"
                log.debug(f"Set DBUS_SESSION_BUS_ADDRESS to {os.environ['DBUS_SESSION_BUS_ADDRESS']}")

    def is_available(self) -> bool:
        """Checks if any notification method is available."""
        return NOTIFY_AVAILABLE

    def show(self, title: str, message: str) -> bool:
        """
        Shows a native Linux notification.
        
        Returns:
            True if the notification was sent successfully, False otherwise.
        """
        if not NOTIFY_AVAILABLE:
            return False
            
        try:
            if USE_GI_NOTIFY:
                return self._show_gi(title, message)
            else:
                return self._show_binary(title, message)
        except Exception as e:
            log.error(f"Failed to send Linux notification: {e}")
            return False

    def _show_gi(self, title: str, message: str) -> bool:
        try:
            notification = Notify.Notification.new(title, message, str(self.icon_path) if self.icon_path else "dialog-information")
            # Set app name explicitly (some desktops use this)
            notification.set_hint("desktop-entry", "pclink")
            notification.show()
            log.debug(f"Linux notification sent via libnotify (gi): {title}")
            return True
        except Exception as e:
            log.error(f"libnotify (gi) failed: {e}")
            # Try falling back to binary if gi failed
            return self._show_binary(title, message)

    def _show_binary(self, title: str, message: str) -> bool:
        try:
            # -a, --app-name=APP_NAME  Specifies the app name for the notification.
            cmd = ["notify-send", "-a", "PCLink", title, message]
            if self.icon_path:
                cmd.extend(["-i", str(self.icon_path)])
            
            subprocess.run(cmd, check=True, capture_output=True)
            log.debug(f"Linux notification sent via notify-send: {title}")
            return True
        except Exception as e:
            log.error(f"notify-send failed: {e}")
            return False
