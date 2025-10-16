# src/pclink/core/utils.py

import logging
import os
import shutil
import subprocess
import socket
import sys
from pathlib import Path
from typing import Callable, List, Optional, Union
import importlib.resources  # Keep this import

import psutil
from . import constants

if sys.platform == "win32":
    import ctypes
    import winreg

log = logging.getLogger(__name__)


# --- NEW, UNIVERSAL resource_path FUNCTION ---
def resource_path(relative_path: Union[str, Path]) -> Path:
    """
    Get the absolute path to a resource, working correctly for:
    1. Development environment (running from source)
    2. PyInstaller bundle (frozen executable)
    3. Standard package installation (e.g., via a .deb file)
    """
    # Case 1: Running in a PyInstaller bundle
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / relative_path

    # Determine the project root by looking for a known file (pyproject.toml)
    # This reliably detects if we are running from the source tree.
    try:
        # __file__ is src/pclink/core/utils.py
        # .parent -> core
        # .parent -> pclink
        # .parent -> src
        # .parent -> project root
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        is_dev_mode = (project_root / 'pyproject.toml').exists()
    except Exception:
        is_dev_mode = False

    # Case 2: Running in a development environment (from source)
    if is_dev_mode:
        return project_root / relative_path

    # Case 3: Running as an installed package (e.g., from .deb)
    # The relative path should be from inside the 'pclink' package folder
    try:
        # We need to strip the 'src/pclink/' part for this to work
        # e.g., "src/pclink/assets/icon.png" -> "assets/icon.png"
        path_parts = Path(relative_path).parts
        if 'pclink' in path_parts:
            # Find the index of 'pclink' and take everything after it
            pclink_index = path_parts.index('pclink')
            package_relative_path = Path(*path_parts[pclink_index + 1:])
        else:
            package_relative_path = Path(relative_path)

        return importlib.resources.files('pclink') / package_relative_path
    except Exception as e:
        log.error(f"Could not find resource path using importlib.resources for '{relative_path}': {e}")
        # A final, desperate fallback
        return Path(relative_path)

# --- All other functions in this file remain the same ---
# (The rest of the file is unchanged, you only need to replace the function above)
def run_preflight_checks():
    # ... (no changes)
    try:
        constants.initialize_app_directories()
        generate_self_signed_cert(constants.CERT_FILE, constants.KEY_FILE)
        return True
    except Exception as e:
        logging.getLogger(__name__).error(f"Preflight checks failed: {e}")
        return False

# ... (rest of the file is unchanged)



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

