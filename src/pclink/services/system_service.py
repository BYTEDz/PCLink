# src/pclink/services/system_service.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import logging
import os
import platform
import re
import socket
import subprocess
import sys
import time
from collections import deque
from typing import Any, Dict, List, Optional

import psutil

log = logging.getLogger(__name__)

# Cache for MAC address to avoid repeated slow probes
_mac_address_cache = {"mac": None, "timestamp": 0}
_MAC_CACHE_TTL = 3600  # 1 hour cache

SUBPROCESS_FLAGS = 0
if sys.platform == "win32":
    SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW


class NetworkMonitor:
    """Tracks network I/O throughput to calculate real-time transfer speeds."""

    def __init__(self):
        self.last_update = time.time()
        try:
            self.last_io = psutil.net_io_counters()
        except Exception:
            self.last_io = None
        self.last_speed = {"upload_mbps": 0.0, "download_mbps": 0.0}

    def get_speed(self) -> Dict[str, float]:
        if not self.last_io:
            return self.last_speed

        now = time.time()
        try:
            curr_io = psutil.net_io_counters()
        except Exception:
            return self.last_speed

        delta = now - self.last_update
        if delta < 0.2:  # Increased threshold for stability
            return self.last_speed

        up_mbps = (
            (curr_io.bytes_sent - self.last_io.bytes_sent) * 8 / delta
        ) / 1_000_000
        down_mbps = (
            (curr_io.bytes_recv - self.last_io.bytes_recv) * 8 / delta
        ) / 1_000_000

        self.last_speed = {
            "upload_mbps": round(max(0.0, up_mbps), 2),
            "download_mbps": round(max(0.0, down_mbps), 2),
        }
        self.last_update = now
        self.last_io = curr_io

        return self.last_speed


def _get_current_user():
    """Safely get the current user name, handling headless/service environments."""
    try:
        return os.getlogin()
    except OSError:
        try:
            import pwd

            return pwd.getpwuid(os.getuid()).pw_name
        except (ImportError, KeyError):
            return os.environ.get("USER", os.environ.get("USERNAME", "unknown"))


