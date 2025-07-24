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

from PySide6.QtCore import QObject, Signal

# A thread-safe global store for connected devices.
# The structure is { "ip_address": {"last_seen": timestamp, "name": "Device Name"} }
connected_devices = {}


class ApiSignalEmitter(QObject):
    """
    A Qt Signal emitter to allow the FastAPI thread to safely communicate
    with the main GUI thread.
    """

    device_list_updated = Signal()
    pairing_request = Signal(str, str)  # Emits pairing_id and device_name


# Global singleton instance of the signal emitter.
api_signal_emitter = ApiSignalEmitter()
