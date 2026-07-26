# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import html
import logging
import sys

from .constants import APP_AUMID
from .utils import resource_path  # Import our robust path helper

log = logging.getLogger(__name__)

if sys.platform == "win32":
    try:
        from winrt.windows.data.xml.dom import XmlDocument
        from winrt.windows.ui.notifications import (
            ToastNotification,
            ToastNotificationManager,
        )

        notifier = ToastNotificationManager.create_toast_notifier(APP_AUMID)
        WINSDK_AVAILABLE = True
    except (ImportError, RuntimeError, TypeError) as e:
        log.warning(
            f"Could not initialize Windows Notifier. Native notifications will be disabled. Error: {e}"
        )
        notifier = None
        WINSDK_AVAILABLE = False
else:
    notifier = None
    WINSDK_AVAILABLE = False


class WindowsNotifier:
    """A wrapper for sending native Windows toast notifications."""

    def __init__(self):
        # Get the icon path once during initialization
        self.default_icon_path = resource_path("src/pclink/assets/icon.png")
        if not self.default_icon_path.exists():
            log.warning(
                f"Default notification icon not found at: {self.default_icon_path}"
            )
            self.default_icon_path = None

    def is_available(self) -> bool:
        """Checks if the notifier was initialized successfully."""
        return WINSDK_AVAILABLE

    def show(self, title: str, message: str) -> bool:
        """Show basic toast with no action."""
        return self._send_toast(title, message, launch_url=None)

    def show_actionable(self, title: str, message: str, url: str) -> bool:
        """Show clickable toast — clicking opens `url` in default browser."""
        return self._send_toast(title, message, launch_url=url)

    def _send_toast(self, title: str, message: str, launch_url: str | None) -> bool:
        if not WINSDK_AVAILABLE or not notifier:
            return False

        try:
            icon_uri = self.default_icon_path.as_uri() if self.default_icon_path else ""
            safe_title = html.escape(title)
            safe_message = html.escape(message)

            # launch attr → Windows opens this URL when user clicks the toast body
            launch_attr = f' launch="{html.escape(launch_url)}"' if launch_url else ""

            toast_xml = f"""
            <toast{launch_attr} activationType="protocol">
                <visual>
                    <binding template="ToastGeneric">
                        <text>{safe_title}</text>
                        <text>{safe_message}</text>
                        <image placement="appLogoOverride" src="{icon_uri}" />
                    </binding>
                </visual>
            </toast>
            """

            xml_doc = XmlDocument()
            xml_doc.load_xml(toast_xml)
            notifier.show(ToastNotification(xml_doc))

            log.debug(f"Windows toast sent: {title} (url={launch_url})")
            return True

        except Exception as e:
            log.error(f"Failed to send Windows toast: {e}", exc_info=True)
            return False