class SystemService:
    """Logic for system operations: power, volume, telemetry."""

    def __init__(self):
        self._network_monitor = NetworkMonitor()
        # Response cache for frequently polled endpoints
        self._system_info_cache = None
        self._system_info_cache_time = 0
        self._SYSTEM_INFO_TTL = 0.5  # 500ms cache

        # Thermal data cache (Windows PowerShell calls are expensive)
        self._thermals_cache: Dict[str, float] = {}
        self._thermals_cache_time = 0
        self._THERMALS_TTL = 30  # 30 seconds - temperature doesn't change fast

        # Telemetry History (for smooth graphs on connection)
        self._telemetry_history = deque(maxlen=20)
        self._last_light_snapshot = None
        self._background_task = None

        # Initialize psutil markers to avoid zero values on first call
        try:
            psutil.cpu_percent(interval=None)
            psutil.cpu_stats()
            psutil.net_io_counters()
        except Exception:
            pass

    async def start_background_collection(self):
        """Starts the low-impact background telemetry collection."""
        if self._background_task and not self._background_task.done():
            return

        self._background_task = asyncio.create_task(self._collection_loop())

    async def _collection_loop(self):
        """Infinite loop for light telemetry snapshots."""
        from ..api_server.ws_manager import mobile_manager

        while True:
            try:
                # 1. Collect ONLY light stats (extremely cheap)
                snapshot = await asyncio.to_thread(self._get_light_snapshot)
                self._last_light_snapshot = snapshot
                self._telemetry_history.append(
                    {"timestamp": time.time(), "data": snapshot}
                )

                # 2. Adaptive sleeping: poll faster if someone is watching
                if mobile_manager.active_connections:
                    await asyncio.sleep(1.0)
                else:
                    await asyncio.sleep(3.0)  # Very low impact when idle
            except Exception as e:
                log.debug(f"Telemetry collection error: {e}")
                await asyncio.sleep(5)

    def _get_light_snapshot(self) -> Dict[str, Any]:
        """Captures minimal stats needed for graphs without heavy OS probes."""
        mem = psutil.virtual_memory()
        return {
            "cpu": {"percent": psutil.cpu_percent(interval=None)},
            "ram": {
                "percent": mem.percent,
                "used_gb": round(mem.used / (1024**3), 2),
            },
            "network": {"speed": self._network_monitor.get_speed()},
        }

    def get_telemetry_history(self) -> List[Dict[str, Any]]:
        """Returns the rolling history of light snapshots."""
        return list(self._telemetry_history)

    async def run_command(self, cmd: List[str], timeout: float = 5.0) -> str:
        """Asynchronously runs a command and returns its stdout."""
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=SUBPROCESS_FLAGS,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                log.warning(f"Command timed out after {timeout}s: {cmd[0]}")
                raise RuntimeError(f"Command timed out: {cmd[0]}")

            if process.returncode != 0:
                error_msg = stderr.decode().strip()
                log.debug(f"Command execution failed: {cmd} -> {error_msg}")
                raise RuntimeError(f"Command failed: {cmd[0]} - {error_msg}")

            return stdout.decode()
        except Exception as e:
            if isinstance(e, (FileNotFoundError, PermissionError)):
                log.debug(f"Command not available: {cmd[0]}")
            elif not isinstance(e, (RuntimeError, asyncio.TimeoutError)):
                log.error(f"Subprocess error for {cmd}: {e}")
            raise

    def _format_bytes(self, byte_count: int) -> str:
        """Formats bytes to human-readable string."""
        if byte_count >= 1024**3:
            return f"{byte_count / (1024**3):.1f} GB"
        return f"{byte_count / (1024**2):.0f} MB"

    async def get_disks_info(self) -> Dict[str, List[Dict[str, Any]]]:
        """Provides information about all mounted disk partitions."""
        return await asyncio.to_thread(self._get_sync_disks_info)

    def _get_sync_disks_info(self) -> Dict[str, List[Dict[str, Any]]]:
        disks_info = []
        for part in psutil.disk_partitions():
            if "cdrom" in part.opts or part.fstype == "":
                continue
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disks_info.append(
                    {
                        "device": part.mountpoint,
                        "total": self._format_bytes(usage.total),
                        "used": self._format_bytes(usage.used),
                        "free": self._format_bytes(usage.free),
                        "percent": int(usage.percent),
                    }
                )
            except (PermissionError, FileNotFoundError):
                continue
        return {"disks": disks_info}

    async def get_system_info(self) -> Dict[str, Any]:
        """Aggregates all system-level telemetry with 500ms caching."""
        now = time.time()
        if (
            self._system_info_cache
            and (now - self._system_info_cache_time) < self._SYSTEM_INFO_TTL
        ):
            return self._system_info_cache

        result = await asyncio.to_thread(self._get_sync_system_info)
        self._system_info_cache = result
        self._system_info_cache_time = now
        return result

    def _safe_get_battery(self) -> Dict[str, Any]:
        if not hasattr(psutil, "sensors_battery"):
            return {}
        try:
            battery = psutil.sensors_battery()
            if battery:
                return {
                    "percent": round(battery.percent, 1),
                    "power_plugged": battery.power_plugged,
                    "secsleft": (
                        battery.secsleft
                        if battery.secsleft != psutil.POWER_TIME_UNLIMITED
                        else None
                    ),
                }
        except Exception as e:
            log.debug(f"Failed to read battery sensors: {e}")
        return {}

    def _safe_get_cpu_metrics(self, freq) -> Dict[str, Any]:
        try:
            return {
                "percent": psutil.cpu_percent(interval=0.1),
                "per_cpu_percent": psutil.cpu_percent(interval=None, percpu=True),
                "physical_cores": psutil.cpu_count(logical=False),
                "total_cores": psutil.cpu_count(logical=True),
                "current_freq_mhz": freq.current if freq else None,
                "max_freq_mhz": freq.max if freq else None,
            }
        except Exception as e:
            log.debug(f"Failed to read CPU metrics: {e}")
            return {}

    def _safe_get_ram_metrics(self, mem) -> Dict[str, Any]:
        try:
            return {
                "percent": mem.percent,
                "total_gb": round(mem.total / (1024**3), 2),
                "used_gb": round(mem.used / (1024**3), 2),
                "available_gb": round(mem.available / (1024**3), 2),
            }
        except Exception as e:
            log.debug(f"Failed to read RAM metrics: {e}")
            return {}

    def _safe_get_swap_metrics(self, swap) -> Dict[str, Any]:
        try:
            return {
                "percent": swap.percent,
                "total_gb": round(swap.total / (1024**3), 2),
                "used_gb": round(swap.used / (1024**3), 2),
                "free_gb": round(swap.free / (1024**3), 2),
            }
        except Exception as e:
            log.debug(f"Failed to read SWAP metrics: {e}")
            return {}

    def _safe_get_disk_io_metrics(self) -> Optional[Dict[str, Any]]:
        try:
            io_counters = psutil.disk_io_counters(perdisk=False)
            if io_counters:
                return {
                    "read_bytes": io_counters.read_bytes,
                    "write_bytes": io_counters.write_bytes,
                    "read_count": io_counters.read_count,
                    "write_count": io_counters.write_count,
                }
        except Exception as e:
            log.debug(f"Failed to read Disk I/O metrics: {e}")
        return None

    def _safe_get_network_metrics(self, speed) -> Dict[str, Any]:
        net_info = {}
        try:
            addrs = psutil.net_if_addrs()
            stats = psutil.net_if_stats()
            for nic, nic_addrs in addrs.items():
                ipv4 = None
                for a in nic_addrs:
                    if a.family == socket.AF_INET:
                        ipv4 = a.address
                        break
                if ipv4:
                    net_info[nic] = {
                        "ip": ipv4,
                        "is_up": stats[nic].isup if nic in stats else False,
                        "speed_mbps": stats[nic].speed if nic in stats else 0,
                    }
        except Exception as e:
            log.debug(f"Failed to read network interfaces: {e}")

        try:
            return {
                "speed": speed,
                "io_total": psutil.net_io_counters()._asdict(),
                "interfaces": net_info,
            }
        except Exception as e:
            log.debug(f"Failed to read network I/O counters: {e}")
            return {"speed": speed, "io_total": {}, "interfaces": net_info}

    def _safe_get_active_users(self) -> List[Dict[str, Any]]:
        active_users = []
        try:
            for u in psutil.users():
                active_users.append(
                    {
                        "name": u.name,
                        "terminal": u.terminal,
                        "host": u.host,
                        "started": int(u.started),
                    }
                )
        except Exception as e:
            log.debug(f"Failed to read active users: {e}")
        return active_users

    def _safe_get_load_avg(self) -> List[float]:
        try:
            if hasattr(os, "getloadavg"):
                return list(os.getloadavg())
        except Exception as e:
            log.debug(f"Failed to read load average: {e}")
        return []

    def _safe_get_fans(self) -> Dict[str, Any]:
        fans = {}
        if hasattr(psutil, "sensors_fans"):
            try:
                raw_fans = psutil.sensors_fans()
                for label, entries in raw_fans.items():
                    fans[label] = [
                        {"label": f.label, "current": f.current} for f in entries
                    ]
            except Exception as e:
                log.debug(f"Failed to read fan sensors: {e}")
        return fans

    def _safe_get_unix_thermals(self) -> Dict[str, float]:
        temps = {}
        if hasattr(psutil, "sensors_temperatures"):
            try:
                raw_temps = psutil.sensors_temperatures()
                if raw_temps:
                    # Look for common CPU temperature sensor labels
                    for label in ["coretemp", "k10temp", "package_id_0", "cpu_thermal"]:
                        if label in raw_temps and raw_temps[label]:
                            temps["cpu_temp_celsius"] = raw_temps[label][0].current
                            break
            except Exception as e:
                log.debug(f"Failed to read Unix thermal sensors: {e}")
        return temps

    def _get_sync_system_info(self) -> Dict[str, Any]:
        """Synchronous CPU/RAM/Disk/Network telemetry."""
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        freq = psutil.cpu_freq()
        boot = psutil.boot_time()
        uptime = time.time() - boot
        speed = self._network_monitor.get_speed()

        # Thermal Detection
        if sys.platform == "win32":
            temps = self._get_windows_thermals()
        else:
            temps = self._safe_get_unix_thermals()

        # OS Details
        os_family = platform.system()
        os_release = platform.release()
        os_name = f"{os_family} {os_release}"
        os_distro = "unknown"
        machine_arch = platform.machine()

        if os_family == "Linux":
            try:
                import distro

                os_distro = distro.id()
                os_name = f"{distro.name()} {distro.version()}"
            except ImportError:
                if os.path.exists("/etc/os-release"):
                    with open("/etc/os-release", "r") as f:
                        content = f.read()
                        name_match = re.search(
                            r'^NAME=["\']?(.+?)["\']?$', content, re.M
                        )
                        version_match = re.search(
                            r'^VERSION_ID=["\']?(.+?)["\']?$', content, re.M
                        )
                        id_match = re.search(r'^ID=["\']?(.+?)["\']?$', content, re.M)
                        if id_match:
                            os_distro = id_match.group(1).lower()
                        if name_match:
                            os_name = name_match.group(1)
                            if version_match:
                                os_name += f" {version_match.group(1)}"
            except Exception as e:
                log.debug(f"Failed to determine Linux distribution: {e}")

        if os_family == "Windows":
            os_distro = "windows"
            try:
                ver = sys.getwindowsversion()
                if ver.major == 10 and ver.build >= 22000:
                    os_name = "Windows 11"
            except Exception as e:
                log.debug(f"Failed to refine Windows version: {e}")

        from .discovery_service import DiscoveryService

        return {
            "os": os_name,
            "os_family": os_family.lower(),
            "os_distro": os_distro,
            "os_kernel": os_release,
            "arch": machine_arch,
            "python_version": platform.python_version(),
            "hostname": socket.gethostname(),
            "server_id": DiscoveryService.generate_server_id(),
            "uptime_seconds": int(uptime),
            "boot_time": int(boot),
            "procs": len(psutil.pids()),
            "users": self._safe_get_active_users(),
            "load_avg": self._safe_get_load_avg(),
            "battery": self._safe_get_battery(),
            "cpu": self._safe_get_cpu_metrics(freq),
            "ram": self._safe_get_ram_metrics(mem),
            "swap": self._safe_get_swap_metrics(swap),
            "disk_io": self._safe_get_disk_io_metrics(),
            "network": self._safe_get_network_metrics(speed),
            "sensors": temps,
            "fans": self._safe_get_fans(),
        }

    def _get_windows_thermals(self) -> Dict[str, float]:
        """Provides CPU temperature using native WMI (avoids expensive PowerShell spawning)."""
        now = time.time()
        if (
            self._thermals_cache
            and (now - self._thermals_cache_time) < self._THERMALS_TTL
        ):
            return self._thermals_cache

        thermals = {}
        try:
            import pythoncom
            import win32com.client

            pythoncom.CoInitialize()
            try:
                # 1. Try ACPI Thermal Zone (Standard Windows)
                try:
                    wmi_service = win32com.client.GetObject("winmgmts:\\\\.\\root\\WMI")
                    results = wmi_service.ExecQuery(
                        "SELECT CurrentTemperature FROM MSAcpi_ThermalZoneTemperature"
                    )
                    for item in results:
                        # Value is in tenths of Kelvin
                        temp_c = (item.CurrentTemperature - 2732) / 10.0
                        if 0 < temp_c < 125:
                            thermals["cpu_temp_celsius"] = round(temp_c, 1)
                            break
                except Exception:
                    pass

                # 2. Try LibreHardwareMonitor or OpenHardwareMonitor as robust fallbacks
                if "cpu_temp_celsius" not in thermals:
                    for ns in [
                        "root\\LibreHardwareMonitor",
                        "root\\OpenHardwareMonitor",
                    ]:
                        try:
                            wmi_service = win32com.client.GetObject(
                                f"winmgmts:\\\\.\\{ns}"
                            )
                            query = "SELECT Name, Value FROM Sensor WHERE SensorType='Temperature'"
                            sensors = wmi_service.ExecQuery(query)
                            for sensor in sensors:
                                name = sensor.Name.lower()
                                if "cpu" in name and (
                                    "package" in name
                                    or "core" in name
                                    or "total" in name
                                ):
                                    thermals["cpu_temp_celsius"] = float(sensor.Value)
                                    break
                            if "cpu_temp_celsius" in thermals:
                                break
                        except Exception:
                            continue
            finally:
                pythoncom.CoUninitialize()
        except Exception as e:
            log.debug(f"Windows thermal detection failed: {e}")

        self._thermals_cache = thermals
        self._thermals_cache_time = now
        return thermals

    async def get_volume(self) -> Dict[str, Any]:
        """Gets current master volume and mute status."""
        if sys.platform == "win32":
            return await asyncio.to_thread(self._get_volume_win32)
        elif sys.platform == "darwin":
            vol = await self.run_command(
                ["osascript", "-e", "output volume of (get volume settings)"]
            )
            muted = await self.run_command(
                ["osascript", "-e", "output muted of (get volume settings)"]
            )
            return {"level": int(vol.strip()), "muted": muted.strip() == "true"}
        else:
            return await self._get_volume_linux_fallback()

    def _get_volume_win32(self) -> Dict[str, Any]:
        import comtypes
        from comtypes import CLSCTX_ALL, CoInitialize, CoUninitialize

        try:
            CoInitialize()
            from pycaw.pycaw import IAudioEndpointVolume

            # Try to get enumerator interface/CLSID from pycaw, fallback to raw GUIDs
            try:
                from pycaw.constants import CLSID_MMDeviceEnumerator
                from pycaw.pycaw import IMMDeviceEnumerator
            except ImportError:
                IMMDeviceEnumerator = comtypes.GUID(
                    "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
                )
                CLSID_MMDeviceEnumerator = comtypes.GUID(
                    "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
                )

            enumerator = comtypes.CoCreateInstance(
                CLSID_MMDeviceEnumerator,
                IMMDeviceEnumerator,
                comtypes.CLSCTX_INPROC_SERVER,
            )
            # 0: eRender, 0: eConsole
            device = enumerator.GetDefaultAudioEndpoint(0, 0)
            interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = interface.QueryInterface(IAudioEndpointVolume)
            return {
                "level": round(volume.GetMasterVolumeLevelScalar() * 100),
                "muted": bool(volume.GetMute()),
            }
        except Exception as e:
            log.error(f"Ultimate volume fetch failure: {e}")
            raise
        finally:
            CoUninitialize()

    async def _get_volume_linux_fallback(self) -> Dict[str, Any]:
        methods = [
            (["amixer", "sget", "Master"], "amixer_master"),
            (["pactl", "get-sink-volume", "@DEFAULT_SINK@"], "pactl"),
        ]
        for cmd, method in methods:
            try:
                res = await self.run_command(cmd, timeout=1.0)
                if method == "amixer_master":
                    lvl = re.search(r"\[(\d+)%\]", res)
                    muted = re.search(r"\[off\]", res)
                    if lvl:
                        return {"level": int(lvl.group(1)), "muted": bool(muted)}
                elif method == "pactl":
                    lvl = re.search(r"(\d+)%", res)
                    mute_out = await self.run_command(
                        ["pactl", "get-sink-mute", "@DEFAULT_SINK@"], timeout=1.0
                    )
                    if lvl:
                        return {
                            "level": int(lvl.group(1)),
                            "muted": "yes" in mute_out.lower(),
                        }
            except Exception:
                continue
        raise RuntimeError("Volume control unavailable")

    async def set_volume(self, level: int):
        """Sets master volume (0-100)."""
        if not 0 <= level <= 100:
            raise ValueError("Volume must be 0-100")
        if sys.platform == "win32":
            await asyncio.to_thread(self._set_volume_win32, level)
        elif sys.platform == "darwin":
            if level == 0:
                await self.run_command(
                    ["osascript", "-e", "set volume output muted true"]
                )
            else:
                await self.run_command(
                    ["osascript", "-e", "set volume output muted false"]
                )
                await self.run_command(
                    ["osascript", "-e", f"set volume output volume {level}"]
                )
        else:
            if level == 0:
                await self.run_command(["amixer", "-q", "set", "Master", "mute"])
            else:
                await self.run_command(["amixer", "-q", "set", "Master", "unmute"])
                await self.run_command(["amixer", "-q", "set", "Master", f"{level}%"])

    def _set_volume_win32(self, level: int):
        import comtypes
        from comtypes import CLSCTX_ALL, CoInitialize, CoUninitialize

        try:
            CoInitialize()
            from pycaw.pycaw import IAudioEndpointVolume

            try:
                from pycaw.constants import CLSID_MMDeviceEnumerator
                from pycaw.pycaw import IMMDeviceEnumerator
            except ImportError:
                IMMDeviceEnumerator = comtypes.GUID(
                    "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
                )
                CLSID_MMDeviceEnumerator = comtypes.GUID(
                    "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
                )

            enumerator = comtypes.CoCreateInstance(
                CLSID_MMDeviceEnumerator,
                IMMDeviceEnumerator,
                comtypes.CLSCTX_INPROC_SERVER,
            )
            device = enumerator.GetDefaultAudioEndpoint(0, 0)
            interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = interface.QueryInterface(IAudioEndpointVolume)

            volume.SetMute(1 if level == 0 else 0, None)
            if level > 0:
                volume.SetMasterVolumeLevelScalar(level / 100, None)
        except Exception as e:
            log.error(f"Ultimate volume set failure: {e}")
            raise
        finally:
            CoUninitialize()

    async def power_command(self, command: str, hybrid: bool = True):
        """Handles shutdown, reboot, lock, sleep."""
        cmd_map = {
            "win32": {
                "shutdown": (
                    ["shutdown", "/s", "/hybrid", "/t", "1"]
                    if hybrid
                    else ["shutdown", "/s", "/t", "1"]
                ),
                "reboot": ["shutdown", "/r", "/t", "1"],
                "lock": ["rundll32.exe", "user32.dll,LockWorkStation"],
                "sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
                "logout": ["shutdown", "/l"],
            },
            "linux": {
                "shutdown": ["systemctl", "poweroff"],
                "reboot": ["systemctl", "reboot"],
                "lock": ["loginctl", "lock-session"],
                "sleep": ["systemctl", "suspend"],
                "logout": ["loginctl", "terminate-user", _get_current_user()],
            },
            "darwin": {
                "shutdown": [
                    "osascript",
                    "-e",
                    'tell app "System Events" to shut down',
                ],
                "reboot": ["osascript", "-e", 'tell app "System Events" to restart'],
                "lock": [
                    "osascript",
                    "-e",
                    'tell app "loginwindow" to  «event aevtrlok»',
                ],
                "sleep": ["pmset", "sleepnow"],
                "logout": ["osascript", "-e", 'tell app "System Events" to log out'],
            },
        }
        cmd = cmd_map.get(sys.platform, {}).get(command)
        if not cmd:
            raise ValueError(f"Unsupported command: {command}")

        if sys.platform == "linux":
            success = await self._try_power_command_linux(command, cmd)
            if not success:
                raise RuntimeError("Power command failed")
        else:
            await asyncio.to_thread(subprocess.run, cmd, creationflags=SUBPROCESS_FLAGS)

    async def _try_power_command_linux(self, command: str, primary: List[str]) -> bool:
        # Use -n to prevent hanging on password prompts
        fallbacks = {
            "shutdown": [["sudo", "-n", "systemctl", "poweroff"], ["poweroff"]],
            "reboot": [["sudo", "-n", "systemctl", "reboot"], ["reboot"]],
            "lock": [["loginctl", "lock-session"], ["xdg-screensaver", "lock"]],
            "sleep": [["sudo", "-n", "systemctl", "suspend"]],
            "logout": [["loginctl", "terminate-user", _get_current_user()]],
        }
        targets = [primary] + fallbacks.get(command, [])
        for t in targets:
            try:
                await self.run_command(t)
                return True
            except Exception as e:
                log.debug(f"Linux power command fallback '{t}' failed: {e}")
                continue
        return False

    async def get_wol_info(self) -> Dict[str, Any]:
        """Gets MAC address for Wake-on-LAN."""
        now = time.time()
        if _mac_address_cache["mac"] and (
            now - _mac_address_cache["timestamp"] < _MAC_CACHE_TTL
        ):
            return {"supported": True, "mac_address": _mac_address_cache["mac"]}

        try:
            from getmac import get_mac_address

            mac = await asyncio.to_thread(get_mac_address)
            if mac:
                _mac_address_cache["mac"] = mac
                _mac_address_cache["timestamp"] = now
                return {"supported": True, "mac_address": mac}
        except Exception:
            pass
        return {"supported": False, "mac_address": None}


# Global instance
system_service = SystemService()
