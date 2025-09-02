# filename: src/pclink/gui/theme.py
import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

from ..core.utils import resource_path

log = logging.getLogger(__name__)

DARK_STYLESHEET = """
QWidget { background-color: #2e2f30; color: #e0e0e0; font-family: Segoe UI, sans-serif; font-size: 10pt; }
QMainWindow { background-color: #2e2f30; } 
QMenuBar { background-color: #3a3b3c; }
QMenuBar::item:selected { background-color: #5a5b5c; }
QMenu { background-color: #3a3b3c; border: 1px solid #4a4b4c; }
QMenu::item:selected { background-color: #5a5b5c; }
QLabel { background-color: transparent; } 
QLabel#statusTextLabel { font-size: 14pt; font-weight: bold; }
QLabel#protocolStatusLabel { font-size: 9pt; color: #a0a0a0; }
QLabel#subGroupTitle { font-weight: bold; padding-top: 5px; font-size: 11pt; color: #e0e0e0;}
QLabel#qrCodeLabel { 
    border: 2px solid #4a4b4c; 
    border-radius: 8px; 
    background-color: #242526; 
    padding: 8px; 
    text-align: center;
    word-wrap: break-word;
}
QLineEdit, QComboBox, QListWidget { background-color: #242526; border: 1px solid #4a4b4c; border-radius: 4px; padding: 6px; }
QLineEdit {font-family: Consolas, monospace;}
QPushButton { background-color: #5a5b5c; border: none; border-radius: 4px; padding: 8px 16px; font-weight: bold; }
QPushButton:hover { background-color: #6a6b6c; } QPushButton:pressed { background-color: #4a4b4c; } QPushButton:disabled { background-color: #404040; color: #888; }
QPushButton#copyButton { padding: 4px; font-size: 8pt; max-width: 30px; }
QMessageBox, QInputDialog { background-color: #3a3b3c; }
"""


def get_stylesheet() -> str:
    """Returns the application's stylesheet."""
    return DARK_STYLESHEET


def create_app_icon() -> QIcon:
    """
    Loads the application icon from assets, creating a fallback if not found.
    """
    icon_path = resource_path("assets/icon.png")
    log.debug(f"Attempting to load icon from: {icon_path}")

    if icon_path.exists():
        icon = QIcon(str(icon_path))
        if not icon.isNull():
            log.info(f"Successfully loaded app icon from: {icon_path}")
            return icon
        log.warning(f"Icon file exists but failed to load properly: {icon_path}")

    log.warning(f"Icon file not found at '{icon_path}'. Creating a fallback icon.")
    return _create_fallback_icon()


def _create_fallback_icon() -> QIcon:
    """Creates a programmatic fallback icon for the application."""
    icon = QIcon()
    for size in [16, 32, 48, 64, 128, 256]:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(60, 9, 108))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(0, 0, size, size)

        painter.setPen(QColor(227, 227, 227))
        font = painter.font()
        font.setPixelSize(int(size * 0.6))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "PC")

        painter.end()
        icon.addPixmap(pixmap)
    return icon