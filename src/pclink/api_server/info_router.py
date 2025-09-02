# filename: src/pclink/api_server/info_router.py
"""
PCLink - Remote PC Control Server - Info API Module
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
import psutil
from fastapi import APIRouter, Request

from .services import NetworkMonitor, get_system_info_data

router = APIRouter()
network_monitor = NetworkMonitor()


@router.get("/system")
async def get_system_info(request: Request):
    """Provides general system information like OS, CPU, RAM, and network speed."""
    info = await get_system_info_data(network_monitor)
    info["allow_insecure_shell"] = request.app.state.allow_insecure_shell
    return info


@router.get("/disks")
async def get_disks_info():
    """Provides information about connected disk partitions."""
    disks = []
    for p in psutil.disk_partitions(all=False):
        if "cdrom" in p.opts or not p.fstype:
            continue
        try:
            usage = psutil.disk_usage(p.mountpoint)
            if usage.total > 0:
                disks.append({
                    "device": p.mountpoint,
                    "total": f"{usage.total / (1024**3):.2f} GB",
                    "used": f"{usage.used / (1024**3):.2f} GB",
                    "free": f"{usage.free / (1024**3):.2f} GB",
                    "percent": round(usage.percent),
                })
        except Exception:
            pass
    return {"disks": disks}