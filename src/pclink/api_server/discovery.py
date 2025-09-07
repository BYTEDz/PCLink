"""
PCLink - Remote PC Control Server - Discovery API Module
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
        # Enable broadcast option on the socket.
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        # Set a short timeout for socket operations to allow graceful shutdown.
        self._socket.settimeout(0.2)

        beacon_payload = self._get_beacon_payload()

        print(f"Starting discovery broadcast on port {DISCOVERY_PORT}")  # Use logging in production.
        while self._running:
            try:
                # Send the beacon payload to the broadcast address and discovery port.
                self._socket.sendto(beacon_payload, ("<broadcast>", DISCOVERY_PORT))
            except Exception as e:
                # Log or handle potential socket errors.
                print(f"Discovery broadcast error: {e}")  # Use logging in production.
            # Wait for 5 seconds before sending the next beacon.
            time.sleep(5)

        print("Discovery broadcast stopped.")  # Use logging in production.
        self._socket.close()

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