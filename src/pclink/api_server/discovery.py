# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import json
import socket
import threading
import time
import uuid
import platform

# Define constants for discovery protocol.
DISCOVERY_PORT = 38099
BEACON_MAGIC = "PCLINK_DISCOVERY_BEACON_V1"


class DiscoveryService:
    """
    Manages network discovery for the PCLink server.

    Broadcasts UDP beacons containing server information and listens for responses.
    """

    def __init__(self, api_port: int, hostname: str, server_id: str = None):
        """
        Initializes the DiscoveryService.

        Args:
            api_port: The port the PCLink API server is running on.
            hostname: The hostname of the server.
            server_id: An optional unique identifier for the server. If not provided, one is generated.
        """
        self.api_port = api_port
        self.hostname = hostname
        self.server_id = server_id or self._generate_server_id()
        self._thread: threading.Thread | None = None
        self._running = False
        self._socket: socket.socket | None = None

    def _generate_server_id(self) -> str:
        """
        Generates a unique and deterministic server identifier based on system information.
        """
        # Create a UUID based on DNS namespace and system-specific details for consistency.
        system_info = f"{platform.node()}-{platform.system()}-{platform.machine()}"
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, system_info))

    def _get_beacon_payload(self) -> bytes:
        """
        Constructs the JSON payload for the discovery beacon.

        Includes server details like port, hostname, OS, and HTTPS status.
        """
        payload = {
            "magic": BEACON_MAGIC,
            "port": self.api_port,
            "hostname": self.hostname,
            "https": True,  # Indicates if the API server uses HTTPS.
            "os": platform.system().lower(),
            "server_id": self.server_id,
        }
        # Return the JSON payload encoded as UTF-8 bytes.
        return json.dumps(payload).encode("utf-8")

    def _broadcast_loop(self):
        """
        The main loop for broadcasting discovery beacons.

        Runs in a separate thread, sending UDP broadcast packets periodically.
        """
        # Create a UDP socket for broadcasting.
        self._socket = socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
        )
        
        try:
            # Enable broadcast option on the socket.
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            # Enable address reuse to avoid "Address already in use" errors
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            # Linux-specific: Enable SO_REUSEPORT if available
            if hasattr(socket, 'SO_REUSEPORT'):
                try:
                    self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except OSError:
                    pass  # Not all Linux versions support this
            
            # Set a short timeout for socket operations to allow graceful shutdown.
            self._socket.settimeout(0.2)
            
            # Smart binding: try different approaches for Linux compatibility
            self._smart_bind_socket()
                
        except Exception as e:
            print(f"Error setting up UDP socket: {e}")
            return

        beacon_payload = self._get_beacon_payload()
        broadcast_addresses = self._get_broadcast_addresses()

        import sys
        is_frozen = getattr(sys, "frozen", False)
        if not is_frozen:  # Only print in development
            print(f"Starting discovery broadcast on port {DISCOVERY_PORT}")
            print(f"Broadcasting to: {broadcast_addresses}")
        
        # Log to file for debugging frozen builds
        import logging
        log = logging.getLogger(__name__)
        log.info(f"Discovery service starting on port {DISCOVERY_PORT}")
        log.info(f"Broadcasting to {len(broadcast_addresses)} addresses: {broadcast_addresses}")
        
        while self._running:
            try:
                # Send to multiple broadcast addresses for better Linux compatibility
                for broadcast_addr in broadcast_addresses:
                    try:
                        self._socket.sendto(beacon_payload, (broadcast_addr, DISCOVERY_PORT))
                    except Exception as addr_error:
                        print(f"Failed to broadcast to {broadcast_addr}: {addr_error}")
                        
            except Exception as e:
                print(f"Discovery broadcast error: {e}")
                
            # Wait for 5 seconds before sending the next beacon.
            time.sleep(5)

        print("Discovery broadcast stopped.")
        if self._socket:
            self._socket.close()
    
    def _smart_bind_socket(self):
        """Smart socket binding with fallback options for Linux"""
        bind_attempts = [
            ('', 0),  # Any available port
            ('0.0.0.0', 0),  # Explicit any address
            ('127.0.0.1', 0),  # Localhost fallback
        ]
        
        for host, port in bind_attempts:
            try:
                self._socket.bind((host, port))
                return
            except OSError as e:
                continue
        
        # If all binding attempts fail, continue without binding
        print("Warning: Could not bind UDP socket, continuing anyway")

    def _get_broadcast_addresses(self):
        """Get all possible broadcast addresses for better Linux compatibility"""
        broadcast_addresses = ["<broadcast>", "255.255.255.255"]
        
        try:
            import psutil
            
            # Get broadcast addresses for all active network interfaces
            for interface_name, interface_addrs in psutil.net_if_addrs().items():
                # Skip loopback and virtual interfaces
                if (interface_name.startswith(('lo', 'docker', 'br-', 'veth', 'virbr')) or
                    'virtual' in interface_name.lower()):
                    continue
                
                # Check if interface is up
                try:
                    if_stats = psutil.net_if_stats().get(interface_name)
                    if not if_stats or not if_stats.isup:
                        continue
                except (AttributeError, KeyError):
                    pass
                    
                for addr in interface_addrs:
                    if addr.family == socket.AF_INET and hasattr(addr, 'broadcast') and addr.broadcast:
                        if addr.broadcast not in broadcast_addresses:
                            broadcast_addresses.append(addr.broadcast)
                            
        except ImportError:
            # Fallback: try to get broadcast addresses using system commands
            try:
                import subprocess
                result = subprocess.run(['ip', 'route', 'show'], capture_output=True, text=True, timeout=2)
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if 'brd' in line:
                            parts = line.split()
                            try:
                                brd_idx = parts.index('brd')
                                if brd_idx + 1 < len(parts):
                                    brd_addr = parts[brd_idx + 1]
                                    if brd_addr not in broadcast_addresses:
                                        broadcast_addresses.append(brd_addr)
                            except (ValueError, IndexError):
                                continue
            except (subprocess.SubprocessError, FileNotFoundError):
                pass
        except Exception as e:
            print(f"Error getting broadcast addresses: {e}")
            
        return broadcast_addresses

    def start(self):
        """Starts the discovery broadcast service in a new thread."""
        if self._running:
            return  # Service is already running.
        self._running = True
        # Create and start the broadcast thread. Daemon=True ensures it exits when the main program exits.
        self._thread = threading.Thread(target=self._broadcast_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stops the discovery broadcast service."""
        self._running = False
        # Wait for the broadcast thread to finish, with a timeout.
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)