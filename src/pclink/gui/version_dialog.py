"""
PCLink - A simple, compact, and modern Version Information Dialog.
"""

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QFormLayout,
    QFrame,
)

from ..core.utils import resource_path
from ..core.version import __version__, version_info


class VersionDialog(QDialog):
    """A simple, single-pane dialog showing version and build information."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About PCLink")
        self.setObjectName("versionDialog")

        # Set a fixed size for a compact, clean look
        self.setFixedSize(480, 400)

        self.setup_ui()

    def setup_ui(self):
        """Set up the main UI components in a single vertical layout."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 10)
        main_layout.setSpacing(10)

        # 1. Header Section
        main_layout.addWidget(self._create_header())

        # 2. Content Section
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(20, 10, 20, 10)
        content_layout.addWidget(self._create_about_section())

        # 3. Dynamic Build Info Section (only if metadata exists)
        metadata = self._get_metadata()
        if metadata:
            content_layout.addWidget(self._create_separator())
            content_layout.addLayout(self._create_build_info_section(metadata))
        
        main_layout.addWidget(content_widget)

        # 4. Footer Section
        main_layout.addStretch(1)
        main_layout.addLayout(self._create_footer())

    def _create_header(self):
        """Creates the top header widget with title and copyright."""
        header_widget = QWidget()
        header_widget.setObjectName("headerWidget")
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(20, 15, 20, 15)
        header_layout.setSpacing(2)

        title_label = QLabel("PCLink")
        title_label.setObjectName("titleLabel")

        version_label = QLabel(f"Version {version_info.version}")
        version_label.setObjectName("versionLabel")

        copyright_label = QLabel(version_info.copyright)
        copyright_label.setObjectName("copyrightLabel")

        header_layout.addWidget(title_label)
        header_layout.addWidget(version_label)
        header_layout.addSpacing(10)
        header_layout.addWidget(copyright_label)
        return header_widget

    def _create_about_section(self):
        """Creates the main 'About' content widget."""
        about_widget = QWidget()
        layout = QVBoxLayout(about_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)

        description = QLabel(version_info.description)
        description.setWordWrap(True)

        form_layout = QFormLayout()
        form_layout.setSpacing(8)
        website_label = QLabel(f'<a href="{version_info.url}" style="color: #4A90E2;">{version_info.url}</a>')
        website_label.setOpenExternalLinks(True)

        form_layout.addRow("<b>Author:</b>", QLabel(version_info.author))
        form_layout.addRow("<b>License:</b>", QLabel(version_info.license))
        form_layout.addRow("<b>Website:</b>", website_label)
        
        layout.addWidget(description)
        layout.addLayout(form_layout)
        return about_widget

    def _create_build_info_section(self, metadata):
        """Creates the 'Build Info' layout, only called if metadata exists."""
        build_layout = QVBoxLayout()
        build_layout.setSpacing(8)

        build_header = QLabel("Build Information")
        build_header.setObjectName("sectionHeader")
        
        form_layout = QFormLayout()
        form_layout.setSpacing(8)

        build_info = metadata.get("build", {})
        for key, value in build_info.items():
            form_layout.addRow(f"<b>{key.capitalize()}:</b>", QLabel(str(value)))
            
        build_layout.addWidget(build_header)
        build_layout.addLayout(form_layout)
        return build_layout
        
    def _create_footer(self):
        """Creates the bottom footer with a close button."""
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(20, 0, 20, 0)
        close_button = QPushButton("Close")
        close_button.setFixedWidth(100)
        close_button.clicked.connect(self.accept)
        
        footer_layout.addStretch()
        footer_layout.addWidget(close_button)
        return footer_layout

    def _create_separator(self):
        """Creates a styled horizontal line."""
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        separator.setObjectName("separator")
        return separator

    def _get_metadata(self):
        """Finds and parses the release_metadata.json file."""
        # This function remains unchanged as it's already robust
        metadata_paths = [
            Path("release_metadata.json"),
            resource_path("release_metadata.json"),
        ]
        for path in metadata_paths:
            try:
                if path.exists():
                    with open(path, "r", encoding="utf-8") as f:
                        return json.load(f)
            except (IOError, json.JSONDecodeError):
                continue
        return None