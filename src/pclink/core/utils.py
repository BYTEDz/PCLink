# src/pclink/core/utils.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import datetime
import importlib.resources
import ipaddress
import logging
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Union

import psutil

from . import constants


log = logging.getLogger(__name__)


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
        log.error(f"Could not find resource path for '{relative_path}': {e}")
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
        log.error(f"Preflight checks failed: {e}")
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
            resource.setrlimit(resource.RLIMIT_NOFILE, (new_soft, hard))
            log.info(f"🚀 Increased open files limit: {soft} -> {new_soft}")
    except Exception as e:
        log.warning(f"⚠️ Could not increase open files limit: {e}")


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
            if any(
                x in iface.lower()
                for x in [
                    "virtual",
                    "vmnet",
                    "loopback",
                    "docker",
                    "veth",
                    "virbr",
                    "tun",
                    "tap",
                ]
            ) or iface.startswith(("lo", "br-")):
                continue

            # Check if interface is up
            try:
                stats = psutil.net_if_stats().get(iface)
                if stats and not stats.isup:
                    continue
            except (AttributeError, KeyError):
                pass

            for addr in addrs:
                if addr.family == socket.AF_INET and not addr.address.startswith(
                    "127."
                ):
                    # Skip invalid or link-local addresses
                    if addr.address.startswith(
                        ("169.254.", "0.")
                    ) or addr.address.endswith((".0", ".255")):
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
            result = subprocess.run(
                ["ip", "route", "get", "8.8.8.8"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                for line in result.stdout.split("\n"):
                    if "src" in line:
                        parts = line.split()
                        src_idx = parts.index("src")
                        if src_idx + 1 < len(parts):
                            ip = parts[src_idx + 1]
                            if not ip.startswith("127."):
                                (
                                    local_ips
                                    if ip.startswith(("192.168.", "10.", "172."))
                                    else other_ips
                                ).append(ip)
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
        log.debug("Certificate and key already exist")
        if get_cert_fingerprint(cert_path):
            log.debug("Existing certificate is valid")
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

        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(
                x509.SubjectAlternativeName(
                    [
                        x509.DNSName("localhost"),
                        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                    ]
                ),
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
        # Cleanup partial files
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
