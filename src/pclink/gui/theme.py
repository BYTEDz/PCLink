# gui/theme.py
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
