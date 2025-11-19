# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
import html
from pathlib import Path
from .constants import APP_AUMID
from .utils import resource_path # Import our robust path helper

log = logging.getLogger(__name__)

try:
    from winsdk.windows.data.xml.dom import XmlDocument
    from winsdk.windows.ui.notifications import ToastNotification, ToastNotificationManager
    notifier = ToastNotificationManager.create_toast_notifier(APP_AUMID)
    WINSDK_AVAILABLE = True
except (ImportError, RuntimeError, TypeError) as e:
    log.warning(f"Could not initialize Windows Notifier. Native notifications will be disabled. Error: {e}")
    notifier = None
    WINSDK_AVAILABLE = False


class WindowsNotifier:
    """A wrapper for sending native Windows toast notifications."""

    def __init__(self):
        # Get the icon path once during initialization
        self.default_icon_path = resource_path("src/pclink/assets/icon.png")
        if not self.default_icon_path.exists():
            log.warning(f"Default notification icon not found at: {self.default_icon_path}")
            self.default_icon_path = None

    def is_available(self) -> bool:
        """Checks if the notifier was initialized successfully."""
        return WINSDK_AVAILABLE

    def show(self, title: str, message: str) -> bool:
        """
        Shows a native Windows toast notification with the app icon.
        
        Args:
            title: The notification title.
            message: The notification message.
            
        Returns:
            True if the notification was sent successfully, False otherwise.
        """
        if not WINSDK_AVAILABLE or not notifier:
            return False
            
        try:
            # --- MODIFIED XML TEMPLATE ---
            # Use a more advanced template that includes an app logo override.
            # Paths must be absolute and correctly formatted.
            icon_uri = ""
            if self.default_icon_path:
                # The path must be URI-encoded (file:///)
                icon_uri = self.default_icon_path.as_uri()

            # Sanitize input to prevent XML errors
            safe_title = html.escape(title)
            safe_message = html.escape(message)
            
            toast_xml = f"""
            <toast>
                <visual>
                    <binding template="ToastGeneric">
                        <text>{safe_title}</text>
                        <text>{safe_message}</text>
                        <image placement="appLogoOverride" src="{icon_uri}" />
                    </binding>
                </visual>
            </toast>
            """
            # --- END MODIFIED XML TEMPLATE ---

            xml_doc = XmlDocument()
            xml_doc.load_xml(toast_xml)
            
            toast = ToastNotification(xml_doc)
            notifier.show(toast)
            
            log.debug(f"Windows toast notification sent: {title}")
            return True
            
        except Exception as e:
            log.error(f"Failed to send Windows toast notification: {e}", exc_info=True)
            return False