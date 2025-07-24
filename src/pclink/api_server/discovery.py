# file: api_server/discovery.py
import json
import socket
import threading
import time

DISCOVERY_PORT = 38099
BEACON_MAGIC = "PCLINK_DISCOVERY_BEACON_V1"


class DiscoveryService:
    def __init__(self, api_port: int, hostname: str, use_https: bool):
        self.api_port = api_port
        self.hostname = hostname
        self.use_https = use_https
        self._thread = None
        self._running = False
        self._socket = None

    def _get_beacon_payload(self) -> bytes:
        payload = {
            "magic": BEACON_MAGIC,
            "port": self.api_port,
            "hostname": self.hostname,
            "https": self.use_https,
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
