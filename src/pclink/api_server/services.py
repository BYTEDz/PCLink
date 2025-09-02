# filename: src/pclink/api_server/services.py
"""
PCLink - Remote PC Control Server - API Services Module
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

import platform
import socket
import time
from typing import Dict

import psutil
from pynput.keyboard import Controller as KeyboardController
from pynput.keyboard import Key
from pynput.mouse import Button, Controller as MouseController


class NetworkMonitor:
    """A helper class to calculate network upload and download speeds."""
    def __init__(self):
        self.last_update_time = time.time()
        self.last_io_counters = psutil.net_io_counters()

    def get_speed(self) -> Dict[str, float]:
        current_time = time.time()
        current_io_counters = psutil.net_io_counters()
        time_delta = current_time - self.last_update_time
        if time_delta < 0.1:
            return {"upload_mbps": 0.0, "download_mbps": 0.0}
        
        bytes_sent_delta = current_io_counters.bytes_sent - self.last_io_counters.bytes_sent
        bytes_recv_delta = current_io_counters.bytes_recv - self.last_io_counters.bytes_recv
        
        upload_speed_mbps = (bytes_sent_delta * 8 / time_delta) / 1_000_000
        download_speed_mbps = (bytes_recv_delta * 8 / time_delta) / 1_000_000
        
        self.last_update_time = current_time
        self.last_io_counters = current_io_counters
        
        return {"upload_mbps": round(upload_speed_mbps, 2), "download_mbps": round(download_speed_mbps, 2)}


def get_media_info_data() -> Dict[str, str]:
    """Provides information about the currently playing media (placeholder)."""
    return {"title": "Nothing Playing", "artist": "", "status": "STOPPED"}


async def get_system_info_data(network_monitor: NetworkMonitor) -> Dict:
    """Provides general system information like OS, CPU, RAM, and network speed."""
    mem = psutil.virtual_memory()
    cpu_freq = psutil.cpu_freq()
    return {
        "os": f"{platform.system()} {platform.release()}",
        "hostname": socket.gethostname(),
        "cpu": {
            "percent": psutil.cpu_percent(interval=None),
            "physical_cores": psutil.cpu_count(logical=False),
            "total_cores": psutil.cpu_count(logical=True),
            "current_freq_mhz": cpu_freq.current if cpu_freq else 0,
        },
        "ram": {
            "percent": mem.percent,
            "total_gb": round(mem.total / (1024**3), 2),
            "used_gb": round(mem.used / (1024**3), 2),
        },
        "network_speed": network_monitor.get_speed(),
    }

# --- Shared Input Controllers and Mappings ---
mouse_controller = MouseController()
keyboard_controller = KeyboardController()

button_map = {"left": Button.left, "right": Button.right, "middle": Button.middle}

key_map = {
    'enter': Key.enter, 'esc': Key.esc, 'shift': Key.shift, 'ctrl': Key.ctrl, 
    'alt': Key.alt, 'cmd': Key.cmd, 'win': Key.cmd, 'backspace': Key.backspace, 
    'delete': Key.delete, 'tab': Key.tab, 'space': Key.space, 'up': Key.up, 
    'down': Key.down, 'left': Key.left, 'right': Key.right,
    'f1': Key.f1, 'f2': Key.f2, 'f3': Key.f3, 'f4': Key.f4, 'f5': Key.f5, 
    'f6': Key.f6, 'f7': Key.f7, 'f8': Key.f8, 'f9': Key.f9, 'f10': Key.f10, 
    'f11': Key.f11, 'f12': Key.f12
}

def get_key(key_str: str):
    return key_map.get(key_str.lower(), key_str)