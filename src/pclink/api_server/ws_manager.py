from typing import Any, Dict, List

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        # Support multiple connections per device (Mobile app + Extensions)
        self.device_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, device_id: str = None):
        try:
            await websocket.accept()
        except RuntimeError:
            pass  # already accepted

        self.active_connections.append(websocket)
        if device_id:
            if device_id not in self.device_connections:
                self.device_connections[device_id] = []
            self.device_connections[device_id].append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

        # Remove from device map (cleanup lists)
        for dev_id, ws_list in list(self.device_connections.items()):
            if websocket in ws_list:
                ws_list.remove(websocket)
                if not ws_list:
                    del self.device_connections[dev_id]
                break

    async def disconnect_device(self, device_id: str):
        """Forcefully disconnect all paths for a specific device."""
        if ws_list := self.device_connections.get(device_id):
            # Create a copy to avoid modification during iteration
            for socket in list(ws_list):
                try:
                    # Using code 4003 to signal "Device Revoked" explicitly
                    await socket.close(code=4003, reason="Device revoked")
                except Exception:
                    pass
                finally:
                    # Logic safety: Ensure it's removed even if close fails
                    if socket in self.active_connections:
                        self.active_connections.remove(socket)

            # Final purge of the device list
            if device_id in self.device_connections:
                del self.device_connections[device_id]

    async def send_to_device(self, device_id: str, message: Dict[str, Any]):
        """Send a message to a specific device."""
        if ws_list := self.device_connections.get(device_id):
            for socket in ws_list:
                try:
                    await socket.send_json(message)
                except Exception:
                    pass

    async def broadcast(self, message: Dict[str, Any]):
        for connection in self.active_connections[:]:
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)


# Global singleton managers
mobile_manager = ConnectionManager()
ui_manager = ConnectionManager()
