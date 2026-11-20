# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import gettext
import json
import logging
import platform
import socket
import threading
import time
import uuid

from ..core.logging import log_telemetry_event

log = logging.getLogger(__name__)
_ = gettext.gettext

# Define constants for discovery protocol.
DISCOVERY_PORT = 38099
BEACON_MAGIC = "PCLINK_DISCOVERY_BEACON_V1"
REQUEST_MAGIC = "PCLINK_DISCOVERY_REQUEST_V1"
BEACON_INTERVAL = 1.5
BROADCAST_REFRESH_INTERVAL = 3.0
RECV_TIMEOUT = 0.25


class DiscoveryService:
    """Interface for LAN discovery beacons with automated socket auto-rebind."""

    def __init__(self, api_port: int, hostname: str, server_id: str = None):
        """
        Setup discovery state.

        Args:
            api_port: The port the PCLink API server is running on.
            hostname: The hostname of the server.
            server_id: An optional unique identifier for the server. If not provided, one is generated.
        """
        self.api_port = api_port
        self.hostname = hostname
        self.server_id = server_id or self.generate_server_id()
        self._thread: threading.Thread | None = None
        self._running = False
        self._socket: socket.socket | None = None
        self._listening = False
        self._last_payload: bytes | None = None
        self._last_ips: list[str] = []

    @staticmethod
    def generate_server_id() -> str:
        """Generate deterministic UUID from hardware profile."""
        system_info = f"{platform.node()}-{platform.system()}-{platform.machine()}"
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, system_info))

    def _get_beacon_payload(self) -> bytes:
        """Prepare JSON beacon payload with the current network addresses."""
        try:
            from ..core.version import __version__ as _ver
        except Exception:
            _ver = "unknown"

        from ..core.config import config_manager
        from ..core.utils import get_available_ips

        ips = get_available_ips()
        self._last_ips = ips

        payload = {
            "magic": BEACON_MAGIC,
            "port": self.api_port,
            "hostname": self.hostname,
            "https": True,
            "os": platform.system().lower(),
            "server_id": self.server_id,
            "version": _ver,
            "ips": ips,
            "remote_access_url": config_manager.get("remote_access_url", ""),
        }
        return json.dumps(payload).encode("utf-8")

    def _init_socket(self) -> bool:
        """Initialize or re-bind UDP socket safely."""
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass

        try:
            self._socket = socket.socket(
                socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
            )
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            if hasattr(socket, "SO_REUSEPORT"):
                try:
                    self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except OSError:
                    pass

            self._socket.settimeout(RECV_TIMEOUT)
            self._smart_bind_socket()
            log_telemetry_event(
                "discovery",
                "socket_initialized",
                {"port": DISCOVERY_PORT, "listening": self._listening},
            )
            return True
        except Exception as e:
            log.error(_("Failed to initialize discovery UDP socket: {}").format(e))
            log_telemetry_event(
                "discovery",
                "socket_init_failed",
                {"error": str(e)},
                level=logging.ERROR,
            )
            return False

    def _broadcast_loop(self):
        """Beacon + probe responder loop with automatic socket recreation on network drop."""
        if not self._init_socket():
            return

        broadcast_addresses: list[str] = []
        last_addresses_refresh = 0.0
        last_beacon = 0.0
        previous_ips: list[str] = []

        log.info(_("Discovery service starting on port {}").format(DISCOVERY_PORT))

        while self._running:
            try:
                now = time.monotonic()

                if (
                    not broadcast_addresses
                    or now - last_addresses_refresh >= BROADCAST_REFRESH_INTERVAL
                ):
                    broadcast_addresses = self._get_broadcast_addresses()
                    last_addresses_refresh = now

                if now - last_beacon >= BEACON_INTERVAL:
                    self._last_payload = self._get_beacon_payload()
                    if self._last_ips != previous_ips:
                        if previous_ips:
                            log.info(
                                _("Discovery beacon IPs changed: {} -> {}").format(
                                    previous_ips, self._last_ips
                                )
                            )
                        previous_ips = list(self._last_ips)
                    last_beacon = now

                    for broadcast_addr in broadcast_addresses:
                        try:
                            self._socket.sendto(
                                self._last_payload, (broadcast_addr, DISCOVERY_PORT)
                            )
                        except OSError as e:
                            if (
                                getattr(e, "winerror", None) == 10051
                                or getattr(e, "errno", None) == 101
                            ):
                                log.debug(
                                    f"Skipping unreachable network: {broadcast_addr}"
                                )
                            else:
                                log.warning(
                                    _("Broadcast write error on {}: {}").format(
                                        broadcast_addr, e
                                    )
                                )
                                self._init_socket()
                                broadcast_addresses = []
                                break

                self._drain_requests()

            except Exception as e:
                log.error(_("Discovery broadcast exception: {}").format(e))
                self._init_socket()
                broadcast_addresses = []

        log.info(_("Discovery broadcast stopped."))
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass

    def _drain_requests(self):
        """Reply unicast to clients actively probing for a server."""
        if self._socket is None:
            return
        while self._running:
            try:
                data, addr = self._socket.recvfrom(2048)
            except socket.timeout:
                return
            except OSError as e:
                log.debug(f"Discovery receive error: {e}")
                self._init_socket()
                return

            try:
                payload = json.loads(data.decode("utf-8", errors="ignore"))
            except (ValueError, UnicodeDecodeError):
                continue

            if payload.get("magic") != REQUEST_MAGIC:
                continue

            requested_id = payload.get("server_id")
            if requested_id and requested_id != self.server_id:
                continue

            try:
                self._socket.sendto(
                    self._last_payload or self._get_beacon_payload(), addr
                )
            except OSError:
                pass

    def _smart_bind_socket(self) -> bool:
        """Bind to the discovery port when possible so active probes can be answered."""
        bind_attempts = [
            ("", DISCOVERY_PORT),
            ("0.0.0.0", DISCOVERY_PORT),
            ("", 0),
            ("0.0.0.0", 0),
            ("127.0.0.1", 0),
        ]

        for host, port in bind_attempts:
            try:
                self._socket.bind((host, port))
                self._listening = self._socket.getsockname()[1] == DISCOVERY_PORT
                if not self._listening:
                    log.debug(
                        "Discovery port busy; beacon-only mode on ephemeral port."
                    )
                return True
            except OSError:
                continue

        log.warning(
            _("Could not bind UDP socket explicitly, operating in unbound state.")
        )
        return False

    def _get_broadcast_addresses(self):
        """Resolve multiple broadcast targets across active network adapters."""
        broadcast_addresses = ["<broadcast>", "255.255.255.255"]

        try:
            import psutil

            try:
                stats = psutil.net_if_stats()
            except Exception:
                stats = {}

            for interface_name, interface_addrs in psutil.net_if_addrs().items():
                if (
                    interface_name.startswith(("lo", "docker", "br-", "veth", "virbr"))
                    or "virtual" in interface_name.lower()
                ):
                    continue

                try:
                    if_stats = stats.get(interface_name)
                    if not if_stats or not if_stats.isup:
                        continue
                except (AttributeError, KeyError):
                    pass

                for addr in interface_addrs:
                    if addr.family == socket.AF_INET:
                        if hasattr(addr, "broadcast") and addr.broadcast:
                            target_broadcast = addr.broadcast
                        elif addr.address and addr.netmask:
                            try:
                                import ipaddress

                                network = ipaddress.IPv4Network(
                                    f"{addr.address}/{addr.netmask}", strict=False
                                )
                                target_broadcast = str(network.broadcast_address)
                            except Exception:
                                continue
                        else:
                            continue

                        if (
                            target_broadcast
                            and target_broadcast not in broadcast_addresses
                        ):
                            broadcast_addresses.append(target_broadcast)

        except ImportError:
            try:
                import subprocess

                result = subprocess.run(
                    ["ip", "route", "show"], capture_output=True, text=True, timeout=2
                )
                if result.returncode == 0:
                    for line in result.stdout.split("\n"):
                        if "brd" in line:
                            parts = line.split()
                            try:
                                brd_idx = parts.index("brd")
                                if brd_idx + 1 < len(parts):
                                    brd_addr = parts[brd_idx + 1]
                                    if brd_addr not in broadcast_addresses:
                                        broadcast_addresses.append(brd_addr)
                            except (ValueError, IndexError):
                                continue
            except (subprocess.SubprocessError, FileNotFoundError):
                pass
        except Exception as e:
            log.debug(f"Error resolving broadcast addresses: {e}")

        return broadcast_addresses

    def start(self):
        """Launch background beacon thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._broadcast_loop, daemon=True, name="pclink-discovery"
        )
        self._thread.start()

    def stop(self):
        """Tear down beacon service."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
