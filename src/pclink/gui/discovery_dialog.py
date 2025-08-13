"""
PCLink Discovery Troubleshooting Dialog
Helps users fix discovery issues with Android devices
"""

import logging
import socket
import subprocess
import sys
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QTextEdit, QProgressBar, QMessageBox, QGroupBox
)
from PySide6.QtGui import QFont, QIcon

from ..core.utils import is_admin, check_firewall_rule_exists, add_firewall_rule, restart_as_admin

log = logging.getLogger(__name__)


class DiscoveryFixThread(QThread):
    """Background thread for discovery diagnostics and fixes"""
    
    progress_update = Signal(str)
    finished_signal = Signal(bool, str)
    
    def __init__(self, fix_firewall=False):
        super().__init__()
        self.fix_firewall = fix_firewall
    
    def run(self):
        try:
            self.progress_update.emit("Checking network configuration...")
            
            # Get network info
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                s.close()
                
                ip_parts = local_ip.split('.')
                network = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.0/24"
                
                self.progress_update.emit(f"✓ Local IP: {local_ip}")
                self.progress_update.emit(f"✓ Network: {network}")
                
            except Exception as e:
                self.progress_update.emit(f"✗ Network check failed: {e}")
                self.finished_signal.emit(False, "Network configuration error")
                return
            
            # Check PCLink status
            self.progress_update.emit("Checking PCLink server status...")
            
            try:
                result = subprocess.run(['netstat', '-ano'], capture_output=True, text=True, timeout=5)
                
                if ':38099' in result.stdout:
                    self.progress_update.emit("✓ Discovery port 38099 is active")
                else:
                    self.progress_update.emit("⚠ Discovery port 38099 not found")
                
                if ':8000' in result.stdout:
                    self.progress_update.emit("✓ API port 8000 is active")
                else:
                    self.progress_update.emit("⚠ API port 8000 not found")
                    
            except Exception as e:
                self.progress_update.emit(f"⚠ Could not check ports: {e}")
            
            # Check firewall rules
            self.progress_update.emit("Checking Windows Firewall...")
            
            rule_exists = check_firewall_rule_exists("PCLink Discovery")
            
            if rule_exists:
                self.progress_update.emit("✓ PCLink Discovery firewall rule exists")
                
                if not self.fix_firewall:
                    self.finished_signal.emit(True, "Discovery should be working. If Android devices still can't discover the server, check router settings (disable AP isolation).")
                    return
            else:
                self.progress_update.emit("✗ PCLink Discovery firewall rule missing")
                
                if self.fix_firewall:
                    self.progress_update.emit("Adding firewall rule...")
                    
                    if not is_admin():
                        self.finished_signal.emit(False, "Administrator privileges required to add firewall rules")
                        return
                    
                    success, message = add_firewall_rule("PCLink Discovery", 38099, "UDP", "out")
                    
                    if success:
                        self.progress_update.emit("✓ Firewall rule added successfully")
                        self.finished_signal.emit(True, "Discovery firewall rule added! Restart PCLink and try discovery from Android device.")
                    else:
                        self.progress_update.emit(f"✗ Failed to add firewall rule: {message}")
                        self.finished_signal.emit(False, f"Failed to add firewall rule: {message}")
                else:
                    self.finished_signal.emit(False, "Firewall rule missing - click 'Fix Discovery' to add it")
            
        except Exception as e:
            log.error(f"Discovery fix thread error: {e}", exc_info=True)
            self.finished_signal.emit(False, f"Unexpected error: {e}")


class DiscoveryTroubleshootDialog(QDialog):
    """Dialog for troubleshooting and fixing discovery issues"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Discovery Troubleshooting")
        self.setModal(True)
        self.resize(600, 500)
        
        self.fix_thread = None
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Title
        title = QLabel("PCLink Discovery Troubleshooting")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        # Description
        desc = QLabel(
            "This tool helps diagnose and fix issues preventing Android devices "
            "from discovering your PCLink server on the network."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #888; margin: 10px 0;")
        layout.addWidget(desc)
        
        # Status group
        status_group = QGroupBox("Diagnostic Results")
        status_layout = QVBoxLayout(status_group)
        
        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setMaximumHeight(200)
        self.status_text.setStyleSheet("""
            QTextEdit {
                background-color: #2b2b2b;
                color: #ffffff;
                border: 1px solid #555;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 10pt;
            }
        """)
        status_layout.addWidget(self.status_text)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        status_layout.addWidget(self.progress_bar)
        
        layout.addWidget(status_group)
        
        # Instructions group
        instructions_group = QGroupBox("Common Solutions")
        instructions_layout = QVBoxLayout(instructions_group)
        
        instructions = QLabel("""
