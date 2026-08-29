# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import datetime
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


def resource_path(relative_path: Union[str, Path]) -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / relative_path

    try:
        project_root = Path(__file__).resolve().parents[3]
        if (project_root / "pyproject.toml").exists():
            return project_root / relative_path
    except Exception:
        pass

    try:
        path_parts = Path(relative_path).parts
        if "pclink" in path_parts:
            idx = path_parts.index("pclink")
            package_rel = Path(*path_parts[idx + 1 :])
        else:
            package_rel = Path(relative_path)
        return importlib.resources.files("pclink") / package_rel
    except Exception as e:
        log.error(f"Could not find resource path for '{relative_path}': {e}")
        return Path(relative_path)


def run_preflight_checks() -> bool:
    try:
        constants.initialize_app_directories()
        generate_self_signed_cert(constants.CERT_FILE, constants.KEY_FILE)

        if sys.platform == "linux":
            increase_open_files_limit()

        return True
    except Exception as e:
        log.error(f"Preflight checks failed: {e}")
        return False


def increase_open_files_limit(target: int = 4096):
    if sys.platform != "linux":
        return

    try:
        import resource

        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        if soft < target:
            new_soft = min(target, hard)
            if new_soft > soft:
                resource.setrlimit(resource.RLIMIT_NOFILE, (new_soft, hard))
                log.info(f"Increased open files limit: {soft} -> {new_soft}")
    except Exception as e:
        log.warning(f"Could not increase open files limit: {e}")


def get_available_ips() -> List[str]:
    local_ips, other_ips = [], []

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
                            or str(addr.address) == "192.168.137.1"
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
        log.error(f"Could not get IP addresses using psutil: {e}")

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
            log.error(f"Socket fallback for IP address failed: {e}")

    result = sorted(list(set(local_ips))) + sorted(list(set(other_ips)))

    if not result:
        log.warning("Could not determine any valid IP address, defaulting to 127.0.0.1")
        return ["127.0.0.1"]

    return result


def get_cert_fingerprint(cert_path: Path) -> Optional[str]:
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
        return fingerprint_hex

    except ImportError as e:
        log.error(f"Cryptography library not available: {e}")
        return None
    except Exception as e:
        log.error(f"Error calculating cert fingerprint: {e}")
        return None


def generate_self_signed_cert(cert_path: Path, key_path: Path):
    if cert_path.exists() and key_path.exists():
        if get_cert_fingerprint(cert_path):
            return
        log.warning("Existing certificate is invalid, regenerating...")

    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:
        log.error(
            "Cryptography library required. Install with: pip install cryptography"
        )
        raise

    try:
        log.info("Generating new self-signed certificate")

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
            log.info("Successfully generated certificate")
        else:
            raise Exception("Certificate validation failed after generation")

    except Exception as e:
        log.error(f"Failed to generate self-signed certificate: {e}")
        for path in [cert_path, key_path]:
            try:
                if path.exists():
                    path.unlink()
            except Exception:
                pass
        raise


class DummyTty:
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
    try:
        path = Path(path).resolve()
        if not path.exists():
            log.warning(f"Attempted to open non-existent directory: {path}")
            return

        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            try:
                subprocess.run(["xdg-open", str(path)], check=False)
            except (FileNotFoundError, subprocess.SubprocessError):
                log.error("Could not find xdg-open to open directory.")
    except Exception as e:
        log.error(f"Error opening directory {path}: {e}")


def perform_factory_reset(wipe_auth: bool = False, wipe_extensions: bool = False):
    import shutil
    import time

    log.warning(
        f"FACTORY RESET INITIATED (wipe_auth={wipe_auth}, wipe_extensions={wipe_extensions})"
    )

    items_to_delete = [
        constants.CONFIG_FILE,
        constants.APP_DATA_PATH / "devices.db",
        constants.APP_DATA_PATH / "extensions.db",
        constants.APP_DATA_PATH / "shares.db",
        constants.APP_DATA_PATH / "logs",
        constants.APP_DATA_PATH / ".extension_crashes",
    ]

    if wipe_auth:
        log.warning("Wiping authentication configuration and certificates...")
        items_to_delete.extend(
            [
                constants.APP_DATA_PATH / "web_auth.json",
                constants.CERT_FILE,
                constants.KEY_FILE,
            ]
        )

    if wipe_extensions:
        log.warning("Wiping installed extensions and extension storage...")
        items_to_delete.append(constants.APP_DATA_PATH / "extensions")
        items_to_delete.append(constants.APP_DATA_PATH / "extension_data")

    for item in items_to_delete:
        try:
            if item.exists():
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
                log.debug(f"Purged: {item}")
        except Exception as e:
            log.error(f"Failed to delete {item}: {e}")

    if constants.TRANSFERS_PATH.exists():
        try:
            shutil.rmtree(constants.TRANSFERS_PATH)
            log.debug(f"Purged transfers directory: {constants.TRANSFERS_PATH}")
        except Exception as e:
            log.error(f"Failed to delete transfers path: {e}")

    log.info("Factory reset sequence complete. Terminating process.")

    try:
        logging.shutdown()
    except Exception:
        pass

    time.sleep(0.5)
    os._exit(0)