def get_available_ips() -> List[str]:
    """
    Gets a list of all non-loopback IPv4 addresses on the host.

    Returns a sorted list of IP addresses, prioritizing local network IPs.
    """
    local_ips, other_ips = [], []
    
    try:
        for iface, addrs in psutil.net_if_addrs().items():
            # Enhanced Linux interface filtering
            if (
                "virtual" in iface.lower()
                or "vmnet" in iface.lower()
                or "loopback" in iface.lower()
                or iface.startswith(('lo', 'docker', 'br-', 'veth', 'virbr'))
                or "tun" in iface.lower()
                or "tap" in iface.lower()
            ):
                continue
                
            # Check if interface is up (Linux-specific)
            try:
                interface_stats = psutil.net_if_stats().get(iface)
                if interface_stats and not interface_stats.isup:
                    continue
            except (AttributeError, KeyError):
                pass  # Interface stats not available, continue anyway
                
            for addr in addrs:
                if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                    # Skip invalid or link-local addresses
                    if (addr.address.startswith(("169.254.", "0.")) or 
                        addr.address.endswith(".0") or 
                        addr.address.endswith(".255")):
                        continue
                        
                    # Prioritize common private IP ranges
                    if addr.address.startswith(("192.168.", "10.", "172.")):
                        if addr.address not in local_ips:
                            local_ips.append(addr.address)
                    else:
                        if addr.address not in other_ips:
                            other_ips.append(addr.address)
                            
    except Exception as e:
        log.error(f"Could not get IP addresses using psutil: {e}")

    # Linux-specific: Try alternative methods if psutil fails
    if not local_ips and not other_ips:
        try:
            # Method 1: Use 'ip' command (modern Linux)
            result = subprocess.run(['ip', 'route', 'get', '8.8.8.8'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'src' in line:
                        parts = line.split()
                        src_idx = parts.index('src')
                        if src_idx + 1 < len(parts):
                            ip = parts[src_idx + 1]
                            if not ip.startswith('127.') and ip not in local_ips + other_ips:
                                if ip.startswith(("192.168.", "10.", "172.")):
                                    local_ips.append(ip)
                                else:
                                    other_ips.append(ip)
                                break
        except (subprocess.SubprocessError, FileNotFoundError, ValueError):
            pass
            
        try:
            # Method 2: Use 'hostname -I' (some Linux distributions)
            result = subprocess.run(['hostname', '-I'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                for ip in result.stdout.strip().split():
                    if not ip.startswith('127.') and ip not in local_ips + other_ips:
                        if ip.startswith(("192.168.", "10.", "172.")):
                            local_ips.append(ip)
                        else:
                            other_ips.append(ip)
        except (subprocess.SubprocessError, FileNotFoundError):
            pass

    # Combine and remove duplicates, keeping order
    sorted_ips = sorted(list(set(local_ips))) + sorted(list(set(other_ips)))

    # Fallback if all methods fail
    if not sorted_ips:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
                if ip and ip != "0.0.0.0" and not ip.startswith("127."):
                    sorted_ips.append(ip)
        except Exception as e:
            log.error(f"Socket fallback for IP address failed: {e}")
            
        # Linux-specific: Final fallback using network interfaces directly
        if not sorted_ips and sys.platform.startswith('linux'):
            try:
                import glob
                for interface_path in glob.glob('/sys/class/net/*/address'):
                    interface_name = interface_path.split('/')[-2]
                    if not interface_name.startswith(('lo', 'docker', 'br-', 'veth')):
                        # This is a basic fallback - in practice, the earlier methods should work
                        break
            except Exception:
                pass

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
        self.init_system = self._detect_init_system()
        self.is_packaged = self._detect_packaged_installation()

    def _detect_init_system(self) -> str:
        """Detect the init system in use."""
        try:
            # Check for systemd
            if Path("/run/systemd/system").exists():
                return "systemd"
            
            # Check for runit
            if Path("/run/runit").exists() or shutil.which("sv"):
                return "runit"
            
            # Check for OpenRC
            if Path("/run/openrc").exists() or shutil.which("rc-service"):
                return "openrc"
            
            # Check for SysV init
            if Path("/etc/init.d").exists():
                return "sysv"
            
            # Default fallback
            return "unknown"
            
        except Exception as e:
            log.debug(f"Error detecting init system: {e}")
            return "unknown"

    def _detect_packaged_installation(self) -> bool:
        """Detect if PCLink is installed as a system package."""
        try:
            # Check if running from /usr/lib/pclink (typical .deb installation)
            if str(Path(__file__).resolve()).startswith("/usr/lib/pclink"):
                return True
            
            # Check if pclink command is in system PATH
            pclink_path = shutil.which("pclink")
            if pclink_path and Path(pclink_path).resolve().parts[:3] == ('/', 'usr', 'bin'):
                return True
            
            # Check for .deb package installation
            try:
                result = subprocess.run(
                    ["dpkg", "-l", "pclink"], 
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0 and "ii" in result.stdout:
                    return True
            except (subprocess.SubprocessError, FileNotFoundError):
                pass
            
            # Check for .rpm package installation
            try:
                result = subprocess.run(
                    ["rpm", "-q", "pclink"], 
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    return True
            except (subprocess.SubprocessError, FileNotFoundError):
                pass
            
            return False
            
        except Exception as e:
            log.debug(f"Error detecting package installation: {e}")
            return False

    def _get_desktop_file(self, app_name: str) -> Path:
        return self.autostart_path / f"{app_name.lower()}.desktop"

    def _get_systemd_user_service_path(self, app_name: str) -> Path:
        """Get path for systemd user service file."""
        systemd_user_dir = Path.home() / ".config" / "systemd" / "user"
        return systemd_user_dir / f"{app_name.lower()}.service"

    def _create_systemd_user_service(self, app_name: str, exe_path: Path):
        """Create a systemd user service for startup."""
        try:
            service_path = self._get_systemd_user_service_path(app_name)
            service_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Determine the correct executable path
            if self.is_packaged:
                # Use system pclink command for packaged installations
                exec_start = "/usr/bin/pclink --startup"
                working_dir = "/usr/lib/pclink"
            else:
                # Use direct path for development/portable installations
                exec_start = f'"{exe_path}" --startup'
                working_dir = exe_path.parent
            
            service_content = f"""[Unit]
Description={app_name} Remote Control Server
After=graphical-session.target
Wants=graphical-session.target

[Service]
Type=simple
ExecStart={exec_start}
WorkingDirectory={working_dir}
Restart=on-failure
RestartSec=5
Environment=DISPLAY=:0
Environment=XDG_RUNTIME_DIR=%i

[Install]
WantedBy=default.target
"""
            
            service_path.write_text(service_content, encoding="utf-8")
            
            # Reload systemd and enable the service
            subprocess.run(["systemctl", "--user", "daemon-reload"], 
                         check=False, capture_output=True)
            subprocess.run(["systemctl", "--user", "enable", f"{app_name.lower()}.service"], 
                         check=False, capture_output=True)
            
            log.info(f"Created systemd user service: {service_path}")
            return True
            
        except Exception as e:
            log.warning(f"Failed to create systemd user service: {e}")
            return False

    def _remove_systemd_user_service(self, app_name: str):
        """Remove systemd user service."""
        try:
            service_name = f"{app_name.lower()}.service"
            
            # Disable and stop the service
            subprocess.run(["systemctl", "--user", "disable", service_name], 
                         check=False, capture_output=True)
            subprocess.run(["systemctl", "--user", "stop", service_name], 
                         check=False, capture_output=True)
            
            # Remove service file
            service_path = self._get_systemd_user_service_path(app_name)
            service_path.unlink(missing_ok=True)
            
            # Reload systemd
            subprocess.run(["systemctl", "--user", "daemon-reload"], 
                         check=False, capture_output=True)
            
            log.info(f"Removed systemd user service: {service_name}")
            return True
            
        except Exception as e:
            log.warning(f"Failed to remove systemd user service: {e}")
            return False

    def _is_systemd_service_enabled(self, app_name: str) -> bool:
        """Check if systemd user service is enabled."""
        try:
            service_name = f"{app_name.lower()}.service"
            result = subprocess.run(
                ["systemctl", "--user", "is-enabled", service_name],
                capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0 and "enabled" in result.stdout
        except Exception:
            return False

    def add(self, app_name: str, exe_path: Path):
        """Add application to startup using the most appropriate method."""
        success_methods = []
        
        # Method 1: Try systemd user service (preferred for modern systems)
        if self.init_system == "systemd":
            if self._create_systemd_user_service(app_name, exe_path):
                success_methods.append("systemd")
        
        # Method 2: Desktop autostart (fallback and compatibility)
        try:
            self.autostart_path.mkdir(parents=True, exist_ok=True)
            desktop_file = self._get_desktop_file(app_name)
            
            # Get icon path
            try:
                icon_path = resource_path("src/pclink/assets/icon.png")
            except Exception:
                icon_path = "pclink"  # Use generic name if icon not found
            
            # Determine the correct executable command
            if self.is_packaged:
                exec_command = "/usr/bin/pclink --startup"
            else:
                exec_command = f'"{exe_path}" --startup'
            
            desktop_entry = (
                f"[Desktop Entry]\n"
                f"Type=Application\n"
                f"Name={app_name}\n"
                f"Exec=sh -c 'sleep 10 && {exec_command}'\n"
                f"Comment={app_name} Remote Control Server\n"
                f"Icon={icon_path}\n"
                f"X-GNOME-Autostart-enabled=true\n"
                f"X-KDE-autostart-after=panel\n"
                f"X-MATE-Autostart-enabled=true\n"
                f"Hidden=false\n"
                f"NoDisplay=true\n"
                f"StartupNotify=false\n"
                f"Categories=Network;System;\n"
                f"X-GNOME-Autostart-Delay=10\n"
            )
            
            desktop_file.write_text(desktop_entry, encoding="utf-8")
            success_methods.append("desktop")
            log.info(f"Added '{app_name}' to desktop autostart at {desktop_file}")
            
        except IOError as e:
            log.warning(f"Failed to write desktop entry file: {e}")
        
        # Method 3: Init system specific methods (for systems without desktop environment)
        if self.init_system == "runit":
            try:
                # Create a simple runit service (user-level)
                runit_dir = Path.home() / ".local" / "share" / "runit" / "sv" / app_name.lower()
                runit_dir.mkdir(parents=True, exist_ok=True)
                
                run_script = runit_dir / "run"
                if self.is_packaged:
                    run_content = f"#!/bin/sh\nexec /usr/bin/pclink --startup\n"
                else:
                    run_content = f"#!/bin/sh\nexec \"{exe_path}\" --startup\n"
                
                run_script.write_text(run_content)
                run_script.chmod(0o755)
                
                success_methods.append("runit")
                log.info(f"Created runit service directory: {runit_dir}")
                
            except Exception as e:
                log.warning(f"Failed to create runit service: {e}")
        
        if not success_methods:
            raise OSError("Failed to add to startup using any available method")
        
        log.info(f"Added '{app_name}' to Linux startup using: {', '.join(success_methods)}")

    def remove(self, app_name: str):
        """Remove application from startup using all methods."""
        removed_methods = []
        
        # Remove systemd user service
        if self.init_system == "systemd":
            if self._remove_systemd_user_service(app_name):
                removed_methods.append("systemd")
        
        # Remove desktop autostart file
        desktop_file = self._get_desktop_file(app_name)
        try:
            if desktop_file.exists():
                desktop_file.unlink()
                removed_methods.append("desktop")
                log.info(f"Removed desktop autostart file: {desktop_file}")
        except IOError as e:
            log.warning(f"Failed to remove desktop autostart file: {e}")
        
        # Remove runit service
        if self.init_system == "runit":
            try:
                runit_dir = Path.home() / ".local" / "share" / "runit" / "sv" / app_name.lower()
                if runit_dir.exists():
                    shutil.rmtree(runit_dir)
                    removed_methods.append("runit")
                    log.info(f"Removed runit service: {runit_dir}")
            except Exception as e:
                log.warning(f"Failed to remove runit service: {e}")
        
        if removed_methods:
            log.info(f"Removed '{app_name}' from Linux startup: {', '.join(removed_methods)}")
        else:
            log.debug(f"'{app_name}' not found in any startup location")

    def is_enabled(self, app_name: str) -> bool:
        """Check if application is enabled for startup using any method."""
        # Check systemd user service
        if self.init_system == "systemd" and self._is_systemd_service_enabled(app_name):
            return True
        
        # Check desktop autostart file
        if self._get_desktop_file(app_name).exists():
            return True
        
        # Check runit service
        if self.init_system == "runit":
            runit_dir = Path.home() / ".local" / "share" / "runit" / "sv" / app_name.lower()
            if runit_dir.exists() and (runit_dir / "run").exists():
                return True
        
        return False


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