<b>If discovery still doesn't work after fixing firewall:</b><br>
• Ensure Android device is on the same WiFi network<br>
• Check router settings - disable "AP Isolation" if enabled<br>
• Restart PCLink server after applying fixes<br>
• Use QR code connection as alternative<br>
• Try manual IP entry: your server IP is shown above
        """)
        instructions.setWordWrap(True)
        instructions_layout.addWidget(instructions)
        
        layout.addWidget(instructions_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.diagnose_btn = QPushButton("Run Diagnostics")
        self.diagnose_btn.clicked.connect(self.run_diagnostics)
        button_layout.addWidget(self.diagnose_btn)
        
        self.fix_btn = QPushButton("Fix Discovery")
        self.fix_btn.clicked.connect(self.fix_discovery)
        self.fix_btn.setEnabled(False)
        button_layout.addWidget(self.fix_btn)
        
        button_layout.addStretch()
        
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.close_btn)
        
        layout.addLayout(button_layout)
    
    def run_diagnostics(self):
        """Run discovery diagnostics"""
        self.status_text.clear()
        self.status_text.append("Starting discovery diagnostics...\n")
        
        self.diagnose_btn.setEnabled(False)
        self.fix_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate
        
        self.fix_thread = DiscoveryFixThread(fix_firewall=False)
        self.fix_thread.progress_update.connect(self.update_status)
        self.fix_thread.finished_signal.connect(self.diagnostics_finished)
        self.fix_thread.start()
    
    def fix_discovery(self):
        """Fix discovery issues"""
        if not is_admin():
            reply = QMessageBox.question(
                self, "Administrator Required",
                "Administrator privileges are required to add firewall rules.\n\n"
                "Would you like to restart PCLink as Administrator?",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                if restart_as_admin():
                    QMessageBox.information(
                        self, "Restarting",
                        "PCLink will restart with administrator privileges. "
                        "Please run the discovery fix again after restart."
                    )
                    self.accept()
                    return
                else:
                    QMessageBox.warning(
                        self, "Restart Failed",
                        "Could not restart as administrator. Please manually run PCLink as Administrator."
                    )
            return
        
        self.status_text.clear()
        self.status_text.append("Fixing discovery issues...\n")
        
        self.diagnose_btn.setEnabled(False)
        self.fix_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        
        self.fix_thread = DiscoveryFixThread(fix_firewall=True)
        self.fix_thread.progress_update.connect(self.update_status)
        self.fix_thread.finished_signal.connect(self.fix_finished)
        self.fix_thread.start()
    
    def update_status(self, message):
        """Update status text"""
        self.status_text.append(message)
        self.status_text.ensureCursorVisible()
    
    def diagnostics_finished(self, success, message):
        """Handle diagnostics completion"""
        self.progress_bar.setVisible(False)
        self.diagnose_btn.setEnabled(True)
        
        if success:
            self.status_text.append(f"\n✓ Diagnostics completed: {message}")
        else:
            self.status_text.append(f"\n✗ Issue found: {message}")
            self.fix_btn.setEnabled(True)
    
    def fix_finished(self, success, message):
        """Handle fix completion"""
        self.progress_bar.setVisible(False)
        self.diagnose_btn.setEnabled(True)
        
        if success:
            self.status_text.append(f"\n✓ Fix completed: {message}")
            QMessageBox.information(
                self, "Discovery Fixed",
                f"{message}\n\nPlease restart PCLink server and try discovery from your Android device."
            )
        else:
            self.status_text.append(f"\n✗ Fix failed: {message}")
            QMessageBox.warning(self, "Fix Failed", message)
    
    def closeEvent(self, event):
        if self.fix_thread and self.fix_thread.isRunning():
            self.fix_thread.terminate()
            self.fix_thread.wait()
        event.accept()