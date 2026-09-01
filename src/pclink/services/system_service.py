# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import logging
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar

import psutil

log = logging.getLogger(__name__)

T = TypeVar("T")

_mac_address_cache = {"mac": None, "timestamp": 0}
_MAC_CACHE_TTL = 3600

SUBPROCESS_FLAGS = 0
if sys.platform == "win32":
    SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW


def safe_probe(
    probe_func: Callable[[], T], default: Any = None, name: str = "telemetry"
) -> Any:
    try:
        res = probe_func()
        return res if res is not None else (default if default is not None else {})
    except Exception as e:
        log.debug(f"Telemetry probe '{name}' failed: {e}")
        return default if default is not None else {}


def _get_volume_label(mountpoint: str, device: str) -> str:
    try:
        if sys.platform == "win32":
            import ctypes

            vol_buffer = ctypes.create_unicode_buffer(1024)
            fs_buffer = ctypes.create_unicode_buffer(1024)
            ctypes.windll.kernel32.GetVolumeInformationW(
                ctypes.c_wchar_p(mountpoint),
                vol_buffer,
                ctypes.sizeof(vol_buffer),
                None,
                None,
                None,
                fs_buffer,
                ctypes.sizeof(fs_buffer),
            )
            return vol_buffer.value or ""

        elif sys.platform.startswith("linux"):
            if "/media/" in mountpoint or "/run/media/" in mountpoint:
                return os.path.basename(mountpoint.rstrip("/"))
            by_label = Path("/dev/disk/by-label")
            if by_label.exists() and device:
                dev_name = os.path.basename(device)
                for link in by_label.iterdir():
                    try:
                        if (
                            link.is_symlink()
                            and os.path.basename(os.readlink(link)) == dev_name
                        ):
                            return link.name
                    except Exception:
                        continue

        elif sys.platform == "darwin":
            if mountpoint.startswith("/Volumes/"):
                return os.path.basename(mountpoint)
    except Exception:
        pass
    return ""


class NetworkMonitor:
    def __init__(self):
        self.last_update = time.time()
        self._lock = threading.Lock()
        try:
            self.last_io = self._get_filtered_io()
        except Exception:
            self.last_io = None
        self.last_speed = {"upload_mbps": 0.0, "download_mbps": 0.0}

    def _get_filtered_io(self) -> Optional[Tuple[int, int]]:
        """Sum I/O counters strictly across active physical network adapters, excluding loopback."""
        try:
            per_nic = psutil.net_io_counters(pernic=True)
            stats = psutil.net_if_stats()
        except Exception:
            return None

        total_sent = 0
        total_recv = 0
        has_matched = False

        ignored_prefixes = (
            "lo",
            "br-",
            "docker",
            "veth",
            "virbr",
            "vmnet",
            "tun",
            "tap",
            "wg",
            "tailscale",
        )

        for iface, io in per_nic.items():
            iface_lower = iface.lower()
            if iface_lower.startswith(ignored_prefixes) or any(
                x in iface_lower
                for x in [
                    "loopback",
                    "virtual",
                    "vethernet",
                    "hyper-v",
                    "wsl",
                    "default switch",
                ]
            ):
                continue

            if iface in stats and not stats[iface].isup:
                continue

            total_sent += io.bytes_sent
            total_recv += io.bytes_recv
            has_matched = True

        if not has_matched:
            global_io = psutil.net_io_counters(pernic=False)
            if global_io:
                return global_io.bytes_sent, global_io.bytes_recv
            return 0, 0

        return total_sent, total_recv

    def get_speed(self) -> Dict[str, float]:
        with self._lock:
            now = time.time()
            delta = now - self.last_update
            if delta < 0.4:
                return self.last_speed

            curr_io = self._get_filtered_io()
            if not curr_io or not self.last_io:
                self.last_io = curr_io
                self.last_update = now
                return self.last_speed

            curr_sent, curr_recv = curr_io
            last_sent, last_recv = self.last_io

            up_mbps = ((curr_sent - last_sent) * 8 / delta) / 1_000_000
            down_mbps = ((curr_recv - last_recv) * 8 / delta) / 1_000_000

            self.last_speed = {
                "upload_mbps": round(max(0.0, up_mbps), 2),
                "download_mbps": round(max(0.0, down_mbps), 2),
            }
            self.last_update = now
            self.last_io = curr_io

            return self.last_speed


