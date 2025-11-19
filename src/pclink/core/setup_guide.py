# src/pclink/core/setup_guide.py
#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import constants
from .utils import load_config_value, save_config_value, is_admin

log = logging.getLogger(__name__)


class PortChecker:
    """Class for checking port availability and system requirements."""
    
    def __init__(self, ports_to_check: List[int]):
        self.ports_to_check = ports_to_check
        self.results = {}
    
    def run_checks(self) -> Dict:
        """Run port checks and system validation."""
        log.info("Running system checks...")
        
        # Check system requirements
        log.info("Checking system requirements...")
        self.results['system'] = self._check_system_requirements()
        
        # Check firewall status
        log.info("Checking firewall status...")
        self.results['firewall'] = self._check_firewall_status()
        
        # Check admin privileges
        log.info("Checking admin privileges...")
        self.results['admin'] = is_admin()
        
        # Check ports
        port_results = {}
        for port in self.ports_to_check:
            log.info(f"Checking port {port}...")
            port_results[port] = self._check_port(port)
        
        self.results['ports'] = port_results
        return self.results
    
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


def run_setup_checks() -> Dict:
    """Run setup checks and return results."""
    ports_to_check = [
        constants.DEFAULT_PORT,
        constants.DEFAULT_PORT + 1,
        constants.DEFAULT_PORT + 2,
        38099  # Discovery port
    ]
    
    checker = PortChecker(ports_to_check)
    return checker.run_checks()


def configure_auto_start():
    """Configure auto-start with Windows."""
    try:
        from .utils import get_startup_manager
        import sys
        from pathlib import Path
        
        startup_manager = get_startup_manager()
        exe_path = Path(sys.executable).resolve()
        startup_manager.add(constants.APP_NAME, exe_path)
        log.info("Auto-start configured successfully")
        return True
    except Exception as e:
        log.error(f"Failed to configure auto-start: {e}")
        return False


def complete_setup(port: int = None, enable_auto_start: bool = True) -> bool:
    """Complete the setup process with given configuration."""
    try:
        # Use default port if none specified
        if port is None:
            port = constants.DEFAULT_PORT
        
        # Save port configuration
        save_config_value(constants.PORT_FILE, str(port))
        log.info(f"Port configured: {port}")
        
        # Configure auto-start if requested
        if enable_auto_start:
            if configure_auto_start():
                log.info("Auto-start enabled")
            else:
                log.warning("Auto-start configuration failed")
        
        # Mark setup as completed
        setup_completed_file = constants.APP_DATA_PATH / ".setup_completed"
        setup_completed_file.write_text("1")
        log.info("Setup marked as completed")
        
        return True
        
    except Exception as e:
        log.error(f"Setup completion failed: {e}", exc_info=True)
        return False
    



def should_show_setup_guide() -> bool:
    """Check if the setup guide should be shown."""
    setup_completed_file = constants.APP_DATA_PATH / ".setup_completed"
    return not setup_completed_file.exists()


def show_setup_guide(parent=None) -> bool:
    """Run the console-based setup guide."""
    print("\n" + "="*60)
    print("🎉 Welcome to PCLink!")
    print("="*60)
    print("Quick setup to get you connected\n")
    
    # Run system checks
    print("Running system checks...")
    results = run_setup_checks()
    
    # Analyze results
    system = results.get('system', {})
    ports = results.get('ports', {})
    firewall = results.get('firewall', {})
    has_admin = results.get('admin', False)
    
    # Check for critical issues
    if not system.get('meets_requirements', True):
        print("❌ System requirements not met:")
        for issue in system.get('issues', []):
            print(f"   • {issue}")
        return False
    
    # Find available port
    available_ports = [port for port, info in ports.items() if info.get('available', False)]
    
    if available_ports:
        recommended_port = min(available_ports)
        if recommended_port != constants.DEFAULT_PORT:
            print(f"ℹ️  Using port {recommended_port} (default port was busy)")
    else:
        print("⚠️  Default port is busy - finding alternative...")
        # Find a random available port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            recommended_port = s.getsockname()[1]
        print(f"ℹ️  Using port {recommended_port}")
    
    # Check firewall
    if firewall.get('enabled', False) and not has_admin and sys.platform == 'win32':
        print("⚠️  Windows Firewall is enabled - you may need administrator privileges")
        print("   for optimal security configuration.")
    
    print("\n" + "-"*60)
    print("Configuration:")
    print(f"• Server port: {recommended_port}")
    print("• Auto-start: Enabled")
    print("-"*60)
    
    # Complete setup
    if complete_setup(port=recommended_port, enable_auto_start=True):
        print("\n✅ Setup completed successfully!")
        print("\nNext steps:")
        print("• Download the PCLink mobile app")
        print("• Scan the QR code to connect your device")
        print("• Start controlling your PC remotely!")
        print("\n" + "="*60 + "\n")
        return True
    else:
        print("\n❌ Setup failed. Please check the logs for details.")
        return False