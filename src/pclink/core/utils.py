# filepath: src/pclink/core/utils.py

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import datetime
import gettext
import importlib.resources
import ipaddress
import logging
import os
import re
import socket
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Union

import psutil

from . import constants

log = logging.getLogger(__name__)
_ = gettext.gettext


def resource_path(relative_path: Union[str, Path]) -> Path:
    """Resolve absolute path for application resources."""
    # Case 1: PyInstaller bundle
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / relative_path

    # Case 2: Development environment
    try:
        project_root = Path(__file__).resolve().parents[3]
        if (project_root / "pyproject.toml").exists():
            return project_root / relative_path
    except Exception:
        pass

    # Case 3: Installed package
    try:
        path_parts = Path(relative_path).parts
        if "pclink" in path_parts:
            idx = path_parts.index("pclink")
            package_rel = Path(*path_parts[idx + 1 :])
        else:
            package_rel = Path(relative_path)
        return importlib.resources.files("pclink") / package_rel
    except Exception as e:
        log.error(
            _("Could not find resource path for '{path}': {error}").format(
                path=relative_path, error=e
            )
        )
        return Path(relative_path)


def run_preflight_checks() -> bool:
    """Execute pre-flight environment checks."""
    try:
        constants.initialize_app_directories()
        generate_self_signed_cert(constants.CERT_FILE, constants.KEY_FILE)

        # Optimize system limits
        if sys.platform == "linux":
            increase_open_files_limit()

        return True
    except Exception as e:
        log.error(_("Preflight checks failed: {error}").format(error=e))
        return False


def increase_open_files_limit(target: int = 4096):
    """
    Increases the maximum number of open file descriptors for the current process.
    Required for extensions using select() when many connections are active.
    """
    if sys.platform != "linux":
        return

    try:
        import resource

        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        if soft < target:
            new_soft = min(target, hard)
            if new_soft > soft:
                resource.setrlimit(resource.RLIMIT_NOFILE, (new_soft, hard))
                log.info(
                    _("Increased open files limit: {soft} -> {new_soft}").format(
                        soft=soft, new_soft=new_soft
                    )
                )
    except Exception as e:
        log.warning(_("Could not increase open files limit: {error}").format(error=e))


