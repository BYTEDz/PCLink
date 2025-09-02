# filename: src/pclink/core/utils.py
"""
PCLink - Remote PC Control Server - Utilities Module
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
import os
import subprocess
import socket
import sys
from pathlib import Path
from typing import Callable, List, Optional, Union

import psutil

from . import constants

if sys.platform == "win32":
    import ctypes
    import winreg

log = logging.getLogger(__name__)


def run_preflight_checks():
    """
    Run essential one-time setup tasks before the application starts.
    This includes creating directories and generating security certificates.
    """
    constants.initialize_app_directories()
    generate_self_signed_cert(constants.CERT_FILE, constants.KEY_FILE)


def get_app_data_path(app_name: str) -> Path:
    """
    Returns the platform-specific application data directory path.

    This function does NOT create the directory.
    """
    if sys.platform == "win32":
        path = Path(os.environ["APPDATA"]) / app_name
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / app_name
    else:
        path = Path.home() / ".config" / app_name
    return path


def is_admin() -> bool:
    """Check if the current process is running with administrator privileges"""
    if sys.platform == "win32":
        try:
            return ctypes.windll.shell32.IsUserAnAdmin()
        except:
            return False
    else:
        return os.geteuid() == 0


def check_firewall_rule_exists(rule_name: str) -> bool:
    """Check if a Windows Firewall rule exists"""
    if sys.platform != "win32":
        return True  # Assume no firewall issues on non-Windows
    
    try:
        result = subprocess.run([
            'netsh', 'advfirewall', 'firewall', 'show', 'rule', 
            f'name={rule_name}'
        ], capture_output=True, text=True, timeout=10)
        
        return result.returncode == 0 and rule_name in result.stdout
    except:
        return False


def add_firewall_rule(rule_name: str, port: int, protocol: str = "UDP", direction: str = "out") -> tuple[bool, str]:
    """
    Add a Windows Firewall rule
    Returns (success, message)
    """
    if sys.platform != "win32":
        return True, "Firewall rules not needed on this platform"
    
    try:
        cmd = [
            'netsh', 'advfirewall', 'firewall', 'add', 'rule',
            f'name={rule_name}',
            f'dir={direction}',
            'action=allow',
            f'protocol={protocol}',
            f'localport={port}'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            return True, f"Firewall rule '{rule_name}' added successfully"
        else:
            return False, f"Failed to add firewall rule: {result.stderr.strip()}"
            
    except subprocess.TimeoutExpired:
        return False, "Firewall command timed out"
    except Exception as e:
        return False, f"Error adding firewall rule: {str(e)}"


def restart_as_admin(script_path: str = None) -> bool:
    """Restart the current application with administrator privileges"""
    if sys.platform != "win32":
        return False
    
    try:
        if script_path is None:
            script_path = sys.executable
            params = ' '.join(sys.argv)
        else:
            params = script_path
        
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params, None, 1
        )
        return True
    except:
        return False


def resource_path(relative_path: Union[str, Path]) -> Path:
    """
    Get the absolute path to a resource, supporting both development and PyInstaller.
    """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        # Assets are bundled as src/pclink/assets in the PyInstaller bundle
        base_path = Path(sys._MEIPASS) / "src" / "pclink"
    except AttributeError:
        # Not in a PyInstaller bundle, use the pclink package directory
        # This file is in src/pclink/core/utils.py, so parent gives us src/pclink/
        base_path = Path(__file__).parent.parent.resolve()
    return base_path / relative_path


def get_available_ips() -> List[str]:
    """
    Gets a list of all non-loopback IPv4 addresses on the host.

    Returns a sorted list of IP addresses, prioritizing local network IPs.
    """
    local_ips, other_ips = [], []
    try:
        for iface, addrs in psutil.net_if_addrs().items():
            # Ignore virtual or loopback-like interfaces
            if (
                "virtual" in iface.lower()
                or "vmnet" in iface.lower()
                or "loopback" in iface.lower()
            ):
                continue
            for addr in addrs:
                if addr.family == socket.AF_INET and not addr.address.startswith(
                    "127."
                ):
                    # Prioritize common private IP ranges
                    if addr.address.startswith(("192.168.", "10.", "172.")):
                        local_ips.append(addr.address)
                    else:
                        other_ips.append(addr.address)
    except Exception as e:
        log.error(f"Could not get IP addresses using psutil: {e}")

    # Combine and remove duplicates, keeping order
    sorted_ips = sorted(list(set(local_ips))) + sorted(list(set(other_ips)))

    # Fallback if psutil fails to find any IPs
    if not sorted_ips:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
                if ip and ip != "0.0.0.0":
                    sorted_ips.append(ip)
        except Exception as e:
            log.error(f"Socket fallback for IP address failed: {e}")

    # Final fallback
    if not sorted_ips:
        log.warning("Could not determine any valid IP address, defaulting to 127.0.0.1")
        return ["127.0.0.1"]

    return sorted_ips


def is_admin() -> bool:
    """Check if the current user has administrative privileges."""
    try:
        if sys.platform == "win32":
            return ctypes.windll.shell32.IsUserAnAdmin() == 1
        return os.getuid() == 0
    except Exception as e:
        log.error(f"Failed to check admin status: {e}")
        return False


def restart_as_admin():
    """
    Restarts the application with administrator privileges on Windows.

    Note: The calling process is responsible for quitting itself after
    calling this function.
    """
    if sys.platform != "win32":
        log.warning("Restarting as admin is only supported on Windows.")
        return

    try:
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, " ".join(sys.argv), None, 1
        )
    except Exception as e:
        log.error(f"Failed to execute ShellExecuteW for elevation: {e}")


def generate_self_signed_cert(cert_path: Path, key_path: Path):
    """Generates a self-signed certificate and private key if they don't exist."""
    if cert_path.exists() and key_path.exists():
        log.debug(f"Certificate and key already exist at {cert_path} and {key_path}")
        # Verify the existing certificate is valid
        try:
            fingerprint = get_cert_fingerprint(cert_path)
            if fingerprint:
                log.debug("Existing certificate is valid")
                return
            else:
                log.warning("Existing certificate is invalid, regenerating...")
        except Exception as e:
            log.warning(f"Error validating existing certificate: {e}, regenerating...")

    try:
        import datetime
        import ipaddress

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError as e:
        log.error(f"Cryptography library is required. Please run 'pip install cryptography': {e}")
        raise

    try:
        log.info(f"Generating new self-signed certificate at {cert_path}")
        
        # Generate private key
        log.debug("Generating RSA private key...")
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        
        # Ensure directories exist
        key_path.parent.mkdir(parents=True, exist_ok=True)
        cert_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write private key
        log.debug(f"Writing private key to {key_path}")
        with key_path.open("wb") as f:
            f.write(
                key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            )

        # Create certificate
        log.debug("Creating certificate...")
        subject = issuer = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, "PCLink Self-Signed")]
        )
        
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(
                x509.SubjectAlternativeName([
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.IPv4Address("127.0.0.1"))
                ]), 
                critical=False
            )
            .sign(key, hashes.SHA256())
        )

        # Write certificate
        log.debug(f"Writing certificate to {cert_path}")
        with cert_path.open("wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        
        # Verify the generated certificate
        fingerprint = get_cert_fingerprint(cert_path)
        if fingerprint:
            log.info(f"Successfully generated certificate with fingerprint: {fingerprint[:16]}...")
        else:
            log.error("Generated certificate appears to be invalid")
            raise Exception("Certificate validation failed after generation")
            
    except Exception as e:
        log.error(f"Failed to generate self-signed certificate: {e}", exc_info=True)
        # Clean up partial files
        try:
            if cert_path.exists():
                cert_path.unlink()
            if key_path.exists():
                key_path.unlink()
        except Exception as cleanup_error:
            log.error(f"Failed to clean up partial certificate files: {cleanup_error}")
        raise


def get_cert_fingerprint(cert_path: Path) -> Optional[str]:
    """Calculate the SHA-256 fingerprint of a certificate."""
    if not cert_path.is_file():
        log.error(f"Certificate file does not exist: {cert_path}")
        return None
    
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes

        log.debug(f"Reading certificate from: {cert_path}")
        cert_data = cert_path.read_bytes()
        
        if not cert_data:
            log.error(f"Certificate file is empty: {cert_path}")
            return None
        
        log.debug(f"Loading PEM certificate, size: {len(cert_data)} bytes")
        cert = x509.load_pem_x509_certificate(cert_data)
        
        log.debug("Calculating SHA-256 fingerprint")
        fingerprint = cert.fingerprint(hashes.SHA256())
        fingerprint_hex = fingerprint.hex()
        
        log.debug(f"Certificate fingerprint calculated: {fingerprint_hex[:16]}...")
        return fingerprint_hex
        
    except ImportError as e:
        log.error(f"Cryptography library not available: {e}")
        return None
    except Exception as e:
        log.error(f"Error calculating cert fingerprint for {cert_path}: {e}", exc_info=True)
        return None


class _StartupManager:
    """Abstract base class for platform-specific startup managers."""

    def add(self, app_name: str, exe_path: Path):
        raise NotImplementedError

    def remove(self, app_name: str):
        raise NotImplementedError

    def is_enabled(self, app_name: str) -> bool:
        raise NotImplementedError


class _WindowsStartupManager(_StartupManager):
    def __init__(self):
        self.key = winreg.HKEY_CURRENT_USER
        self.key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"

    def add(self, app_name: str, exe_path: Path):
        # Enhanced Windows 11 compatibility with multiple startup methods
        if getattr(sys, "frozen", False):
            # Running as PyInstaller executable
            command = f'"{exe_path}" --startup'
            log.info(f"Configuring PyInstaller executable for startup: {command}")
        else:
            # Running as Python script
            command = f'"{exe_path}" --startup'
        
        # Method 1: Registry (traditional method)
        registry_success = self._add_to_registry(app_name, command)
        
        # Method 2: Windows Startup folder (Windows 11 fallback)
        shortcut_success = self._add_to_startup_folder(app_name, exe_path)
        
        # Method 3: Task Scheduler (most reliable for Windows 11)
        task_success = self._add_to_task_scheduler(app_name, exe_path)
        
        if not (registry_success or shortcut_success or task_success):
            raise OSError("Failed to add to startup using any method")
        
        log.info(f"Added '{app_name}' to Windows startup using available methods")

    def _add_to_registry(self, app_name: str, command: str) -> bool:
        """Add to Windows registry startup."""
        try:
            with winreg.OpenKey(
                self.key, self.key_path, 0, winreg.KEY_SET_VALUE
            ) as reg_key:
                winreg.SetValueEx(reg_key, app_name, 0, winreg.REG_SZ, command)
            log.info(f"Added '{app_name}' to registry startup")
            return True
        except OSError as e:
            log.warning(f"Failed to add to registry startup: {e}")
            return False

    def _add_to_startup_folder(self, app_name: str, exe_path: Path) -> bool:
        """Add shortcut to Windows startup folder (Windows 11 preferred)."""
        try:
            startup_folder = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
            startup_folder.mkdir(parents=True, exist_ok=True)
            
            shortcut_path = startup_folder / f"{app_name}.lnk"
            
            # Method 1: Try using win32com.client (if available)
            try:
                import win32com.client
                shell = win32com.client.Dispatch("WScript.Shell")
                shortcut = shell.CreateShortCut(str(shortcut_path))
                shortcut.Targetpath = str(exe_path)
                shortcut.Arguments = "--startup"
                shortcut.WorkingDirectory = str(exe_path.parent)
                shortcut.save()
                
                if shortcut_path.exists():
                    log.info(f"Added '{app_name}' shortcut to startup folder using win32com")
                    return True
                    
            except ImportError:
                log.debug("win32com not available, trying alternative method")
            except Exception as e:
                log.warning(f"win32com method failed: {e}")
            
            # Method 2: Create a simple batch file instead of shortcut
            batch_path = startup_folder / f"{app_name}.bat"
            batch_content = f'@echo off\nstart "" "{exe_path}" --startup\n'
            
            try:
                with open(batch_path, 'w') as f:
                    f.write(batch_content)
                
                if batch_path.exists():
                    log.info(f"Added '{app_name}' batch file to startup folder")
                    return True
                    
            except Exception as e:
                log.warning(f"Batch file method failed: {e}")
            
            # Method 3: Copy executable to startup folder (simple but works)
            try:
                import shutil
                startup_exe = startup_folder / f"{app_name}.exe"
                
                # Create a simple wrapper script
                wrapper_content = f'''import subprocess
import sys
subprocess.run([r"{exe_path}", "--startup"])
'''
                wrapper_path = startup_folder / f"{app_name}_startup.py"
                with open(wrapper_path, 'w') as f:
                    f.write(wrapper_content)
                
                # Create batch file to run the Python wrapper
                batch_path = startup_folder / f"{app_name}.bat"
                batch_content = f'@echo off\npython "{wrapper_path}"\n'
                with open(batch_path, 'w') as f:
                    f.write(batch_content)
                
                if batch_path.exists():
                    log.info(f"Added '{app_name}' Python wrapper to startup folder")
                    return True
                    
            except Exception as e:
                log.warning(f"Python wrapper method failed: {e}")
            
            return False
                
        except Exception as e:
            log.warning(f"Failed to add to startup folder: {e}")
            return False

    def _add_to_task_scheduler(self, app_name: str, exe_path: Path) -> bool:
        """Add to Windows Task Scheduler (most reliable for Windows 11)."""
        try:
            # Create a scheduled task that runs at logon
            task_name = f"PCLink_{app_name}"
            
            # XML for the scheduled task
            task_xml = f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>PCLink Remote PC Control Server</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <Delay>PT10S</Delay>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions>
    <Exec>
      <Command>{exe_path}</Command>
      <Arguments>--startup</Arguments>
      <WorkingDirectory>{exe_path.parent}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>'''
            
            # Save task XML to temp file
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
                f.write(task_xml)
                temp_xml = f.name
            
            try:
                # Create the scheduled task
                result = subprocess.run([
                    "schtasks", "/create", "/tn", task_name, "/xml", temp_xml, "/f"
                ], capture_output=True, text=True, timeout=15)
                
                if result.returncode == 0:
                    log.info(f"Added '{app_name}' to Task Scheduler")
                    return True
                else:
                    log.warning(f"Failed to create scheduled task: {result.stderr}")
                    return False
                    
            finally:
                # Clean up temp file
                try:
                    Path(temp_xml).unlink()
                except:
                    pass
                    
        except Exception as e:
            log.warning(f"Failed to add to Task Scheduler: {e}")
            return False

    def remove(self, app_name: str):
        """Remove from all startup methods."""
        removed_any = False
        
        # Remove from registry
        try:
            with winreg.OpenKey(
                self.key, self.key_path, 0, winreg.KEY_SET_VALUE
            ) as reg_key:
                winreg.DeleteValue(reg_key, app_name)
            log.info(f"Removed '{app_name}' from registry startup.")
            removed_any = True
        except FileNotFoundError:
            log.debug(f"'{app_name}' not in registry startup.")
        except OSError as e:
            log.warning(f"Failed to remove from registry startup: {e}")
        
        # Remove from startup folder (multiple file types)
        try:
            startup_folder = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
            
            # Remove .lnk shortcut
            shortcut_path = startup_folder / f"{app_name}.lnk"
            if shortcut_path.exists():
                shortcut_path.unlink()
                log.info(f"Removed '{app_name}' shortcut from startup folder.")
                removed_any = True
            
            # Remove .bat batch file
            batch_path = startup_folder / f"{app_name}.bat"
            if batch_path.exists():
                batch_path.unlink()
                log.info(f"Removed '{app_name}' batch file from startup folder.")
                removed_any = True
            
            # Remove Python wrapper
            wrapper_path = startup_folder / f"{app_name}_startup.py"
            if wrapper_path.exists():
                wrapper_path.unlink()
                log.info(f"Removed '{app_name}' Python wrapper from startup folder.")
                removed_any = True
                
        except Exception as e:
            log.warning(f"Failed to remove startup files: {e}")
        
        # Remove from Task Scheduler
        try:
            task_name = f"PCLink_{app_name}"
            result = subprocess.run([
                "schtasks", "/delete", "/tn", task_name, "/f"
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                log.info(f"Removed '{app_name}' from Task Scheduler.")
                removed_any = True
        except Exception as e:
            log.warning(f"Failed to remove from Task Scheduler: {e}")
        
        if not removed_any:
            log.debug(f"'{app_name}' not found in any startup location.")

    def is_enabled(self, app_name: str) -> bool:
        """Check if enabled in any startup method."""
        # Check registry
        try:
            with winreg.OpenKey(self.key, self.key_path, 0, winreg.KEY_READ) as reg_key:
                winreg.QueryValueEx(reg_key, app_name)
            return True
        except FileNotFoundError:
            pass
        
        # Check startup folder (multiple file types)
        try:
            startup_folder = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
            
            # Check for .lnk shortcut
            shortcut_path = startup_folder / f"{app_name}.lnk"
            if shortcut_path.exists():
                return True
            
            # Check for .bat batch file
            batch_path = startup_folder / f"{app_name}.bat"
            if batch_path.exists():
                return True
            
            # Check for Python wrapper
            wrapper_path = startup_folder / f"{app_name}_startup.py"
            if wrapper_path.exists():
                return True
                
        except:
            pass
        
        # Check Task Scheduler
        try:
            task_name = f"PCLink_{app_name}"
            result = subprocess.run([
                "schtasks", "/query", "/tn", task_name
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                return True
        except:
            pass
        
        return False


class _LinuxStartupManager(_StartupManager):
    def __init__(self):
        self.autostart_path = Path.home() / ".config" / "autostart"

    def _get_desktop_file(self, app_name: str) -> Path:
        return self.autostart_path / f"{app_name.lower()}.desktop"

    def add(self, app_name: str, exe_path: Path):
        self.autostart_path.mkdir(parents=True, exist_ok=True)
        desktop_file = self._get_desktop_file(app_name)
        icon_path = resource_path("assets/icon.png")
        desktop_entry = (
            f"[Desktop Entry]\n"
            f"Type=Application\n"
            f"Name={app_name}\n"
            f'Exec="{exe_path}" --startup\n'
            f"Comment={app_name} Remote Control Server\n"
            f"Icon={icon_path}\n"
            f"X-GNOME-Autostart-enabled=true\n"
        )
        try:
            desktop_file.write_text(desktop_entry, encoding="utf-8")
            log.info(f"Added '{app_name}' to Linux startup at {desktop_file}.")
        except IOError as e:
            log.error(f"Failed to write desktop entry file: {e}")
            raise

    def remove(self, app_name: str):
        desktop_file = self._get_desktop_file(app_name)
        try:
            desktop_file.unlink(missing_ok=True)
            log.info(f"Removed '{app_name}' from Linux startup.")
        except IOError as e:
            log.error(f"Failed to remove startup file: {e}")
            raise

    def is_enabled(self, app_name: str) -> bool:
        return self._get_desktop_file(app_name).exists()


class _UnsupportedStartupManager(_StartupManager):
    def add(self, app_name: str, exe_path: Path):
        log.warning(f"Startup management not supported on '{sys.platform}'.")

    def remove(self, app_name: str):
        log.warning(f"Startup management not supported on '{sys.platform}'.")

    def is_enabled(self, app_name: str) -> bool:
        return False


def get_startup_manager() -> _StartupManager:
    """Factory function to get the correct startup manager for the current OS."""
    if sys.platform == "win32":
        return _WindowsStartupManager()
    if sys.platform == "linux":
        return _LinuxStartupManager()
    return _UnsupportedStartupManager()


def load_config_value(
    file_path: Path, default: Union[str, Callable[[], str]] = ""
) -> str:
    """Loads a string value from a file, creating it with a default if it doesn't exist."""
    try:
        if file_path.is_file():
            return file_path.read_text(encoding="utf-8").strip()
    except IOError as e:
        log.warning(f"Could not read config file {file_path}, using default: {e}")

    # File doesn't exist or was unreadable, create it with the default value
    default_value = default() if callable(default) else default
    save_config_value(file_path, default_value)
    return str(default_value)


def save_config_value(file_path: Path, value: Union[str, int]):
    """Saves a string value to a file, creating parent directories if needed."""
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(str(value), encoding="utf-8")
    except IOError as e:
        log.error(f"Could not write to config file {file_path}: {e}")
        raise


class DummyTty:
    """A dummy TTY-like object for environments where sys.stdout is None."""

    def isatty(self) -> bool:
        return False

    def write(self, msg: str):
        pass

    def flush(self):
        pass
    
    def readline(self):
        return ""
    
    def readlines(self):
        return []
    
    def close(self):
        pass
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        pass