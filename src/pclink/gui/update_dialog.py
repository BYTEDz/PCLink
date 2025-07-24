#!/usr/bin/env python3
"""
Update Notification Dialog for PCLink
"""

import logging
import webbrowser
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton,
                               QTextEdit, QVBoxLayout, QWidget)

from .theme import get_stylesheet

log = logging.getLogger(__name__)

class UpdateDialog(QDialog):
    """Dialog to notify users about available updates."""
    
    def __init__(self, update_info: dict, parent=None):
        super().__init__(parent)
        self.update_info = update_info
        self.setWindowTitle("PCLink Update Available")
        self.setModal(True)
        self.setFixedSize(500, 400)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        
        # Apply the same theme as the main application
        self.setStyleSheet(get_stylesheet())
        
        self.setup_ui()
        
    def setup_ui(self):
        """Setup the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Header section
        header_layout = QHBoxLayout()
        
        # Icon with app's brand color
        icon_label = QLabel()
        icon_label.setFixedSize(48, 48)
        icon_label.setStyleSheet("""
            background-color: #3c096c; 
            border-radius: 24px;
            border: 2px solid #4a4b4c;
        """)
        header_layout.addWidget(icon_label)
        
        # Title and version info
        title_layout = QVBoxLayout()
        title_label = QLabel("New Version Available!")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        
        version_label = QLabel(
            f"Version {self.update_info['version']} is now available.\n"
            f"You are currently using version {self._get_current_version()}."
        )
        version_label.setStyleSheet("color: #a0a0a0; font-size: 10pt;")
        
        title_layout.addWidget(title_label)
        title_layout.addWidget(version_label)
        header_layout.addLayout(title_layout)
        header_layout.addStretch()
        
        layout.addLayout(header_layout)
        
        # Add separator line
        separator = QLabel()
        separator.setFixedHeight(1)
        separator.setStyleSheet("background-color: #4a4b4c; margin: 10px 0;")
        layout.addWidget(separator)
        
        # Release notes section
        if self.update_info.get("body"):
            notes_label = QLabel("What's New:")
            notes_label.setObjectName("subGroupTitle")  # Use app's styling
            layout.addWidget(notes_label)
            
            notes_text = QTextEdit()
            notes_text.setPlainText(self.update_info["body"])
            notes_text.setReadOnly(True)
            notes_text.setMaximumHeight(150)
            # The QTextEdit will inherit the app's styling automatically
            layout.addWidget(notes_text)
        
        # Add separator before buttons
        button_separator = QLabel()
        button_separator.setFixedHeight(1)
        button_separator.setStyleSheet("background-color: #4a4b4c; margin: 15px 0 10px 0;")
        layout.addWidget(button_separator)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        # Skip this version button
        skip_button = QPushButton("Skip This Version")
        skip_button.clicked.connect(self.skip_version)
        
        # Remind me later button
        later_button = QPushButton("Remind Me Later")
        later_button.clicked.connect(self.remind_later)
        
        # Download button with brand color
        download_button = QPushButton("Download Update")
        download_button.setDefault(True)
        download_button.setStyleSheet("""
            QPushButton {
                background-color: #3c096c;
                color: #e0e0e0;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 10pt;
            }
            QPushButton:hover {
                background-color: #4a0a7a;
            }
            QPushButton:pressed {
                background-color: #2a0650;
            }
        """)
        download_button.clicked.connect(self.download_update)
        
        button_layout.addWidget(skip_button)
        button_layout.addWidget(later_button)
        button_layout.addStretch()
        button_layout.addWidget(download_button)
        
        layout.addLayout(button_layout)
    
    def _get_current_version(self) -> str:
        """Get current application version."""
        try:
            from ..core.version import __version__
            return __version__
        except ImportError:
            return "Unknown"
    
    def download_update(self):
        """Open the download page in browser."""
        try:
            # Try to get platform-specific download
            download_url = self._get_download_url()
            if download_url:
                webbrowser.open(download_url)
            else:
                # Fallback to release page
                webbrowser.open(self.update_info["html_url"])
            
            log.info(f"Opened download page for version {self.update_info['version']}")
            self.accept()
            
        except Exception as e:
            log.error(f"Failed to open download page: {e}")
            # Still close the dialog
            self.accept()
    
    def _get_download_url(self) -> Optional[str]:
        """Get the appropriate download URL for current platform."""
        import sys
        
        assets = self.update_info.get("assets", [])
        platform_patterns = {
            "win32": [".exe", ".msi", "windows"],
            "darwin": [".dmg", ".pkg", "macos", "darwin"],
            "linux": [".deb", ".rpm", ".tar.gz", "linux"]
        }
        
        current_platform = sys.platform
        patterns = platform_patterns.get(current_platform, [])
        
        # Try to find platform-specific asset
        for pattern in patterns:
            for asset in assets:
                asset_name = asset.get("name", "").lower()
                if pattern in asset_name:
                    return asset.get("browser_download_url")
        
        # Return first asset if no platform match
        if assets:
            return assets[0].get("browser_download_url")
        
        return None
    
    def skip_version(self):
        """Skip this version (save preference)."""
        try:
            from PySide6.QtCore import QSettings
            settings = QSettings("PCLink", "UpdateChecker")
            settings.setValue("skipped_version", self.update_info["version"])
            log.info(f"Skipped version {self.update_info['version']}")
        except Exception as e:
            log.warning(f"Failed to save skip preference: {e}")
        
        self.reject()
    
    def remind_later(self):
        """Remind later (just close dialog)."""
        log.info("User chose to be reminded later")
        self.reject()