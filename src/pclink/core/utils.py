# src/pclink/core/utils.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
import os
import shutil
import subprocess
import socket
import sys
import importlib.resources
import datetime
import ipaddress
from pathlib import Path
from typing import Callable, List, Optional, Union

import psutil
from . import constants

# Platform-specific imports
if sys.platform == "win32":
    import ctypes
    import winreg

log = logging.getLogger(__name__)


def resource_path(relative_path: Union[str, Path]) -> Path:
    """Resolve absolute path for application resources."""
    # Case 1: PyInstaller bundle
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / relative_path

    # Case 2: Development environment
    try:
        project_root = Path(__file__).resolve().parents[3]
        if (project_root / 'pyproject.toml').exists():
            return project_root / relative_path
    except Exception:
        pass

    # Case 3: Installed package
    try:
        path_parts = Path(relative_path).parts
        if 'pclink' in path_parts:
            idx = path_parts.index('pclink')
            package_rel = Path(*path_parts[idx + 1:])
        else:
            package_rel = Path(relative_path)
        return importlib.resources.files('pclink') / package_rel
    except Exception as e:
        log.error(f"Could not find resource path for '{relative_path}': {e}")
        return Path(relative_path)


def run_preflight_checks() -> bool:
    """Execute pre-flight environment checks."""
    try:
        constants.initialize_app_directories()
        migrate_legacy_data()
        generate_self_signed_cert(constants.CERT_FILE, constants.KEY_FILE)
        return True
    except Exception as e:
        log.error(f"Preflight checks failed: {e}")
        return False


def migrate_legacy_data():
    """Migrate legacy user data to modern AppData root."""
    home = Path.home()
    legacy_targets = {
        home / ".pclink_uploads": constants.UPLOADS_PATH,
        home / ".pclink_downloads": constants.DOWNLOADS_PATH,
    }

    for legacy_dir, new_dir in legacy_targets.items():
        if legacy_dir.exists() and legacy_dir.is_dir():
            log.info(f"💾 Migrating legacy data from {legacy_dir} to {new_dir}")
            try:
                # Move all files within the directory
                for item in legacy_dir.iterdir():
                    dest = new_dir / item.name
                    if dest.exists():
                        # If destination exists (maybe a partial move or manual copy), delete the old one
                        if item.is_dir():
                            shutil.rmtree(item)
                        else:
                            item.unlink()
                    else:
                        shutil.move(str(item), str(dest))
                
                # Delete the now-empty legacy directory
                legacy_dir.rmdir()
                log.info(f"✅ Successfully migrated {legacy_dir.name}")
            except Exception as e:
                log.warning(f"⚠️ Failed to migrate some data from {legacy_dir}: {e}")


def is_admin() -> bool:
    """Verify elevated privileges."""
    if sys.platform == "win32":
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() == 1
        except Exception:
            return False
    return os.geteuid() == 0


def restart_as_admin(script_path: str = None) -> bool:
    """Elevation wrapper for Windows UAC."""
    if sys.platform != "win32":
        return False
    
    try:
        params = script_path if script_path else ' '.join(sys.argv)
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
        return True
    except Exception as e:
        log.error(f"Failed to restart as admin: {e}")
        return False


