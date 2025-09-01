# file: api_server/discovery.py
"""
PCLink - Remote PC Control Server - Process Manager API Module
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

DISCOVERY_PORT = 38099
BEACON_MAGIC = "PCLINK_DISCOVERY_BEACON_V1"


class DiscoveryService:
    def __init__(self, api_port: int, hostname: str, use_https: bool, server_id: str = None):
        self.api_port = api_port
        self.hostname = hostname
        self.use_https = use_https
        self.server_id = server_id or self._generate_server_id()
        self._thread = None
        self._running = False
        self._socket = None

    def _generate_server_id(self) -> str:
        """Generate a unique server identifier"""
        import uuid
        import platform
        
        # Create a deterministic ID based on hostname and system info
        system_info = f"{platform.node()}-{platform.system()}-{platform.machine()}"
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, system_info))

    def _get_beacon_payload(self) -> bytes:
        import platform
        
        payload = {
            "magic": BEACON_MAGIC,
            "port": self.api_port,
            "hostname": self.hostname,
            "https": self.use_https,
            "os": platform.system().lower(),
            "server_id": self.server_id
        }
        return json.dumps(payload).encode("utf-8")

    def _broadcast_loop(self):
        self._socket = socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
        )
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._socket.settimeout(0.2)

        beacon_payload = self._get_beacon_payload()

        print(f"Starting discovery broadcast on port {DISCOVERY_PORT}")
        while self._running:
            try:
                self._socket.sendto(beacon_payload, ("<broadcast>", DISCOVERY_PORT))
            except Exception as e:
                print(f"Discovery broadcast error: {e}")
            time.sleep(5)  # Broadcast every 5 seconds

        print("Discovery broadcast stopped.")
        self._socket.close()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._broadcast_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
