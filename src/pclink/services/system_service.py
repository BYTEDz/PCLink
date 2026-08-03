# src/pclink/services/system_service.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import gettext
import logging
import os
import platform
import re
import socket
import subprocess
import sys
import time
from collections import deque
from typing import Any, Callable, Dict, List, Optional, TypeVar

import psutil

log = logging.getLogger(__name__)
_ = gettext.gettext

T = TypeVar("T")

# Cache for MAC address to avoid repeated slow probes
_mac_address_cache = {"mac": None, "timestamp": 0}
_MAC_CACHE_TTL = 3600  # 1 hour cache

SUBPROCESS_FLAGS = 0
if sys.platform == "win32":
    SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW


def safe_probe(
    probe_func: Callable[[], T], default: Any = None, name: str = "telemetry"
) -> Any:
    """Generic wrapper to execute telemetry probes safely, returning standard defaults on error."""
    try:
        res = probe_func()
        return res if res is not None else (default if default is not None else {})
    except Exception as e:
        log.debug(f"Telemetry probe '{name}' failed: {e}")
        return default if default is not None else {}


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
        if delta < 0.2:  # Threshold for stability
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

        # Fast Cache (0.5s TTL)
        self._system_info_cache = None
        self._system_info_cache_time = 0
        self._SYSTEM_INFO_TTL = 0.5

        # Slow Cache (5s TTL) for WMI, Sysfs, Disk IO, Battery
        self._slow_metrics_cache = {}
        self._slow_metrics_time = 0
        self._SLOW_METRICS_TTL = 5.0

        # Static Cache (Never expires per process life)
        self._static_os_info = None

        self._thermals_cache: Dict[str, float] = {}
        self._thermals_cache_time = 0
        self._THERMALS_TTL = 30  # 30 seconds

        self._telemetry_history = deque(maxlen=20)
        self._last_light_snapshot = None
        self._background_task = None

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
                snapshot = await asyncio.to_thread(self._get_light_snapshot)
                self._last_light_snapshot = snapshot
                self._telemetry_history.append(
                    {"timestamp": time.time(), "data": snapshot}
                )

                if mobile_manager.active_connections:
                    await asyncio.sleep(1.0)
                else:
                    await asyncio.sleep(3.0)
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
                raise RuntimeError(_("Command timed out: {cmd}").format(cmd=cmd[0]))

            if process.returncode != 0:
                error_msg = stderr.decode().strip()
                log.debug(f"Command execution failed: {cmd} -> {error_msg}")
                raise RuntimeError(
                    _("Command failed: {cmd} - {error}").format(
                        cmd=cmd[0], error=error_msg
                    )
                )

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
        ignored_fstypes = {
            "",
            "overlay",
            "aufs",
            "squashfs",
            "tmpfs",
            "devtmpfs",
            "proc",
            "sysfs",
            "cgroup",
            "cgroup2",
            "nsfs",
            "ramfs",
            "rpc_pipefs",
            "devpts",
            "vfat",  # Usually boot/EFI FAT partitions on Linux
        }
        ignored_mount_prefixes = (
            "/var/lib/docker",
            "/var/lib/containerd",
            "/snap",
            "/var/snap",
            "/flatpak",
            "/dev",
            "/proc",
            "/sys",
            "/run",
            "/docker",
            "/containers",
            "/boot",
            "/efi",
        )

        for part in psutil.disk_partitions(all=False):
            if "cdrom" in part.opts or part.fstype.lower() in ignored_fstypes:
                continue

            mountpoint = part.mountpoint
            mountpoint_lower = mountpoint.lower()
            device_lower = part.device.lower()

            # Filter out Docker, Snap, Flatpak, Boot/EFI, and virtual/pseudo mountpoints
            if any(mountpoint_lower.startswith(p) for p in ignored_mount_prefixes):
                continue
            if "docker" in mountpoint_lower or "docker" in device_lower:
                continue
            if "containerd" in mountpoint_lower or "containerd" in device_lower:
                continue
            if device_lower.startswith("/dev/loop") or device_lower.startswith(
                "overlay"
            ):
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

    def _get_static_os_info(self) -> Dict[str, str]:
        """Fetches OS metadata that never changes (cached indefinitely)."""
        if self._static_os_info:
            return self._static_os_info

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

        self._static_os_info = {
            "os": os_name,
            "os_family": os_family.lower(),
            "os_distro": os_distro,
            "os_kernel": os_release,
            "arch": machine_arch,
            "python_version": platform.python_version(),
            "hostname": socket.gethostname(),
            "server_id": DiscoveryService.generate_server_id(),
        }
        return self._static_os_info

    async def get_system_info(self) -> Dict[str, Any]:
        """Aggregates system telemetry with tiered caching."""
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

        def _probe():
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
            return {}

        return safe_probe(_probe, default={}, name="battery")

    def _safe_get_cpu_metrics(self, freq) -> Dict[str, Any]:
        def _probe():
            return {
                "percent": psutil.cpu_percent(interval=0.1),
                "per_cpu_percent": psutil.cpu_percent(interval=None, percpu=True),
                "physical_cores": psutil.cpu_count(logical=False),
                "total_cores": psutil.cpu_count(logical=True),
                "current_freq_mhz": freq.current if freq else None,
                "max_freq_mhz": freq.max if freq else None,
            }

        return safe_probe(_probe, default={}, name="cpu_metrics")

    def _safe_get_ram_metrics(self, mem) -> Dict[str, Any]:
        def _probe():
            return {
                "percent": mem.percent,
                "total_gb": round(mem.total / (1024**3), 2),
                "used_gb": round(mem.used / (1024**3), 2),
                "available_gb": round(mem.available / (1024**3), 2),
            }

        return safe_probe(_probe, default={}, name="ram_metrics")

    def _safe_get_swap_metrics(self, swap) -> Dict[str, Any]:
        def _probe():
            return {
                "percent": swap.percent,
                "total_gb": round(swap.total / (1024**3), 2),
                "used_gb": round(swap.used / (1024**3), 2),
                "free_gb": round(swap.free / (1024**3), 2),
            }

        return safe_probe(_probe, default={}, name="swap_metrics")

    def _safe_get_disk_io_metrics(self) -> Optional[Dict[str, Any]]:
        def _probe():
            io_counters = psutil.disk_io_counters(perdisk=False)
            if io_counters:
                return {
                    "read_bytes": io_counters.read_bytes,
                    "write_bytes": io_counters.write_bytes,
                    "read_count": io_counters.read_count,
                    "write_count": io_counters.write_count,
                }
            return None

        return safe_probe(_probe, default=None, name="disk_io")

    def _safe_get_network_metrics(self, speed) -> Dict[str, Any]:
        def _probe():
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
                io_total = psutil.net_io_counters()._asdict()
            except Exception:
                io_total = {}

            return {
                "speed": speed,
                "io_total": io_total,
                "interfaces": net_info,
            }

        return safe_probe(
            _probe,
            default={"speed": speed, "io_total": {}, "interfaces": {}},
            name="network",
        )

    def _safe_get_active_users(self) -> List[Dict[str, Any]]:
        def _probe():
            active_users = []
            for u in psutil.users():
                active_users.append(
                    {
                        "name": u.name,
                        "terminal": u.terminal,
                        "host": u.host,
                        "started": int(u.started),
                    }
                )
            return active_users

        return safe_probe(_probe, default=[], name="active_users")

    def _safe_get_load_avg(self) -> List[float]:
        if not hasattr(os, "getloadavg"):
            return []
        return safe_probe(lambda: list(os.getloadavg()), default=[], name="load_avg")

    def _safe_get_fans(self) -> Dict[str, Any]:
        if not hasattr(psutil, "sensors_fans"):
            return {}

        def _probe():
            raw_fans = psutil.sensors_fans()
            return {
                label: [{"label": f.label, "current": f.current} for f in entries]
                for label, entries in raw_fans.items()
            }

        return safe_probe(_probe, default={}, name="fans")

    def _safe_get_unix_thermals(self) -> Dict[str, float]:
        if not hasattr(psutil, "sensors_temperatures"):
            return {}

        def _probe():
            raw_temps = psutil.sensors_temperatures()
            if raw_temps:
                for label in ["coretemp", "k10temp", "package_id_0", "cpu_thermal"]:
                    if label in raw_temps and raw_temps[label]:
                        return {"cpu_temp_celsius": raw_temps[label][0].current}
            return {}

        return safe_probe(_probe, default={}, name="unix_thermals")

    def _get_sync_system_info(self) -> Dict[str, Any]:
        """Synchronous CPU/RAM/Disk/Network telemetry with tiered caching."""
        now = time.time()

        # Fast Path (0.5s updates)
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        freq = psutil.cpu_freq()
        boot = psutil.boot_time()
        uptime = now - boot
        speed = self._network_monitor.get_speed()

        # Slow Path (5.0s updates) to prevent CPU spikes from WMI/SysFS
        if now - self._slow_metrics_time > self._SLOW_METRICS_TTL:
            temps = (
                self._get_windows_thermals()
                if sys.platform == "win32"
                else self._safe_get_unix_thermals()
            )
            self._slow_metrics_cache = {
                "users": self._safe_get_active_users(),
                "load_avg": self._safe_get_load_avg(),
                "battery": self._safe_get_battery(),
                "disk_io": self._safe_get_disk_io_metrics(),
                "sensors": temps,
                "fans": self._safe_get_fans(),
                "procs": len(psutil.pids()),
            }
            self._slow_metrics_time = now

        # Construct final payload
        payload = self._get_static_os_info().copy()

        payload.update(
            {
                "uptime_seconds": int(uptime),
                "boot_time": int(boot),
                "cpu": self._safe_get_cpu_metrics(freq),
                "ram": self._safe_get_ram_metrics(mem),
                "swap": self._safe_get_swap_metrics(swap),
                "network": self._safe_get_network_metrics(speed),
            }
        )

        payload.update(self._slow_metrics_cache)
        return payload

    def _get_windows_thermals(self) -> Dict[str, float]:
        """Provides CPU temperature using native WMI."""
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
                try:
                    wmi_service = win32com.client.GetObject("winmgmts:\\\\.\\root\\WMI")
                    results = wmi_service.ExecQuery(
                        "SELECT CurrentTemperature FROM MSAcpi_ThermalZoneTemperature"
                    )
                    for item in results:
                        temp_c = (item.CurrentTemperature - 2732) / 10.0
                        if 0 < temp_c < 125:
                            thermals["cpu_temp_celsius"] = round(temp_c, 1)
                            break
                except Exception:
                    pass

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
        raise RuntimeError(_("Volume control unavailable"))

    async def set_volume(self, level: int):
        """Sets master volume (0-100)."""
        if not 0 <= level <= 100:
            raise ValueError(_("Volume must be 0-100"))
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
            raise ValueError(
                _("Unsupported command: {command}").format(command=command)
            )

        if sys.platform == "linux":
            success = await self._try_power_command_linux(command, cmd)
            if not success:
                raise RuntimeError(_("Power command failed"))
        else:
            await asyncio.to_thread(subprocess.run, cmd, creationflags=SUBPROCESS_FLAGS)

    async def _try_power_command_linux(self, command: str, primary: List[str]) -> bool:
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
        """Gets MAC address for Wake-on-LAN using psutil."""
        now = time.time()
        if _mac_address_cache["mac"] and (
            now - _mac_address_cache["timestamp"] < _MAC_CACHE_TTL
        ):
            return {"supported": True, "mac_address": _mac_address_cache["mac"]}

        def _get_mac():
            try:
                for nic, addrs in psutil.net_if_addrs().items():
                    for addr in addrs:
                        # AF_LINK is the standard for MAC addresses
                        if addr.family == psutil.AF_LINK:
                            if addr.address and addr.address != "00:00:00:00:00:00":
                                return addr.address
            except Exception:
                pass
            return None

        mac = await asyncio.to_thread(_get_mac)
        if mac:
            _mac_address_cache["mac"] = mac
            _mac_address_cache["timestamp"] = now
            return {"supported": True, "mac_address": mac}

        return {"supported": False, "mac_address": None}


# Global instance
system_service = SystemService()