def get_available_ips() -> List[str]:
    """
    Gets a list of all non-loopback IPv4 addresses on the host.
    Returns a sorted list prioritizing local physical network IPs over virtual/ICS adapters.
    """
    local_ips, other_ips = [], []

    # Primary method: psutil with structured parsing
    try:
        try:
            if_stats = psutil.net_if_stats()
        except Exception:
            if_stats = {}

        for iface, addrs in psutil.net_if_addrs().items():
            iface_lower = iface.lower()
            if any(
                x in iface_lower
                for x in [
                    "virtual",
                    "vmnet",
                    "loopback",
                    "docker",
                    "veth",
                    "vethernet",
                    "hyper-v",
                    "wsl",
                    "default switch",
                    "virbr",
                    "tun",
                    "tap",
                ]
            ) or iface_lower.startswith(("lo", "br-")):
                continue

            stats = if_stats.get(iface)
            if stats and not stats.isup:
                continue

            for addr in addrs:
                if addr.family == socket.AF_INET:
                    try:
                        ip_obj = ipaddress.IPv4Address(addr.address)
                        if (
                            ip_obj.is_loopback
                            or ip_obj.is_link_local
                            or ip_obj.is_multicast
                            or ip_obj.is_unspecified
                            or str(addr.address)
                            == "192.168.137.1"  # Ignore Windows ICS gateway
                        ):
                            continue

                        if ip_obj.is_private:
                            if addr.address not in local_ips:
                                local_ips.append(addr.address)
                        else:
                            if addr.address not in other_ips:
                                other_ips.append(addr.address)
                    except ValueError:
                        continue
    except Exception as e:
        log.error(_("Could not get IP addresses using psutil: {error}").format(error=e))

    # Linux fallback: Try ip route command
    if not local_ips and not other_ips and sys.platform == "linux":
        try:
            result = subprocess.run(
                ["ip", "route", "get", "8.8.8.8"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                match = re.search(
                    r"src\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", result.stdout
                )
                if match:
                    ip = match.group(1)
                    try:
                        ip_obj = ipaddress.IPv4Address(ip)
                        if not ip_obj.is_loopback and ip != "192.168.137.1":
                            if ip_obj.is_private:
                                local_ips.append(ip)
                            else:
                                other_ips.append(ip)
                    except ValueError:
                        pass
        except (subprocess.SubprocessError, FileNotFoundError, ValueError):
            pass

    # Universal fallback: socket connection
    if not local_ips and not other_ips:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
                if ip and ip != "192.168.137.1":
                    try:
                        ip_obj = ipaddress.IPv4Address(ip)
                        if not ip_obj.is_loopback and not ip_obj.is_unspecified:
                            local_ips.append(ip)
                    except ValueError:
                        pass
        except Exception as e:
            log.error(
                _("Socket fallback for IP address failed: {error}").format(error=e)
            )

    result = sorted(list(set(local_ips))) + sorted(list(set(other_ips)))

    if not result:
        log.warning(
            _("Could not determine any valid IP address, defaulting to 127.0.0.1")
        )
        return ["127.0.0.1"]

    return result


def get_cert_fingerprint(cert_path: Path) -> Optional[str]:
    """Generate SHA-256 hash for TLS certificate verification."""
    if not cert_path.is_file():
        log.error(_("Certificate file does not exist: {path}").format(path=cert_path))
        return None

    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes

        cert_data = cert_path.read_bytes()
        if not cert_data:
            log.error(_("Certificate file is empty: {path}").format(path=cert_path))
            return None

        cert = x509.load_pem_x509_certificate(cert_data)
        fingerprint_hex = cert.fingerprint(hashes.SHA256()).hex()
        log.debug(
            _("Certificate fingerprint: {fingerprint}...").format(
                fingerprint=fingerprint_hex[:16]
            )
        )
        return fingerprint_hex

    except ImportError as e:
        log.error(_("Cryptography library not available: {error}").format(error=e))
        return None
    except Exception as e:
        log.error(_("Error calculating cert fingerprint: {error}").format(error=e))
        return None


def generate_self_signed_cert(cert_path: Path, key_path: Path):
    """Bootstrap self-signed TLS credentials."""
    if cert_path.exists() and key_path.exists():
        log.debug(_("Certificate and key already exist"))
        if get_cert_fingerprint(cert_path):
            log.debug(_("Existing certificate is valid"))
            return
        log.warning(_("Existing certificate is invalid, regenerating..."))

    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:
        log.error(
            _("Cryptography library required. Install with: pip install cryptography")
        )
        raise

    try:
        log.info(_("Generating new self-signed certificate"))

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        key_path.parent.mkdir(parents=True, exist_ok=True)
        cert_path.parent.mkdir(parents=True, exist_ok=True)

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
        now = datetime.datetime.now(datetime.timezone.utc)

        san_entries = [
            x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
        ]
        for ip in get_available_ips():
            try:
                ip_addr = ipaddress.IPv4Address(ip)
                if not ip_addr.is_loopback:
                    san_entries.append(x509.IPAddress(ip_addr))
            except ValueError:
                pass

        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(
                x509.SubjectAlternativeName(san_entries),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )

        with cert_path.open("wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

        fingerprint = get_cert_fingerprint(cert_path)
        if fingerprint:
            log.info(_("Successfully generated certificate"))
        else:
            raise Exception(_("Certificate validation failed after generation"))

    except Exception as e:
        log.error(
            _("Failed to generate self-signed certificate: {error}").format(error=e)
        )
        for path in [cert_path, key_path]:
            try:
                if path.exists():
                    path.unlink()
            except Exception:
                pass
        raise


class DummyTty:
    """A dummy TTY-like object for environments where sys.stdout is None."""

    def __init__(self):
        self.encoding = "utf-8"
        self.errors = "strict"
        self._fd = None

    def isatty(self) -> bool:
        return False

    def fileno(self) -> int:
        if self._fd is None:
            try:
                self._fd = os.open(os.devnull, os.O_WRONLY)
            except Exception:
                return 1
        return self._fd

    def write(self, msg: str):
        pass

    def flush(self):
        pass

    def readline(self):
        return ""

    def readlines(self):
        return []

    def close(self):
        if self._fd is not None:
            try:
                os.close(self._fd)
            except Exception:
                pass
            self._fd = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def open_directory(path: Union[str, Path]):
    """Opens a directory in the system's file manager."""
    try:
        path = Path(path).resolve()
        if not path.exists():
            log.warning(
                _("Attempted to open non-existent directory: {path}").format(path=path)
            )
            return

        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            try:
                subprocess.run(["xdg-open", str(path)], check=False)
            except (FileNotFoundError, subprocess.SubprocessError):
                log.error(_("Could not find xdg-open to open directory."))
    except Exception as e:
        log.error(
            _("Error opening directory {path}: {error}").format(path=path, error=e)
        )


def perform_factory_reset(wipe_auth: bool = False, wipe_extensions: bool = False):
    """
    Purges server configuration and data.
    If wipe_auth is True, also deletes authentication credentials.
    If wipe_extensions is True, also deletes the extensions directory.
    """
    import shutil
    import time

    log.warning(
        _(
            "FACTORY RESET INITIATED (wipe_auth={wipe_auth}, wipe_extensions={wipe_extensions})"
        ).format(wipe_auth=wipe_auth, wipe_extensions=wipe_extensions)
    )
    log.warning(_("FACTORY RESET INITIATED. PURGING SYSTEM DATA..."))

    items_to_delete = [
        constants.CONFIG_FILE,
        constants.APP_DATA_PATH / "devices.db",
        constants.APP_DATA_PATH / "logs",
        constants.APP_DATA_PATH / ".extension_crashes",
    ]

    if wipe_auth:
        log.warning(_("Wiping ALL authentication data (Password & SSL)..."))
        items_to_delete.extend(
            [
                constants.APP_DATA_PATH / "web_auth.json",
                constants.CERT_FILE,
                constants.KEY_FILE,
            ]
        )

    if wipe_extensions:
        log.warning(_("Wiping ALL installed extensions..."))
        items_to_delete.append(constants.APP_DATA_PATH / "extensions")

    for item in items_to_delete:
        try:
            if item.exists():
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
                log.debug(_("Purged: {item}").format(item=item))
        except Exception as e:
            log.error(_("Failed to delete {item}: {error}").format(item=item, error=e))

    if constants.TRANSFERS_PATH.exists():
        try:
            shutil.rmtree(constants.TRANSFERS_PATH)
            log.debug(
                _("Purged transfers directory: {path}").format(
                    path=constants.TRANSFERS_PATH
                )
            )
        except Exception as e:
            log.error(_("Failed to delete transfers path: {error}").format(error=e))

    log.info(_("Factory reset sequence complete. Terminating process for restart."))

    try:
        logging.shutdown()
    except Exception:
        pass

    time.sleep(0.5)
    os._exit(0)
