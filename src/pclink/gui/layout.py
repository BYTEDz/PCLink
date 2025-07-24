"""
PCLink - Remote PC Control Server - UI Layout Setup
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

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import (QComboBox, QFormLayout, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QPushButton,
                               QStyle, QVBoxLayout, QWidget)

from ..core.utils import get_available_ips


class StatusIndicator(QWidget):
    """A simple colored circle widget to indicate server status."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._color = QColor("grey")
        self.setFixedSize(16, 16)

    def set_color(self, color: str | QColor):
        self._color = QColor(color)
        self.update()  # Trigger a repaint

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(self._color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(self.rect())


def setupUi(main_window):
    """Sets up all the UI widgets and layouts for the main window."""
    main_window.resize(500, 600)

    central_widget = QWidget()
    main_window.setCentralWidget(central_widget)
    main_layout = QVBoxLayout(central_widget)
    main_layout.setContentsMargins(15, 15, 15, 15)
    main_layout.setSpacing(15)

    # --- Server Status Section ---
    server_status_layout = QHBoxLayout()
    main_window.status_indicator = StatusIndicator()

    status_text_vbox = QVBoxLayout()
    status_text_vbox.setSpacing(0)
    main_window.status_label = QLabel()
    main_window.status_label.setObjectName("statusTextLabel")
    main_window.protocol_label = QLabel()
    main_window.protocol_label.setObjectName("protocolStatusLabel")
    status_text_vbox.addWidget(main_window.status_label)
    status_text_vbox.addWidget(main_window.protocol_label)

    main_window.server_toggle_button = QPushButton()
    main_window.server_toggle_button.setMinimumSize(QSize(120, 0))

    server_status_layout.addWidget(main_window.status_indicator)
    server_status_layout.addSpacing(5)
    server_status_layout.addLayout(status_text_vbox, 1)
    server_status_layout.addWidget(main_window.server_toggle_button)
    main_layout.addLayout(server_status_layout)

    # --- QR Code and Connection Details Section ---
    qr_details_layout = QHBoxLayout()
    main_window.qr_label = QLabel()
    main_window.qr_label.setFixedSize(160, 160)
    main_window.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    main_window.qr_label.setObjectName("qrCodeLabel")
    main_window.qr_label.setWordWrap(True)
    main_window.qr_label.setScaledContents(False)
    qr_details_layout.addWidget(main_window.qr_label)

    details_layout = QFormLayout()
    details_layout.setSpacing(10)
    main_window.conn_details_layout = details_layout

    # IP Address Row
    main_window.ip_address_combo = QComboBox()
    main_window.ip_address_combo.addItems(get_available_ips())
    main_window.copy_ip_btn = QPushButton()
    main_window.copy_ip_btn.setObjectName("copyButton")
    ip_hbox = QHBoxLayout()
    ip_hbox.addWidget(main_window.ip_address_combo)
    ip_hbox.addWidget(main_window.copy_ip_btn)

    # Port Row
    main_window.port_entry = QLineEdit(str(main_window.api_port))
    main_window.port_entry.setReadOnly(True)
    main_window.copy_port_btn = QPushButton()
    main_window.copy_port_btn.setObjectName("copyButton")
    port_hbox = QHBoxLayout()
    port_hbox.addWidget(main_window.port_entry)
    port_hbox.addWidget(main_window.copy_port_btn)

    # API Key Row
    main_window.api_key_entry = QLineEdit(main_window.api_key)
    main_window.api_key_entry.setReadOnly(True)
    main_window.copy_key_btn = QPushButton()
    main_window.copy_key_btn.setObjectName("copyButton")
    key_hbox = QHBoxLayout()
    key_hbox.addWidget(main_window.api_key_entry)
    key_hbox.addWidget(main_window.copy_key_btn)

    main_window.ip_label, main_window.port_label, main_window.api_key_label = (
        QLabel(), QLabel(), QLabel()
    )
    details_layout.addRow(main_window.ip_label, ip_hbox)
    details_layout.addRow(main_window.port_label, port_hbox)
    details_layout.addRow(main_window.api_key_label, key_hbox)

    qr_details_layout.addLayout(details_layout)
    main_layout.addLayout(qr_details_layout)

    # --- Separator and Connected Devices Section ---
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    main_layout.addWidget(line)

    main_window.devices_label = QLabel()
    main_window.devices_label.setObjectName("subGroupTitle")
    main_layout.addWidget(main_window.devices_label)

    main_window.device_list = QListWidget()
    main_window.device_list.setAlternatingRowColors(True)
    main_window.device_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
    main_layout.addWidget(main_window.device_list)


def retranslateUi(main_window):
    """Applies translations to all relevant UI widgets."""
    title = main_window.tr("window_title")
    if main_window.platform == "win32" and main_window.is_admin:
        title += main_window.tr("admin_suffix")
    main_window.setWindowTitle(title)
    
    main_window.copy_ip_btn.setIcon(main_window.style().standardIcon(QStyle.StandardPixmap.SP_FileLinkIcon))
    main_window.copy_port_btn.setIcon(main_window.style().standardIcon(QStyle.StandardPixmap.SP_FileLinkIcon))
    main_window.copy_key_btn.setIcon(main_window.style().standardIcon(QStyle.StandardPixmap.SP_FileLinkIcon))

    main_window.devices_label.setText(main_window.tr("devices_group"))
    main_window.ip_label.setText(main_window.tr("ip_addr_label"))
    main_window.port_label.setText(main_window.tr("port_label"))
    main_window.api_key_label.setText(main_window.tr("api_key_label"))

    main_window.copy_ip_btn.setToolTip(main_window.tr("copy_ip_tooltip"))
    main_window.copy_port_btn.setToolTip(main_window.tr("copy_port_tooltip"))
    main_window.copy_key_btn.setToolTip(main_window.tr("copy_key_tooltip"))

    main_window.retranslate_menus()

    is_rtl = main_window.tr("is_rtl", default="false") == "true"
    layout_direction = Qt.LayoutDirection.RightToLeft if is_rtl else Qt.LayoutDirection.LeftToRight
    label_alignment = Qt.AlignmentFlag.AlignRight if not is_rtl else Qt.AlignmentFlag.AlignLeft
    
    main_window.setLayoutDirection(layout_direction)
    main_window.conn_details_layout.setLabelAlignment(label_alignment)

    main_window.controller.update_ui_for_server_state()