def check_firewall_rule_exists(rule_name: str) -> bool:
    """Query Windows ADVFirewall for existing rules."""
    if sys.platform != "win32":
        return True
    
    try:
        result = subprocess.run(
            ['netsh', 'advfirewall', 'firewall', 'show', 'rule', f'name={rule_name}'],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0 and rule_name in result.stdout
    except Exception:
        return False


def add_firewall_rule(rule_name: str, port: int, protocol: str = "UDP", direction: str = "out") -> tuple[bool, str]:
    """Provision Windows ADVFirewall rules."""
    if sys.platform != "win32":
        return True, "Not required on this platform"
    
    try:
        cmd = [
            'netsh', 'advfirewall', 'firewall', 'add', 'rule',
            f'name={rule_name}', f'dir={direction}', 'action=allow',
            f'protocol={protocol}', f'localport={port}'
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return (True, "Rule added successfully") if result.returncode == 0 else (False, result.stderr.strip())
    except Exception as e:
        return False, str(e)


def get_available_ips() -> List[str]:
    """
    Gets a list of all non-loopback IPv4 addresses on the host.
    Returns a sorted list prioritizing local network IPs.
    """
    local_ips, other_ips = [], []
    
    # Primary method: psutil with enhanced filtering
    try:
        for iface, addrs in psutil.net_if_addrs().items():
            # Filter virtual/loopback interfaces
            if any(x in iface.lower() for x in ["virtual", "vmnet", "loopback", "docker", "veth", "virbr", "tun", "tap"]) or \
               iface.startswith(('lo', 'br-')):
                continue
                
            # Check if interface is up
            try:
                stats = psutil.net_if_stats().get(iface)
                if stats and not stats.isup:
                    continue
            except (AttributeError, KeyError):
                pass
                
            for addr in addrs:
                if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                    # Skip invalid or link-local addresses
                    if addr.address.startswith(("169.254.", "0.")) or \
                       addr.address.endswith((".0", ".255")):
                        continue
                        
                    # Prioritize private IP ranges
                    if addr.address.startswith(("192.168.", "10.", "172.")):
                        if addr.address not in local_ips:
                            local_ips.append(addr.address)
                    else:
                        if addr.address not in other_ips:
                            other_ips.append(addr.address)
    except Exception as e:
        log.error(f"Could not get IP addresses using psutil: {e}")

    # Linux fallback: Try ip route command
    if not local_ips and not other_ips and sys.platform == "linux":
        try:
            result = subprocess.run(['ip', 'route', 'get', '8.8.8.8'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'src' in line:
                        parts = line.split()
                        src_idx = parts.index('src')
                        if src_idx + 1 < len(parts):
                            ip = parts[src_idx + 1]
                            if not ip.startswith('127.'):
                                (local_ips if ip.startswith(("192.168.", "10.", "172.")) else other_ips).append(ip)
                                break
        except (subprocess.SubprocessError, FileNotFoundError, ValueError):
            pass

    # Universal fallback: socket connection
    if not local_ips and not other_ips:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
                if ip and not ip.startswith(("127.", "0.")):
                    local_ips.append(ip)
        except Exception as e:
            log.error(f"Socket fallback for IP address failed: {e}")

    result = sorted(list(set(local_ips))) + sorted(list(set(other_ips)))
    
    if not result:
        log.warning("Could not determine any valid IP address, defaulting to 127.0.0.1")
        return ["127.0.0.1"]
    
    return result


def get_cert_fingerprint(cert_path: Path) -> Optional[str]:
    """Generate SHA-256 hash for TLS certificate verification."""
    if not cert_path.is_file():
        log.error(f"Certificate file does not exist: {cert_path}")
        return None
    
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes

        cert_data = cert_path.read_bytes()
        if not cert_data:
            log.error(f"Certificate file is empty: {cert_path}")
            return None
        
        cert = x509.load_pem_x509_certificate(cert_data)
        fingerprint_hex = cert.fingerprint(hashes.SHA256()).hex()
        log.debug(f"Certificate fingerprint: {fingerprint_hex[:16]}...")
        return fingerprint_hex
        
    except ImportError as e:
        log.error(f"Cryptography library not available: {e}")
        return None
    except Exception as e:
        log.error(f"Error calculating cert fingerprint: {e}")
        return None


def generate_self_signed_cert(cert_path: Path, key_path: Path):
    """Bootstrap self-signed TLS credentials."""
    if cert_path.exists() and key_path.exists():
        log.debug(f"Certificate and key already exist")
        if get_cert_fingerprint(cert_path):
            log.debug("Existing certificate is valid")
            return
        log.warning("Existing certificate is invalid, regenerating...")

    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError as e:
        log.error(f"Cryptography library required. Install with: pip install cryptography")
        raise

    try:
        log.info(f"Generating new self-signed certificate")
        
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        
        key_path.parent.mkdir(parents=True, exist_ok=True)
        cert_path.parent.mkdir(parents=True, exist_ok=True)
        
        with key_path.open("wb") as f:
            f.write(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            ))

        subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "PCLink Self-Signed")])
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

        with cert_path.open("wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        
        fingerprint = get_cert_fingerprint(cert_path)
        if fingerprint:
            log.info(f"Successfully generated certificate")
        else:
            raise Exception("Certificate validation failed after generation")
            
    except Exception as e:
        log.error(f"Failed to generate self-signed certificate: {e}")
        # Cleanup partial files
        for path in [cert_path, key_path]:
            try:
                if path.exists():
                    path.unlink()
            except Exception:
                pass
        raise


# --- Startup Managers ---

class _StartupManager:
    """Platform-agnostic Startup Manager interface."""
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
        """Deploy Windows startup artifacts (Registry/Task Scheduler/VBS)."""
        # Determine the proper command for startup
        # For frozen apps: just run the exe
        # For dev: use pythonw.exe (windowless) with -m pclink start
        exe_path_str = str(exe_path)
        
        if getattr(sys, 'frozen', False):
            # Frozen executable - just run it directly
            command = f'"{exe_path_str}"'
        else:
            # Development mode - use pythonw.exe for windowless execution
            python_dir = Path(sys.executable).parent
            pythonw = python_dir / "pythonw.exe"
            if pythonw.exists():
                command = f'"{pythonw}" -m pclink start'
            else:
                # Fallback to python.exe if pythonw not available
                command = f'"{sys.executable}" -m pclink start'
        
        success_methods = []
        
        # Method 1: Registry (fast, simple, most common)
        try:
            with winreg.OpenKey(self.key, self.key_path, 0, winreg.KEY_SET_VALUE) as rk:
                winreg.SetValueEx(rk, app_name, 0, winreg.REG_SZ, command)
            log.info(f"Added '{app_name}' to registry startup")
            success_methods.append("registry")
        except OSError as e:
            log.warning(f"Failed to add to registry: {e}")

        # Method 2: Task Scheduler (more reliable, survives registry cleanup)
        if self._add_to_task_scheduler(app_name, exe_path_str):
            success_methods.append("task_scheduler")
        
        # Method 3: Startup folder with VBS wrapper (fallback for restricted environments)
        if not success_methods:
            if self._add_to_startup_folder(app_name, exe_path_str):
                success_methods.append("startup_folder")
        
        if not success_methods:
            raise OSError("Failed to add to startup using any method")
        
        log.info(f"Added to Windows startup using: {', '.join(success_methods)}")

    def _add_to_task_scheduler(self, app_name: str, exe_path: str) -> bool:
        """Provision Windows Task Scheduler entry for background persistence."""
        try:
            # Determine execution command
            if getattr(sys, 'frozen', False):
                task_command = f'"{exe_path}"'
            else:
                python_dir = Path(sys.executable).parent
                pythonw = python_dir / "pythonw.exe"
                if pythonw.exists():
                    task_command = f'"{pythonw}" -m pclink start'
                else:
                    task_command = f'"{sys.executable}" -m pclink start'
            
            cmd = [
                "schtasks", "/create", "/tn", f"PCLink_{app_name}", "/f",
                "/sc", "ONLOGON", "/tr", task_command,
                "/rl", "HIGHEST", "/delay", "0000:10"
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            if result.returncode == 0:
                log.info(f"Added '{app_name}' to Task Scheduler")
                return True
            log.warning(f"Task Scheduler failed: {result.stderr}")
            return False
        except Exception as e:
            log.warning(f"Failed to add to Task Scheduler: {e}")
            return False

    def _add_to_startup_folder(self, app_name: str, exe_path: str) -> bool:
        """Deploy VBScript wrapper for windowless persistence."""
        try:
            startup_folder = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
            startup_folder.mkdir(parents=True, exist_ok=True)
            
            # Determine execution command
            if getattr(sys, 'frozen', False):
                run_command = f'"{exe_path}"'
            else:
                python_dir = Path(sys.executable).parent
                pythonw = python_dir / "pythonw.exe"
                if pythonw.exists():
                    run_command = f'"{pythonw}" -m pclink start'
                else:
                    run_command = f'"{sys.executable}" -m pclink start'
            
            # Use VBScript for truly hidden execution (industry standard for hidden startup)
            vbs_path = startup_folder / f"{app_name}.vbs"
            vbs_content = f'''Set WshShell = CreateObject("WScript.Shell")
WScript.Sleep 10000
WshShell.Run {run_command}, 0, False
'''
            vbs_path.write_text(vbs_content)
            
            if vbs_path.exists():
                log.info(f"Added '{app_name}' VBS script to startup folder")
                return True
        except Exception as e:
            log.warning(f"Failed to add to startup folder: {e}")
        return False

    def remove(self, app_name: str):
        removed_any = False
        
        # Remove from registry
        try:
            with winreg.OpenKey(self.key, self.key_path, 0, winreg.KEY_SET_VALUE) as rk:
                winreg.DeleteValue(rk, app_name)
            log.info(f"Removed '{app_name}' from registry")
            removed_any = True
        except FileNotFoundError:
            pass
        except OSError as e:
            log.warning(f"Failed to remove from registry: {e}")
        
        # Remove from Task Scheduler
        try:
            result = subprocess.run(
                ["schtasks", "/delete", "/tn", f"PCLink_{app_name}", "/f"],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            if result.returncode == 0:
                log.info(f"Removed '{app_name}' from Task Scheduler")
                removed_any = True
        except Exception as e:
            log.warning(f"Failed to remove from Task Scheduler: {e}")
        
        # Remove from startup folder (check all possible extensions)
        try:
            startup_folder = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
            for ext in [".vbs", ".bat", ".lnk"]:
                file_path = startup_folder / f"{app_name}{ext}"
                if file_path.exists():
                    file_path.unlink()
                    log.info(f"Removed '{app_name}{ext}' from startup folder")
                    removed_any = True
        except Exception as e:
            log.warning(f"Failed to remove from startup folder: {e}")
        
        if not removed_any:
            log.debug(f"'{app_name}' not found in any startup location")

    def is_enabled(self, app_name: str) -> bool:
        # Check registry
        try:
            with winreg.OpenKey(self.key, self.key_path, 0, winreg.KEY_READ) as rk:
                winreg.QueryValueEx(rk, app_name)
                return True
        except FileNotFoundError:
            pass
        
        # Check Task Scheduler
        try:
            result = subprocess.run(
                ["schtasks", "/query", "/tn", f"PCLink_{app_name}"],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            if result.returncode == 0:
                return True
        except Exception:
            pass
        
        # Check startup folder (all possible extensions)
        try:
            startup_folder = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
            for ext in [".vbs", ".bat", ".lnk"]:
                if (startup_folder / f"{app_name}{ext}").exists():
                    return True
        except Exception:
            pass
        
        return False


class _LinuxStartupManager(_StartupManager):
    def __init__(self):
        self.autostart_path = Path.home() / ".config" / "autostart"
        self.systemd_dir = Path.home() / ".config" / "systemd" / "user"
        self.is_packaged = self._detect_packaged_installation()

    def _get_systemctl_env(self) -> dict:
        """Prepare environment tokens for headless systemctl operations."""
        env = os.environ.copy()
        uid = os.getuid()
        # Ensure XDG_RUNTIME_DIR is set (required for systemctl --user)
        if "XDG_RUNTIME_DIR" not in env:
            env["XDG_RUNTIME_DIR"] = f"/run/user/{uid}"
        # Ensure DBUS_SESSION_BUS_ADDRESS is set
        if "DBUS_SESSION_BUS_ADDRESS" not in env:
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{uid}/bus"
        return env

    def _detect_packaged_installation(self) -> bool:
        """Inference for packaged vs. development installation state."""
        try:
            # Check if installed in /usr/lib or /usr/bin
            if str(Path(__file__).resolve()).startswith("/usr/lib/pclink"):
                return True
            
            pclink_path = shutil.which("pclink")
            if pclink_path and Path(pclink_path).resolve().parts[:3] == ('/', 'usr', 'bin'):
                return True
            
            # Check package managers
            for cmd in [["dpkg", "-l", "pclink"], ["rpm", "-q", "pclink"]]:
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        return True
                except (subprocess.SubprocessError, FileNotFoundError):
                    pass
            
            return False
        except Exception:
            return False

    def add(self, app_name: str, exe_path: Union[str, Path]):
        success_methods = []
        
        # Prepare command string
        # exe_path comes from __main__ and may be a command string (e.g. "python -m pclink")
        # or a Path object. Normalize to string.
        cmd_str = str(exe_path)
        
        # Determine Working Directory
        # Derive working directory from sys.executable to handle complex command strings.
        if self.is_packaged:
            working_dir = "/usr/lib/pclink"
        else:
            working_dir = str(Path(sys.executable).parent)

        # Method 1: Systemd user service (preferred for modern Linux)
        try:
            self.systemd_dir.mkdir(parents=True, exist_ok=True)
            svc_path = self.systemd_dir / f"{app_name.lower()}.service"
            
            # Construct ExecStart
            if self.is_packaged:
                exec_start = "/usr/bin/pclink start"
            else:
                # exe_path already includes arguments like "-m pclink" if needed, 
                # and quotes around the executable if needed.
                exec_start = f"{cmd_str} start"
            
            service_content = f"""[Unit]
Description={app_name} Remote Control Server
After=graphical-session.target network-online.target
Wants=graphical-session.target network-online.target

[Service]
Type=forking
ExecStart={exec_start}
WorkingDirectory={working_dir}
Restart=on-failure
RestartSec=10
Environment=DISPLAY=:0
Environment=XDG_RUNTIME_DIR=/run/user/%U

[Install]
WantedBy=default.target
"""
            svc_path.write_text(service_content, encoding="utf-8")
            
            # Reload and enable service (with proper env for headless contexts)
            env = self._get_systemctl_env()
            subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True, env=env)
            subprocess.run(["systemctl", "--user", "enable", svc_path.name], capture_output=True, env=env)
            
            log.info(f"Created systemd user service: {svc_path}")
            success_methods.append("systemd")
        except Exception as e:
            log.warning(f"Failed to create systemd service: {e}")

        # Method 2: XDG autostart (universal fallback)
        try:
            self.autostart_path.mkdir(parents=True, exist_ok=True)
            desktop_file = self.autostart_path / f"{app_name.lower()}.desktop"
            
            try:
                icon_path = resource_path("src/pclink/assets/icon.png")
            except Exception:
                icon_path = "pclink"
            
            if self.is_packaged:
                exec_command = "/usr/bin/pclink start"
            else:
                exec_command = f"{cmd_str} start"
            
            desktop_entry = (
                f"[Desktop Entry]\n"
                f"Type=Application\n"
                f"Name={app_name}\n"
                f"Exec=sh -c 'sleep 3 && {exec_command}'\n"
                f"Comment={app_name} Remote Control Server\n"
                f"Icon={icon_path}\n"
                f"X-GNOME-Autostart-enabled=true\n"
                f"X-GNOME-Autostart-Delay=3\n"
                f"X-KDE-autostart-after=panel\n"
                f"X-MATE-Autostart-Delay=3\n"
                f"Hidden=false\n"
                f"NoDisplay=true\n"
                f"StartupNotify=false\n"
                f"Terminal=false\n"
            )
            
            desktop_file.write_text(desktop_entry, encoding="utf-8")
            desktop_file.chmod(0o755)
            log.info(f"Added '{app_name}' to desktop autostart")
            success_methods.append("desktop")
        except IOError as e:
            log.warning(f"Failed to write desktop entry: {e}")
        
        if not success_methods:
            raise OSError("Failed to add to startup using any available method")
        
        log.info(f"Added to Linux startup using: {', '.join(success_methods)}")

    def remove(self, app_name: str):
        removed_methods = []
        service_name = f"{app_name.lower()}.service"
        env = self._get_systemctl_env()
        
        # Step 1: Attempt to disable via systemctl (with proper env for headless)
        try:
            subprocess.run(["systemctl", "--user", "disable", service_name], check=False, capture_output=True, env=env)
        except Exception as e:
            log.warning(f"systemctl disable failed (proceeding to file deletion): {e}")
        
        # Step 2: Forcefully delete the service file
        try:
            svc_path = self.systemd_dir / service_name
            if svc_path.exists():
                svc_path.unlink()
                removed_methods.append("systemd")
                log.info(f"Deleted service file: {svc_path}")
        except Exception as e:
            log.error(f"Failed to delete service file {svc_path}: {e}")

        # Step 3: Reload daemon (best effort, with proper env)
        try:
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=False, capture_output=True, env=env)
        except Exception:
            pass
        
        # Step 4: Remove desktop autostart
        try:
            desktop_file = self.autostart_path / f"{app_name.lower()}.desktop"
            if desktop_file.exists():
                desktop_file.unlink()
                removed_methods.append("desktop")
                log.info(f"Deleted desktop entry: {desktop_file}")
        except IOError as e:
            log.warning(f"Failed to remove desktop autostart: {e}")
        
        if removed_methods:
            log.info(f"Removed from Linux startup: {', '.join(removed_methods)}")
        else:
            log.debug(f"'{app_name}' not found in any startup location")

    def is_enabled(self, app_name: str) -> bool:
        # Check systemd (with proper env for headless contexts)
        try:
            result = subprocess.run(
                ["systemctl", "--user", "is-enabled", f"{app_name.lower()}.service"],
                capture_output=True, text=True, timeout=5, env=self._get_systemctl_env()
            )
            if result.returncode == 0 and "enabled" in result.stdout:
                return True
        except Exception:
            pass
        
        # Check desktop autostart
        return (self.autostart_path / f"{app_name.lower()}.desktop").exists()


class _UnsupportedStartupManager(_StartupManager):
    """Fallback for unsupported platforms."""
    def add(self, app_name: str, exe_path: Path):
        log.warning(f"Startup management not supported on '{sys.platform}'")
    def remove(self, app_name: str):
        log.warning(f"Startup management not supported on '{sys.platform}'")
    def is_enabled(self, app_name: str) -> bool:
        return False


def get_startup_manager() -> _StartupManager:
    """Startup strategy resolver."""
    if sys.platform == "win32":
        return _WindowsStartupManager()
    if sys.platform == "linux":
        return _LinuxStartupManager()
    return _UnsupportedStartupManager()


# --- Config Helpers ---

def load_config_value(file_path: Path, default: Union[str, Callable[[], str]] = "") -> str:
    """Read persistent setting with lazy initialization."""
    try:
        if file_path.is_file():
            return file_path.read_text(encoding="utf-8").strip()
    except IOError as e:
        log.warning(f"Could not read config file {file_path}: {e}")

    default_value = default() if callable(default) else default
    save_config_value(file_path, default_value)
    return str(default_value)


def save_config_value(file_path: Path, value: Union[str, int]):
    """Persist setting to filesystem."""
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(str(value), encoding="utf-8")
    except IOError as e:
        log.error(f"Could not write to config file {file_path}: {e}")
        raise


class DummyTty:
    """A dummy TTY-like object for environments where sys.stdout is None."""
    def __init__(self):
        self.encoding = "utf-8"
        self.errors = "strict"

    def isatty(self) -> bool:
        return False
    def fileno(self) -> int:
        # Return a valid file descriptor for libraries like speedtest
        return os.open(os.devnull, os.O_WRONLY)
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