#!/usr/bin/env python3
"""
PCLink Setup Guide and First-Run Experience
Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

This module handles the first-run setup experience, including port checking,
configuration validation, and user guidance.
"""

import logging
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                               QPushButton, QProgressBar, QTextEdit, QCheckBox,
                               QSpinBox, QMessageBox, QGroupBox, QFormLayout, QWidget)

from . import constants
from .utils import load_config_value, save_config_value, is_admin

log = logging.getLogger(__name__)


class PortChecker(QThread):
    """Thread for checking port availability and system requirements."""
    
    progress_updated = Signal(int, str)  # progress, message
    check_completed = Signal(dict)  # results dict
    
    def __init__(self, ports_to_check: List[int]):
        super().__init__()
        self.ports_to_check = ports_to_check
        self.results = {}
    
    def run(self):
        """Run port checks and system validation."""
        total_checks = len(self.ports_to_check) + 3  # ports + 3 system checks
        current_check = 0
        
        # Check system requirements
        self.progress_updated.emit(
            int((current_check / total_checks) * 100),
            "Checking system requirements..."
        )
        self.results['system'] = self._check_system_requirements()
        current_check += 1
        
        # Check firewall status
        self.progress_updated.emit(
            int((current_check / total_checks) * 100),
            "Checking firewall status..."
        )
        self.results['firewall'] = self._check_firewall_status()
        current_check += 1
        
        # Check admin privileges
        self.progress_updated.emit(
            int((current_check / total_checks) * 100),
            "Checking admin privileges..."
        )
        self.results['admin'] = is_admin()
        current_check += 1
        
        # Check ports
        port_results = {}
        for port in self.ports_to_check:
            self.progress_updated.emit(
                int((current_check / total_checks) * 100),
                f"Checking port {port}..."
            )
            port_results[port] = self._check_port(port)
            current_check += 1
            time.sleep(0.1)  # Small delay for UI responsiveness
        
        self.results['ports'] = port_results
        self.check_completed.emit(self.results)
    
    def _check_port(self, port: int) -> Dict[str, any]:
        """Check if a port is available."""
        result = {
            'available': False,
            'error': None,
            'process': None,
            'can_fix': False
        }
        
        try:
            # Try to bind to the port
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(('127.0.0.1', port))
                result['available'] = True
                log.info(f"Port {port} is available")
        except OSError as e:
            result['error'] = str(e)
            log.warning(f"Port {port} is not available: {e}")
            
            # Try to find what's using the port
            try:
                process_info = self._find_process_using_port(port)
                if process_info:
                    result['process'] = process_info
                    # Check if it's another PCLink instance
                    if 'pclink' in process_info.get('name', '').lower():
                        result['can_fix'] = True
            except Exception as find_error:
                log.warning(f"Could not identify process using port {port}: {find_error}")
        
        return result
    
    def _find_process_using_port(self, port: int) -> Optional[Dict[str, any]]:
        """Find which process is using a specific port."""
        try:
            import psutil
            for conn in psutil.net_connections():
                if conn.laddr.port == port:
                    try:
                        process = psutil.Process(conn.pid)
                        return {
                            'pid': conn.pid,
                            'name': process.name(),
                            'cmdline': ' '.join(process.cmdline()),
                        }
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        return {'pid': conn.pid, 'name': 'Unknown', 'cmdline': ''}
        except Exception as e:
            log.error(f"Error finding process using port {port}: {e}")
        return None
    
    def _check_system_requirements(self) -> Dict[str, any]:
        """Check system requirements."""
        result = {
            'python_version': sys.version,
            'platform': sys.platform,
            'meets_requirements': True,
            'issues': []
        }
        
        # Check Python version
        if sys.version_info < (3, 8):
            result['meets_requirements'] = False
            result['issues'].append("Python 3.8+ required")
        
        # Check required directories
        try:
            constants.APP_DATA_PATH.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            result['meets_requirements'] = False
            result['issues'].append(f"Cannot create config directory: {e}")
        
        return result
    
    def _check_firewall_status(self) -> Dict[str, any]:
        """Check Windows firewall status."""
        result = {
            'enabled': False,
            'can_configure': False,
            'profiles': {}
        }
        
        if sys.platform != 'win32':
            result['enabled'] = False  # Not Windows
            return result
        
        try:
            # Check firewall status using netsh
            cmd = ['netsh', 'advfirewall', 'show', 'allprofiles', 'state']
            process = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if process.returncode == 0:
                output = process.stdout
                # Parse firewall profiles
                for line in output.split('\n'):
                    if 'State' in line and 'ON' in line.upper():
                        result['enabled'] = True
                        break
                
                result['can_configure'] = is_admin()
            
        except Exception as e:
            log.warning(f"Could not check firewall status: {e}")
        
        return result


