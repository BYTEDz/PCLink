"""
PCLink - Remote PC Control Server - Global State Module
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

import threading
from typing import Dict, Any, Callable, List

# A thread-safe global store for connected devices.
# The structure is { "ip_address": {"last_seen": timestamp, "name": "Device Name"} }
connected_devices = {}
_device_lock = threading.RLock()

# Event callbacks for device state changes
_device_callbacks: List[Callable] = []
_pairing_callbacks: List[Callable[[str, str, str], None]] = []


def add_device_callback(callback: Callable):
    """Add a callback to be called when device list is updated."""
    _device_callbacks.append(callback)


def add_pairing_callback(callback: Callable[[str, str, str], None]):
    """Add a callback to be called when a pairing request is received."""
    _pairing_callbacks.append(callback)


def emit_device_list_updated():
    """Notify all callbacks that the device list has been updated."""
    for callback in _device_callbacks:
        try:
            callback()
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Error in device callback: {e}")


def emit_pairing_request(pairing_id: str, device_name: str, device_id: str):
    """Notify all callbacks about a pairing request."""
    for callback in _pairing_callbacks:
        try:
            callback(pairing_id, device_name, device_id)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Error in pairing callback: {e}")


# Controller reference for API access
controller = None
