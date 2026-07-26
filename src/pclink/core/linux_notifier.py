# src/pclink/core/linux_notifier.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
import os
import subprocess
import sys

from .utils import resource_path

log = logging.getLogger(__name__)

NOTIFY_AVAILABLE = False
USE_GI_NOTIFY = False

# Early exit if not on Linux to avoid running Linux-specific checks
if sys.platform.startswith("linux"):
    try:
        import gi

        try:
            gi.require_version("Notify", "0.7")
            from gi.repository import Notify

            Notify.init("PCLink")
            NOTIFY_AVAILABLE = True
            USE_GI_NOTIFY = True
            log.info("Linux Notify (libnotify via gi) initialized.")
        except (ImportError, ValueError) as e:
            log.warning(
                f"gi.repository.Notify not available: {e}. Falling back to notify-send."
            )
            # Check if notify-send exists
            try:
                if (
                    subprocess.run(
                        ["which", "notify-send"], capture_output=True
                    ).returncode
                    == 0
                ):
                    NOTIFY_AVAILABLE = True
                    log.info("notify-send found. Using it as fallback.")
                else:
                    log.warning(
                        "notify-send not found. Native Linux notifications will be disabled."
                    )
            except Exception:
                log.warning(
                    "Could not check for notify-send. Native Linux notifications will be disabled."
                )
    except ImportError:
        # If gi is not available at all
        try:
            if (
                subprocess.run(["which", "notify-send"], capture_output=True).returncode
                == 0
            ):
                NOTIFY_AVAILABLE = True
                log.info("notify-send found. Using it as fallback (gi not available).")
            else:
                log.warning(
                    "gi not available and notify-send not found. Native Linux notifications disabled."
                )
        except Exception:
            log.warning(
                "gi not available and could not check for notify-send. Native Linux notifications disabled."
            )
else:
    log.debug("Not on Linux, Skipping Linux notification initialization.")


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
        if (
            sys.platform.startswith("linux")
            and "DBUS_SESSION_BUS_ADDRESS" not in os.environ
        ):
            try:
                uid = os.getuid()
                dbus_path = f"/run/user/{uid}/bus"
                if os.path.exists(dbus_path):
                    os.environ["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={dbus_path}"
                    log.debug(
                        f"Set DBUS_SESSION_BUS_ADDRESS to {os.environ['DBUS_SESSION_BUS_ADDRESS']}"
                    )
            except (AttributeError, Exception) as e:
                log.debug(f"Could not fix DBUS_SESSION_BUS_ADDRESS: {e}")

    def is_available(self) -> bool:
        """Checks if any notification method is available."""
        return NOTIFY_AVAILABLE

    def show(self, title: str, message: str) -> bool:
        """Show basic notification."""
        return self._dispatch(title, message, url=None)

    def show_actionable(self, title: str, message: str, url: str) -> bool:
        """Show critical notification. On Linux there's no reliable click callback,
        so we embed the URL in the message body as fallback guidance."""
        return self._dispatch(title, message, url=url)

    def _dispatch(self, title: str, message: str, url: str | None) -> bool:
        if not NOTIFY_AVAILABLE:
            return False
        try:
            if USE_GI_NOTIFY:
                return self._show_gi(title, message, url)
            else:
                return self._show_binary(title, message, url)
        except Exception as e:
            log.error(f"Failed to send Linux notification: {e}")
            return False

    def _show_gi(self, title: str, message: str, url: str | None = None) -> bool:
        try:
            import webbrowser

            notification = Notify.Notification.new(
                title,
                message,
                str(self.icon_path) if self.icon_path else "dialog-information",
            )
            notification.set_hint("desktop-entry", "pclink")
            if url:
                notification.set_urgency(Notify.Urgency.CRITICAL)
                notification.add_action(
                    "open", "Open Web UI", lambda n, a, u=url: webbrowser.open(u), None
                )
            notification.show()
            log.debug(f"Linux notification sent via libnotify (gi): {title}")
            return True
        except Exception as e:
            log.error(f"libnotify (gi) failed: {e}")
            return self._show_binary(title, message, url)

    def _show_binary(self, title: str, message: str, url: str | None = None) -> bool:
        try:
            cmd = [
                "notify-send",
                "-a",
                "PCLink",
                "-u",
                "critical" if url else "normal",
                title,
                message,
            ]
            if self.icon_path:
                cmd.extend(["-i", str(self.icon_path)])
            subprocess.run(cmd, check=True, capture_output=True)
            log.debug(f"Linux notification sent via notify-send: {title}")
            return True
        except Exception as e:
            log.error(f"notify-send failed: {e}")
            return False