class SetupGuideDialog(QDialog):
    """Simplified first-run setup guide dialog."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome to PCLink!")
        self.setModal(True)
        self.resize(500, 400)
        
        self.setup_results = {}
        self.recommended_port = constants.DEFAULT_PORT
        self.needs_admin = False
        
        self._setup_ui()
        self._start_checks()
    
    def _setup_ui(self):
        """Setup the clean, modern UI components."""
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(30, 30, 30, 30)
        
        # Set dialog background to match main app
        self.setStyleSheet("""
            QDialog {
                background-color: #2e2f30;
                color: #e0e0e0;
                font-family: Segoe UI, sans-serif;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #4a4b4c;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: #242526;
                color: #e0e0e0;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
                color: #e0e0e0;
            }
        """)
        
        # Header
        header = QLabel("Welcome to PCLink!")
        header.setStyleSheet("""
            font-size: 24px; 
            font-weight: bold; 
            color: #e0e0e0;
            margin-bottom: 5px;
        """)
        layout.addWidget(header)
        
        subtitle = QLabel("Quick setup to get you connected")
        subtitle.setStyleSheet("""
            font-size: 14px; 
            color: #a0a0a0;
            margin-bottom: 20px;
        """)
        layout.addWidget(subtitle)
        
        # Progress section
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #4a4b4c;
                border-radius: 8px;
                text-align: center;
                font-weight: bold;
                background-color: #242526;
                color: #e0e0e0;
                height: 25px;
            }
            QProgressBar::chunk {
                background-color: #5a5b5c;
                border-radius: 6px;
            }
        """)
        self.progress_label = QLabel("Checking your system...")
        self.progress_label.setStyleSheet("""
            font-size: 13px; 
            color: #a0a0a0; 
            margin: 8px 0;
        """)
        
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.progress_label)
        
        # Status section (only show if there are issues)
        self.status_group = QGroupBox("Status")
        self.status_layout = QVBoxLayout(self.status_group)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("padding: 10px; line-height: 1.4;")
        self.status_layout.addWidget(self.status_label)
        self.status_group.setVisible(False)
        layout.addWidget(self.status_group)
        
        # Configuration section
        self.config_group = QGroupBox("Settings")
        config_layout = QVBoxLayout(self.config_group)
        config_layout.setSpacing(15)
        
        # Port selection (only show if there's a conflict)
        self.port_widget = QWidget()
        port_layout = QHBoxLayout(self.port_widget)
        port_layout.setContentsMargins(0, 0, 0, 0)
        
        port_label = QLabel("Server Port:")
        port_label.setStyleSheet("font-weight: bold; color: #e0e0e0;")
        self.port_spinbox = QSpinBox()
        self.port_spinbox.setRange(1024, 65535)
        self.port_spinbox.setValue(constants.DEFAULT_PORT)
        self.port_spinbox.setStyleSheet("""
            QSpinBox {
                background-color: #242526;
                border: 1px solid #4a4b4c;
                border-radius: 4px;
                padding: 6px;
                font-size: 13px;
                min-width: 80px;
                color: #e0e0e0;
            }
            QSpinBox:focus {
                border-color: #6a6b6c;
            }
        """)
        
        port_layout.addWidget(port_label)
        port_layout.addWidget(self.port_spinbox)
        port_layout.addStretch()
        self.port_widget.setVisible(False)  # Hidden by default
        config_layout.addWidget(self.port_widget)
        
        # Auto-start option
        self.auto_start_checkbox = QCheckBox("Start PCLink automatically when Windows starts")
        self.auto_start_checkbox.setChecked(True)
        self.auto_start_checkbox.setStyleSheet("""
            QCheckBox {
                font-size: 14px;
                color: #e0e0e0;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid #4a4b4c;
                border-radius: 3px;
                background-color: #242526;
            }
            QCheckBox::indicator:checked {
                background-color: #5a5b5c;
                border-color: #5a5b5c;
            }
            QCheckBox::indicator:hover {
                border-color: #6a6b6c;
            }
        """)
        config_layout.addWidget(self.auto_start_checkbox)
        
        self.config_group.setVisible(False)
        layout.addWidget(self.config_group)
        
        # Admin section (only show if actually needed)
        self.admin_group = QGroupBox("Administrator Required")
        admin_layout = QVBoxLayout(self.admin_group)
        
        admin_info = QLabel("Administrator privileges are needed to configure Windows Firewall for optimal security.")
        admin_info.setWordWrap(True)
        admin_info.setStyleSheet("""
            color: #e0e0e0; 
            font-size: 13px;
            margin-bottom: 15px;
            padding: 10px;
            background-color: #3a3b3c;
            border-radius: 4px;
            border-left: 4px solid #5a5b5c;
        """)
        admin_layout.addWidget(admin_info)
        
        self.run_as_admin_button = QPushButton("🔒 Restart as Administrator")
        self.run_as_admin_button.clicked.connect(self._run_as_admin)
        self.run_as_admin_button.setStyleSheet("""
            QPushButton {
                background-color: #5a5b5c;
                color: #e0e0e0;
                border: none;
                padding: 12px 20px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #6a6b6c;
            }
            QPushButton:pressed {
                background-color: #4a4b4c;
            }
        """)
        admin_layout.addWidget(self.run_as_admin_button)
        
        self.admin_group.setVisible(False)
        layout.addWidget(self.admin_group)
        
        layout.addStretch()
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(15)
        
        # Skip button (only shown when there are issues)
        self.skip_button = QPushButton("Skip Setup")
        self.skip_button.setStyleSheet("""
            QPushButton {
                background-color: #3a3b3c;
                color: #a0a0a0;
                border: 1px solid #4a4b4c;
                padding: 10px 20px;
                border-radius: 4px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #4a4b4c;
                color: #e0e0e0;
            }
        """)
        self.skip_button.clicked.connect(self.reject)
        self.skip_button.setVisible(False)  # Hidden by default
        button_layout.addWidget(self.skip_button)
        
        button_layout.addStretch()
        
        self.finish_button = QPushButton("✓ Complete Setup")
        self.finish_button.setStyleSheet("""
            QPushButton {
                background-color: #5a5b5c;
                color: #e0e0e0;
                border: none;
                padding: 12px 25px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #6a6b6c;
            }
            QPushButton:pressed {
                background-color: #4a4b4c;
            }
            QPushButton:disabled {
                background-color: #404040;
                color: #888;
            }
        """)
        self.finish_button.clicked.connect(self._finish_setup)
        self.finish_button.setEnabled(False)
        button_layout.addWidget(self.finish_button)
        
        layout.addLayout(button_layout)
    
    def _start_checks(self):
        """Start the system checks."""
        ports_to_check = [
            constants.DEFAULT_PORT,
            constants.DEFAULT_PORT + 1,
            constants.DEFAULT_PORT + 2,
            38099  # Discovery port
        ]
        
        self.checker = PortChecker(ports_to_check)
        self.checker.progress_updated.connect(self._update_progress)
        self.checker.check_completed.connect(self._handle_check_results)
        self.checker.start()
    
    def _update_progress(self, progress: int, message: str):
        """Update progress bar and message."""
        self.progress_bar.setValue(progress)
        self.progress_label.setText(message)
    
    def _handle_check_results(self, results: Dict):
        """Handle the completion of system checks."""
        self.setup_results = results
        self._display_simple_results()
        self._show_configuration()
        
        # Enable finish button
        self.finish_button.setEnabled(True)
    
    def _display_simple_results(self):
        """Display simplified results focusing on what the user needs to know."""
        status_messages = []
        has_issues = False
        
        # Check for critical issues
        system = self.setup_results.get('system', {})
        if not system.get('meets_requirements', True):
            has_issues = True
            status_messages.append("❌ System requirements not met")
            for issue in system.get('issues', []):
                status_messages.append(f"   • {issue}")
        
        # Check ports and recommend one
        ports = self.setup_results.get('ports', {})
        available_ports = [port for port, info in ports.items() if info.get('available', False)]
        
        if available_ports:
            self.recommended_port = min(available_ports)
            self.port_spinbox.setValue(self.recommended_port)
            if self.recommended_port != constants.DEFAULT_PORT:
                status_messages.append(f"ℹ️ Using port {self.recommended_port} (default port was busy)")
                self.port_widget.setVisible(True)
        else:
            has_issues = True
            status_messages.append("⚠️ Default port is busy - you may need to choose a different port")
            self.port_widget.setVisible(True)
            # Find a random available port
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('', 0))
                available_port = s.getsockname()[1]
                self.port_spinbox.setValue(available_port)
                self.recommended_port = available_port
        
        # Check if admin is actually needed - only if firewall is blocking AND we don't have admin
        firewall = self.setup_results.get('firewall', {})
        has_admin = self.setup_results.get('admin', False)
        firewall_enabled = firewall.get('enabled', False)
        ports = self.setup_results.get('ports', {})
        
        # Check if the recommended port is actually blocked
        port_is_blocked = not ports.get(self.recommended_port, {}).get('available', True)
        
        # Only show admin button if:
        # 1. Windows Firewall is enabled AND
        # 2. We don't have admin privileges AND  
        # 3. The port we want to use is actually blocked AND
        # 4. We're on Windows
        if (firewall_enabled and not has_admin and port_is_blocked and sys.platform == 'win32'):
            self.needs_admin = True
            status_messages.append("⚠️ Windows Firewall may be blocking the port - administrator access recommended")
            self.admin_group.setVisible(True)
        else:
            # No need for admin - port is available or firewall isn't the issue
            self.admin_group.setVisible(False)
        
        # Show status only if there are issues or important info
        if status_messages:
            self.status_group.setVisible(True)
            self.status_label.setText('\n'.join(status_messages))
            
            # Style based on severity
            if has_issues:
                self.status_label.setStyleSheet("""
                    color: #e0e0e0; 
                    font-size: 14px;
                    line-height: 1.5;
                    background-color: #3a3b3c;
                    border-left: 4px solid #5a5b5c;
                    padding: 12px;
                    border-radius: 4px;
                """)
            else:
                self.status_label.setStyleSheet("""
                    color: #e0e0e0; 
                    font-size: 14px;
                    line-height: 1.5;
                    background-color: #3a3b3c;
                    border-left: 4px solid #5a5b5c;
                    padding: 12px;
                    border-radius: 4px;
                """)
        
        # Update button behavior based on issues
        if has_issues or self.needs_admin:
            # Show skip button when there are issues user might want to bypass
            self.skip_button.setVisible(True)
            self.finish_button.setText("✓ Complete Setup")
        else:
            # Hide skip button when everything is perfect
            self.skip_button.setVisible(False)
            self.finish_button.setText("✓ Continue")
        
        # Update progress
        self.progress_bar.setValue(100)
        if has_issues:
            self.progress_label.setText("⚠️ Setup ready - please review the items above")
            self.progress_label.setStyleSheet("""
                font-size: 13px; 
                color: #e0e0e0; 
                margin: 8px 0;
                font-weight: bold;
            """)
        else:
            self.progress_label.setText("✅ All good! Ready to continue")
            self.progress_label.setStyleSheet("""
                font-size: 13px; 
                color: #e0e0e0; 
                margin: 8px 0;
                font-weight: bold;
            """)
    
    def _show_configuration(self):
        """Show configuration options."""
        self.config_group.setVisible(True)
    
    def _run_as_admin(self):
        """Restart the application as administrator."""
        try:
            from .utils import restart_as_admin
            
            reply = QMessageBox.question(
                self,
                "Restart as Administrator",
                "PCLink will restart with administrator privileges to complete the setup.\n\n"
                "Continue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            
            if reply == QMessageBox.Yes:
                # Mark that we're in setup mode for the restarted instance
                import os
                os.environ['PCLINK_SETUP_MODE'] = '1'
                restart_as_admin()
                # This will exit the current process
                
        except Exception as e:
            log.error(f"Failed to restart as admin: {e}")
            QMessageBox.critical(
                self,
                "Restart Failed",
                f"Could not restart as administrator: {e}\n\n"
                f"You can continue with limited functionality or restart PCLink manually as administrator."
            )
    
    def _finish_setup(self):
        """Complete the setup process."""
        try:
            # Save port configuration
            selected_port = self.port_spinbox.value()
            save_config_value(constants.PORT_FILE, str(selected_port))
            
            # Configure auto-start
            if self.auto_start_checkbox.isChecked():
                self._configure_auto_start()
            
            # Mark setup as completed
            setup_completed_file = constants.APP_DATA_PATH / ".setup_completed"
            setup_completed_file.write_text("1")
            
            # Create a custom success message box
            success_msg = QMessageBox(self)
            success_msg.setWindowTitle("Setup Complete!")
            success_msg.setIcon(QMessageBox.Information)
            success_msg.setText("🎉 PCLink is ready to use!")
            
            details = f"Configuration:\n"
            details += f"• Server running on port {selected_port}\n"
            details += f"• Auto-start: {'Enabled' if self.auto_start_checkbox.isChecked() else 'Disabled'}\n\n"
            details += f"Next steps:\n"
            details += f"• Download the PCLink mobile app\n"
            details += f"• Scan the QR code to connect your device\n"
            details += f"• Start controlling your PC remotely!"
            
            success_msg.setInformativeText(details)
            success_msg.setStandardButtons(QMessageBox.Ok)
            success_msg.setStyleSheet("""
                QMessageBox {
                    background-color: #3a3b3c;
                }
                QMessageBox QLabel {
                    color: #e0e0e0;
                    font-size: 14px;
                }
            """)
            success_msg.exec()
            
            self.accept()
            
        except Exception as e:
            log.error(f"Setup completion failed: {e}", exc_info=True)
            QMessageBox.critical(
                self,
                "Setup Failed",
                f"Failed to complete setup: {e}"
            )
    
    def _configure_auto_start(self):
        """Configure auto-start with Windows."""
        try:
            from .utils import get_startup_manager
            import sys
            from pathlib import Path
            
            startup_manager = get_startup_manager()
            exe_path = Path(sys.executable).resolve()
            startup_manager.add(constants.APP_NAME, exe_path)
            log.info("Auto-start configured successfully")
        except Exception as e:
            log.error(f"Failed to configure auto-start: {e}")
            QMessageBox.warning(
                self,
                "Auto-start Configuration Failed",
                f"Could not configure auto-start: {e}\n\n"
                f"You can manually add PCLink to Windows startup later."
            )
    



def should_show_setup_guide() -> bool:
    """Check if the setup guide should be shown."""
    setup_completed_file = constants.APP_DATA_PATH / ".setup_completed"
    return not setup_completed_file.exists()


def show_setup_guide(parent=None) -> bool:
    """Show the setup guide dialog."""
    dialog = SetupGuideDialog(parent)
    return dialog.exec() == QDialog.Accepted