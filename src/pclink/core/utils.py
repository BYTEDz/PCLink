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
import socket
import sys
from pathlib import Path
from typing import Callable, List, Optional, Union

import psutil

if sys.platform == "win32":
    import ctypes
    import winreg

log = logging.getLogger(__name__)


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
        return

    try:
        import datetime

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:
        log.error(
            "Cryptography library is required. Please run 'pip install cryptography'."
        )
        raise

    log.info(f"Generating new self-signed certificate at {cert_path}")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    with key_path.open("wb") as f:
        f.write(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

    subject = issuer = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "PCLink Self-Signed")]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
        .not_valid_after(
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3650)
        )
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False
        )
        .sign(key, hashes.SHA256())
    )

    cert_path.parent.mkdir(parents=True, exist_ok=True)
    with cert_path.open("wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))


def get_cert_fingerprint(cert_path: Path) -> Optional[str]:
    """Calculate the SHA-256 fingerprint of a certificate."""
    if not cert_path.is_file():
        return None
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes

        cert_data = cert_path.read_bytes()
        cert = x509.load_pem_x509_certificate(cert_data)
        fingerprint = cert.fingerprint(hashes.SHA256())
        return fingerprint.hex()
    except Exception as e:
        log.error(f"Error calculating cert fingerprint for {cert_path}: {e}")
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
        command = f'"{exe_path}" --startup'
        try:
            with winreg.OpenKey(
                self.key, self.key_path, 0, winreg.KEY_SET_VALUE
            ) as reg_key:
                winreg.SetValueEx(reg_key, app_name, 0, winreg.REG_SZ, command)
            log.info(f"Added '{app_name}' to Windows startup.")
        except OSError as e:
            log.error(f"Failed to add to Windows startup: {e}")
            raise

    def remove(self, app_name: str):
        try:
            with winreg.OpenKey(
                self.key, self.key_path, 0, winreg.KEY_SET_VALUE
            ) as reg_key:
                winreg.DeleteValue(reg_key, app_name)
            log.info(f"Removed '{app_name}' from Windows startup.")
        except FileNotFoundError:
            log.debug(f"'{app_name}' not in startup, nothing to remove.")
        except OSError as e:
            log.error(f"Failed to remove from Windows startup: {e}")
            raise

    def is_enabled(self, app_name: str) -> bool:
        try:
            with winreg.OpenKey(self.key, self.key_path, 0, winreg.KEY_READ) as reg_key:
                winreg.QueryValueEx(reg_key, app_name)
            return True
        except FileNotFoundError:
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
