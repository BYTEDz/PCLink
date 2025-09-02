# filename: src/pclink/gui/windows_notifier.py
"""
PCLink - Remote PC Control Server - Windows Toast Notifier
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

import logging
from pathlib import Path

# Import from the new central constants file
from ..core.constants import APP_AUMID

log = logging.getLogger(__name__)

try:
    from winsdk.windows.data.xml.dom import XmlDocument
    from winsdk.windows.ui.notifications import (ToastNotification,
                                                 ToastNotificationManager,
                                                 ToastNotifier)

    # The AUMID must be set before this can be called successfully.
    # The notifier is created by the ToastNotificationManager.
    notifier = ToastNotificationManager.create_toast_notifier(APP_AUMID)
    WINSDK_AVAILABLE = True
except (ImportError, RuntimeError, TypeError) as e:
    log.warning(f"Could not initialize Windows Notifier. Native notifications will be disabled. Error: {e}")
    notifier = None
    WINSDK_AVAILABLE = False


class WindowsNotifier:
    """A wrapper for sending native Windows toast notifications."""

    def is_available(self) -> bool:
        """Checks if the notifier was initialized successfully."""
        return WINSDK_AVAILABLE

    def show(self, title: str, message: str, icon_path: Path = None):
        """
        Displays a toast notification.
        
        Args:
            title: The main title of the notification.
            message: The body text of the notification.
            icon_path: Optional absolute path to an icon to display as the app logo.
        """
        if not self.is_available():
            log.warning("Attempted to show toast notification, but winsdk is not available.")
            return

        # Use a template with an image if a valid icon path is provided
        if icon_path and icon_path.exists() and icon_path.is_absolute():
            template = self._create_template_with_image(title, message, icon_path)
        else:
            template = self._create_text_only_template(title, message)
        
        try:
            toast = ToastNotification(template)
            notifier.show(toast)
            log.info(f"Showed Windows toast notification: '{title}'")
        except Exception as e:
            log.error(f"Failed to show Windows toast notification: {e}", exc_info=True)

    def _create_text_only_template(self, title: str, message: str) -> XmlDocument:
        """Creates a simple XML template with a title and message."""
        xml = f"""
        <toast>
            <visual>
                <binding template="ToastGeneric">
                    <text>{title}</text>
                    <text>{message}</text>
                </binding>
            </visual>
        </toast>
        """
        doc = XmlDocument()
        doc.load_xml(xml)
        return doc

    def _create_template_with_image(self, title: str, message: str, icon_path: Path) -> XmlDocument:
        """Creates an XML template that includes an app logo override."""
        icon_uri = icon_path.as_uri()
        
        xml = f"""
        <toast>
            <visual>
                <binding template="ToastGeneric">
                    <text>{title}</text>
                    <text>{message}</text>
                    <image placement="appLogoOverride" src="{icon_uri}" />
                </binding>
            </visual>
        </toast>
        """
        doc = XmlDocument()
        doc.load_xml(xml)
        return doc