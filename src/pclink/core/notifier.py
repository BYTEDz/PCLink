# src/pclink/core/notifier.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import html
import logging
import os
import subprocess
import sys

from .constants import APP_AUMID
from .utils import resource_path

log = logging.getLogger(__name__)


class BaseNotifier:
    """Base class for system notifications."""

    def __init__(self):
        self.icon_path = resource_path("src/pclink/assets/icon.png")
        if not self.icon_path.exists():
            self.icon_path = None

    def is_available(self) -> bool:
        return False

    def show(self, title: str, message: str) -> bool:
        return False

    def show_actionable(self, title: str, message: str, url: str) -> bool:
        return False


class WindowsNotifier(BaseNotifier):
    def __init__(self):
        super().__init__()
        self.notifier = None
        self.available = False
        try:
            from winrt.windows.data.xml.dom import XmlDocument
            from winrt.windows.ui.notifications import (
                ToastNotification,
                ToastNotificationManager,
            )

            self.notifier = ToastNotificationManager.create_toast_notifier(APP_AUMID)
            self.XmlDocument = XmlDocument
            self.ToastNotification = ToastNotification
            self.available = True
        except Exception as e:
            log.debug(f"Windows Notifier disabled: {e}")

    def is_available(self) -> bool:
        return self.available

    def show(self, title: str, message: str) -> bool:
        return self._send_toast(title, message, None)

    def show_actionable(self, title: str, message: str, url: str) -> bool:
        return self._send_toast(title, message, url)

    def _send_toast(self, title: str, message: str, launch_url: str | None) -> bool:
        if not self.available:
            return False
        try:
            icon_uri = self.icon_path.as_uri() if self.icon_path else ""
            launch_attr = f' launch="{html.escape(launch_url)}"' if launch_url else ""
            toast_xml = f"""
            <toast{launch_attr} activationType="protocol">
                <visual>
                    <binding template="ToastGeneric">
                        <text>{html.escape(title)}</text>
                        <text>{html.escape(message)}</text>
                        <image placement="appLogoOverride" src="{icon_uri}" />
                    </binding>
                </visual>
            </toast>
            """
            xml_doc = self.XmlDocument()
            xml_doc.load_xml(toast_xml)
            self.notifier.show(self.ToastNotification(xml_doc))
            return True
        except Exception as e:
            log.error(f"Windows toast failed: {e}")
            return False


class LinuxNotifier(BaseNotifier):
    def __init__(self):
        super().__init__()
        self.available = False
        self.use_gi = False
        self._ensure_dbus_env()

        try:
            import gi

            gi.require_version("Notify", "0.7")
            from gi.repository import Notify

            Notify.init("PCLink")
            self.Notify = Notify
            self.available = True
            self.use_gi = True
        except Exception:
            if (
                subprocess.run(["which", "notify-send"], capture_output=True).returncode
                == 0
            ):
                self.available = True

    def _ensure_dbus_env(self):
        if "DBUS_SESSION_BUS_ADDRESS" not in os.environ:
            try:
                dbus_path = f"/run/user/{os.getuid()}/bus"
                if os.path.exists(dbus_path):
                    os.environ["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={dbus_path}"
            except Exception:
                pass

    def is_available(self) -> bool:
        return self.available

    def show(self, title: str, message: str) -> bool:
        return self._dispatch(title, message, None)

    def show_actionable(self, title: str, message: str, url: str) -> bool:
        return self._dispatch(title, message, url)

    def _dispatch(self, title: str, message: str, url: str | None) -> bool:
        if not self.available:
            return False
        if self.use_gi:
            try:
                import webbrowser

                n = self.Notify.Notification.new(
                    title,
                    message,
                    str(self.icon_path) if self.icon_path else "dialog-information",
                )
                n.set_hint("desktop-entry", "pclink")
                if url:
                    n.set_urgency(self.Notify.Urgency.CRITICAL)
                    n.add_action(
                        "open",
                        "Open Web UI",
                        lambda n, a, u=url: webbrowser.open(u),
                        None,
                    )
                n.show()
                return True
            except Exception as e:
                log.error(f"gi notify failed: {e}")
                self.use_gi = False  # fallback to binary next time
                return self._dispatch(title, message, url)
        else:
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
                return True
            except Exception as e:
                log.error(f"notify-send failed: {e}")
                return False


def get_system_notifier() -> BaseNotifier:
    """Factory to get the correct notifier for the current OS."""
    if sys.platform == "win32":
        return WindowsNotifier()
    elif sys.platform.startswith("linux"):
        return LinuxNotifier()
    return BaseNotifier()