def _get_current_user() -> str:
    try:
        return os.getlogin()
    except OSError:
        try:
            import pwd

            return pwd.getpwuid(os.getuid()).pw_name
        except (ImportError, KeyError):
            return os.environ.get("USER", os.environ.get("USERNAME", "unknown"))


class SystemService:
    def __init__(self):
        self._network_monitor = NetworkMonitor()

        self._system_info_cache = None
        self._system_info_cache_time = 0
        self._SYSTEM_INFO_TTL = 0.5

        self._slow_metrics_cache = {}
        self._slow_metrics_time = 0
        self._SLOW_METRICS_TTL = 5.0

        self._static_os_info = None

        self._thermals_cache: Dict[str, float] = {}
        self._thermals_cache_time = 0
        self._THERMALS_TTL = 30

        self._telemetry_history = deque(maxlen=20)
        self._last_light_snapshot = None
        self._background_task = None
        self._previous_disks = None

        try:
            psutil.cpu_percent(interval=None)
            psutil.cpu_stats()
            psutil.net_io_counters()
        except Exception:
            pass

    async def start_background_collection(self) -> None:
        if self._background_task and not self._background_task.done():
            return

        self._background_task = asyncio.create_task(self._collection_loop())

    async def _collection_loop(self) -> None:
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
        return list(self._telemetry_history)

    async def run_command(self, cmd: List[str], timeout: float = 5.0) -> str:
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
        if byte_count >= 1024**3:
            return f"{byte_count / (1024**3):.1f} GB"
        return f"{byte_count / (1024**2):.0f} MB"

    async def get_disks_info(self) -> Dict[str, List[Dict[str, Any]]]:
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
            "vfat",
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

        current_disk_set = set()

        for part in psutil.disk_partitions(all=False):
            if "cdrom" in part.opts or part.fstype.lower() in ignored_fstypes:
                continue

            mountpoint = part.mountpoint
            mountpoint_lower = mountpoint.lower()
            device_lower = part.device.lower()

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

            label = _get_volume_label(part.mountpoint, part.device)
            current_disk_set.add(part.mountpoint)

            try:
                usage = psutil.disk_usage(part.mountpoint)
                disks_info.append(
                    {
                        "device": part.mountpoint,
                        "label": label,
                        "total": self._format_bytes(usage.total),
                        "used": self._format_bytes(usage.used),
                        "free": self._format_bytes(usage.free),
                        "percent": int(usage.percent),
                    }
                )
            except (PermissionError, FileNotFoundError):
                continue

        if hasattr(self, "_previous_disks") and self._previous_disks is not None:
            new_disks = current_disk_set - self._previous_disks
            removed_disks = self._previous_disks - current_disk_set

            if new_disks or removed_disks:
                from ..api_server.ws_manager import mobile_manager, ui_manager

                for mount in new_disks:
                    matching_disk = next(
                        (d for d in disks_info if d["device"] == mount), None
                    )
                    label_name = (
                        matching_disk["label"]
                        if matching_disk and matching_disk.get("label")
                        else mount
                    )
                    msg = {
                        "type": "notification",
                        "data": {
                            "title": "Drive Connected",
                            "message": f"Storage device '{label_name}' is now available.",
                            "type": "info",
                        },
                    }
                    asyncio.create_task(mobile_manager.broadcast(msg))
                    asyncio.create_task(ui_manager.broadcast(msg))

        self._previous_disks = current_disk_set
        return {"disks": disks_info}

    def _get_static_os_info(self) -> Dict[str, str]:
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
        now = time.time()

        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        freq = psutil.cpu_freq()
        boot = psutil.boot_time()
        uptime = now - boot
        speed = self._network_monitor.get_speed()

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
        now = time.time()
        if (
            self._thermals_cache
            and (now - self._thermals_cache_time) < self._THERMALS_TTL
        ):
            return self._thermals_cache

        thermals = {}
        try:
            import pythoncom  # type: ignore[import-not-found, import-untyped]
            import win32com.client  # type: ignore[import-not-found, import-untyped]

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
        import comtypes  # type: ignore[import-not-found, import-untyped]
        from comtypes import CLSCTX_ALL, CoInitialize, CoUninitialize  # type: ignore[import-not-found, import-untyped]

        try:
            CoInitialize()
            from pycaw.pycaw import IAudioEndpointVolume  # type: ignore[import-not-found, import-untyped]

            try:
                from pycaw.constants import CLSID_MMDeviceEnumerator  # type: ignore[import-not-found, import-untyped]
                from pycaw.pycaw import IMMDeviceEnumerator  # type: ignore[import-not-found, import-untyped]
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
        if shutil.which("pactl"):
            try:
                res = await self.run_command(
                    ["pactl", "get-sink-volume", "@DEFAULT_SINK@"], timeout=1.0
                )
                mute_out = await self.run_command(
                    ["pactl", "get-sink-mute", "@DEFAULT_SINK@"], timeout=1.0
                )
                lvl = re.search(r"(\d+)%", res)
                if lvl:
                    return {
                        "level": int(lvl.group(1)),
                        "muted": "yes" in mute_out.lower(),
                    }
            except Exception:
                pass

        if shutil.which("wpctl"):
            try:
                res = await self.run_command(
                    ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"], timeout=1.0
                )
                m = re.search(r"Volume:\s*([0-9.]+)", res)
                if m:
                    level = int(round(float(m.group(1)) * 100))
                    return {
                        "level": min(100, max(0, level)),
                        "muted": "[MUTED]" in res,
                    }
            except Exception:
                pass

        if shutil.which("amixer"):
            for control in ["Master", "PCM", "Speaker"]:
                try:
                    res = await self.run_command(
                        ["amixer", "sget", control], timeout=1.0
                    )
                    lvl = re.search(r"\[(\d+)%\]", res)
                    muted = re.search(r"\[off\]", res)
                    if lvl:
                        return {
                            "level": int(lvl.group(1)),
                            "muted": bool(muted),
                        }
                except Exception:
                    continue

        return {"level": 100, "muted": False}

    async def set_volume(self, level: int):
        """Sets master volume (0-100)."""
        if not 0 <= level <= 100:
            raise ValueError("Volume must be between 0 and 100")

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
            await self._set_volume_linux(level)

    def _set_volume_win32(self, level: int):
        import comtypes  # type: ignore[import-not-found, import-untyped]
        from comtypes import CLSCTX_ALL, CoInitialize, CoUninitialize  # type: ignore[import-not-found, import-untyped]

        try:
            CoInitialize()
            from pycaw.pycaw import IAudioEndpointVolume  # type: ignore[import-not-found, import-untyped]

            try:
                from pycaw.constants import CLSID_MMDeviceEnumerator  # type: ignore[import-not-found, import-untyped]
                from pycaw.pycaw import IMMDeviceEnumerator  # type: ignore[import-not-found, import-untyped]
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

    async def _set_volume_linux(self, level: int):
        if shutil.which("pactl"):
            try:
                if level == 0:
                    await self.run_command(
                        ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"],
                        timeout=1.0,
                    )
                else:
                    await self.run_command(
                        ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"],
                        timeout=1.0,
                    )
                    await self.run_command(
                        ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"],
                        timeout=1.0,
                    )
                return
            except Exception as e:
                log.debug(f"pactl volume control failed: {e}")

        if shutil.which("wpctl"):
            try:
                vol_scalar = f"{level / 100.0:.2f}"
                if level == 0:
                    await self.run_command(
                        ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1"],
                        timeout=1.0,
                    )
                else:
                    await self.run_command(
                        ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"],
                        timeout=1.0,
                    )
                    await self.run_command(
                        ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", vol_scalar],
                        timeout=1.0,
                    )
                return
            except Exception as e:
                log.debug(f"wpctl volume control failed: {e}")

        if shutil.which("amixer"):
            for control in ["Master", "PCM", "Speaker"]:
                try:
                    if level == 0:
                        await self.run_command(
                            ["amixer", "-q", "set", control, "mute"], timeout=1.0
                        )
                    else:
                        await self.run_command(
                            ["amixer", "-q", "set", control, "unmute"], timeout=1.0
                        )
                        await self.run_command(
                            ["amixer", "-q", "set", control, f"{level}%"],
                            timeout=1.0,
                        )
                    return
                except Exception:
                    continue

        raise RuntimeError("No working audio control interface found on Linux host")

    async def power_command(self, command: str, hybrid: bool = True):
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
        now = time.time()
        if _mac_address_cache["mac"] and (
            now - _mac_address_cache["timestamp"] < _MAC_CACHE_TTL
        ):
            return {"supported": True, "mac_address": _mac_address_cache["mac"]}

        def _get_mac():
            try:
                for nic, addrs in psutil.net_if_addrs().items():
                    for addr in addrs:
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


system_service = SystemService()
