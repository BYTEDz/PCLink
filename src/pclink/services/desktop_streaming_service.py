# src/pclink/services/desktop_streaming_service.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import gettext
import json
import logging
import os
import platform
import re
import subprocess
import tempfile
from pathlib import Path

from ..core.utils import resource_path

logger = logging.getLogger(__name__)
_ = gettext.gettext

OS_TYPE = platform.system().lower()
ARCH_RAW = platform.machine().lower()

if ARCH_RAW in ["amd64", "x86_64"]:
    ARCH_NAME = "x86_64"
elif ARCH_RAW in ["aarch64", "arm64"]:
    ARCH_NAME = "arm64"
else:
    ARCH_NAME = ARCH_RAW

if OS_TYPE == "windows":
    BIN_NAME = "ferrumcast.exe"
    IPC_PATH = r"\\.\pipe\ferrumcast"
    TOKEN_FILE = str(Path(tempfile.gettempdir()) / "ferrumcast.token")
else:
    BIN_NAME = "ferrumcast"
    IPC_PATH = "/tmp/ferrumcast.sock"
    TOKEN_FILE = str(
        Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        / "ferrumcast.token"
    )

STRUCTURED_PATH = resource_path(
    f"src/pclink/assets/bin/{OS_TYPE}_{ARCH_NAME}/{BIN_NAME}"
)
LEGACY_PATH = resource_path(f"src/pclink/assets/bin/{BIN_NAME}")

if STRUCTURED_PATH.exists():
    ENGINE_PATH = STRUCTURED_PATH
else:
    ENGINE_PATH = LEGACY_PATH


class DesktopStreamingService:
    def __init__(self):
        self.process = None
        self.reader = None
        self.writer = None
        self.listen_task = None
        self._subscribers = {}  # callback -> name
        self._subscriber_ips = {}  # callback -> client_ip
        self._active_http_clients = set()  # IP addresses of HTTP POST streaming clients
        self.srtp_key = None

    def _engine_env(self) -> dict:
        """Prepare the environment for the FerrumCast engine process."""
        env = os.environ.copy()
        if OS_TYPE == "windows":
            candidates = [
                ENGINE_PATH.parent,
                Path(r"C:\Program Files\gstreamer\1.0\msvc_x86_64\bin"),
                Path(r"C:\gstreamer\1.0\msvc_x86_64\bin"),
            ]
            for base in candidates:
                if base.exists() and base.is_dir():
                    exe_dir = str(base)
                    path = env.get("PATH", "")
                    if exe_dir not in path:
                        env["PATH"] = exe_dir + os.pathsep + path
                    env["GST_PLUGIN_PATH"] = exe_dir
                    env["GST_PLUGIN_SYSTEM_PATH"] = ""
                    scanner = base / "gst-plugin-scanner.exe"
                    if scanner.exists():
                        env["GST_PLUGIN_SCANNER"] = str(scanner)
                    break
        return env

    def get_active_client_hosts(self, default_ip="127.0.0.1") -> str:
        """Returns comma-separated string of all active client IP addresses (WebSocket + HTTP POST clients)."""
        active_ips = set(self._subscriber_ips.values())
        active_ips.update(self._active_http_clients)
        active_ips.discard(None)
        active_ips.discard("")
        active_ips.discard("127.0.0.1")

        if not active_ips:
            return default_ip
        return ",".join(sorted(list(active_ips)))

    def remove_http_client(self, client_host: str):
        """Removes a client IP from active HTTP stream clients."""
        if client_host:
            for h in client_host.split(","):
                clean_h = h.strip()
                if clean_h:
                    self._active_http_clients.discard(clean_h)

    async def diagnose_system(self) -> dict:
        """Run diagnostics on mirroring subsystem."""
        import shutil

        info = {
            "platform": platform.system(),
            "binary_exists": ENGINE_PATH.exists(),
            "display_server": "unknown",
            "xdg_portal": "unknown",
            "pipewire": "unknown",
            "encoders": [],
            "status": "supported",
        }

        if platform.system() == "Linux":
            if os.environ.get("WAYLAND_DISPLAY"):
                info["display_server"] = (
                    f"Wayland ({os.environ.get('WAYLAND_DISPLAY')})"
                )
            elif os.environ.get("DISPLAY"):
                info["display_server"] = f"X11 ({os.environ.get('DISPLAY')})"
            else:
                info["display_server"] = "headless / no display server"
                info["status"] = "headless_unsupported"

            pipewire_running = False
            try:
                pw_socket = Path(f"/run/user/{os.getuid()}/pipewire-0")
                if pw_socket.exists() or shutil.which("pipewire") is not None:
                    pipewire_running = True
            except Exception:
                pass
            info["pipewire"] = "running" if pipewire_running else "not_detected"

            portal_running = False
            try:
                proc = await asyncio.create_subprocess_exec(
                    "pgrep",
                    "-f",
                    "xdg-desktop-portal",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                await proc.wait()
                if proc.returncode == 0:
                    portal_running = True
            except Exception:
                pass

            if not portal_running:
                try:
                    proc = await asyncio.create_subprocess_exec(
                        "systemctl",
                        "--user",
                        "is-active",
                        "xdg-desktop-portal",
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                    await proc.wait()
                    if proc.returncode == 0:
                        portal_running = True
                except Exception:
                    pass
            info["xdg_portal"] = "running" if portal_running else "not_detected"

        if info["binary_exists"]:
            try:
                proc = await asyncio.create_subprocess_exec(
                    str(ENGINE_PATH),
                    "--probe",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=self._engine_env(),
                    creationflags=subprocess.CREATE_NO_WINDOW
                    if platform.system() == "Windows"
                    else 0,
                )
                try:
                    stdout, stderr = await asyncio.wait_for(
                        proc.communicate(), timeout=10.0
                    )
                except asyncio.TimeoutError:
                    proc.kill()
                    info["probe_error"] = (
                        "Probe timeout (10s) - GStreamer initialization may be failing"
                    )
                    info["status"] = "binary_failure"
                    logger.error("FerrumCast probe timed out after 10 seconds")
                    return info
                if proc.returncode == 0:
                    lines = stdout.decode().strip().split("\n")
                    if lines:
                        caps = json.loads(lines[-1])
                        info["encoders"] = caps.get("encoders", [])
                else:
                    error_text = (
                        stderr.decode(errors="ignore").strip()
                        or stdout.decode(errors="ignore").strip()
                    )
                    logger.error(
                        f"FerrumCast probe failed (returncode={proc.returncode}): {error_text}"
                    )
                    info["probe_error"] = error_text
                    if platform.system() == "Windows":
                        info["status"] = "binary_failure"
                    else:
                        info["status"] = "gstreamer_error"
            except Exception as e:
                logger.error(f"Failed to probe engine capabilities: {e}")
                info["probe_error"] = str(e)
                if platform.system() == "Windows":
                    info["status"] = "binary_failure"
                else:
                    info["status"] = "gstreamer_error"

        if platform.system() == "Linux":
            if not info["binary_exists"]:
                info["status"] = "missing_binary"
            elif (
                "Wayland" in info["display_server"] and info["xdg_portal"] != "running"
            ):
                info["status"] = "wayland_missing_portal"
            elif not info["encoders"]:
                info["status"] = "gstreamer_error"
        elif platform.system() == "Windows":
            if not info["binary_exists"]:
                info["status"] = "missing_binary"

        return info

    def _engine_alive(self) -> bool:
        return self.process is not None and self.process.returncode is None

    async def _ensure_ipc(self) -> bool:
        """Connect to IPC if not already connected."""
        if self.writer and not self.writer.is_closing():
            return True

        self.reader = None
        self.writer = None

        if OS_TYPE == "windows":
            for _ in range(300):
                try:
                    pipe = await asyncio.wait_for(
                        asyncio.to_thread(open, IPC_PATH, "r+b", buffering=0),
                        timeout=2.0,
                    )
                    logger.info("Mirror engine IPC connected (Windows Named Pipe)")

                    class PipeReader:
                        def __init__(self, pipe):
                            self._pipe = pipe

                        async def readline(self):
                            return await asyncio.to_thread(self._pipe.readline)

                        def close(self):
                            try:
                                self._pipe.close()
                            except Exception:
                                pass

                    class PipeWriter:
                        def __init__(self, pipe):
                            self._pipe = pipe

                        async def write(self, data):
                            await asyncio.to_thread(self._pipe.write, data)

                        async def drain(self):
                            await asyncio.to_thread(self._pipe.flush)

                        def is_closing(self):
                            return False

                        def close(self):
                            try:
                                self._pipe.close()
                            except Exception:
                                pass

                    self.reader = PipeReader(pipe)
                    self.writer = PipeWriter(pipe)

                    if not self.listen_task or self.listen_task.done():
                        self.listen_task = asyncio.create_task(self._listen_ipc())
                    return True
                except asyncio.TimeoutError:
                    logger.debug("Pipe open timed out, retrying...")
                except Exception:
                    pass
                await asyncio.sleep(0.1)
        else:
            for _ in range(300):
                if os.path.exists(IPC_PATH):
                    try:
                        self.reader, self.writer = await asyncio.open_unix_connection(
                            IPC_PATH
                        )
                        logger.info("Mirror engine IPC connected")
                        if not self.listen_task or self.listen_task.done():
                            self.listen_task = asyncio.create_task(self._listen_ipc())
                        return True
                    except (ConnectionRefusedError, OSError):
                        pass
                await asyncio.sleep(0.1)
        return False

    async def start_engine(self, client_host=None, srtp_key=None, **kwargs):
        """Start or update engine. Supports multi-client unicast streaming."""
        self.srtp_key = srtp_key
        if not ENGINE_PATH.exists():
            logger.error(_("Mirror engine not found at {}").format(ENGINE_PATH))
            return False

        if client_host:
            for h in client_host.split(","):
                clean_h = h.strip()
                if clean_h:
                    self._active_http_clients.add(clean_h)

        config = {}
        for k, v in kwargs.items():
            snake_k = re.sub(r"(?<!^)(?=[A-Z])", "_", k).lower()
            config[snake_k] = v

        all_hosts = self.get_active_client_hosts(default_ip=client_host or "127.0.0.1")

        if self._engine_alive() and await self._ensure_ipc():
            logger.info(
                _(
                    "Engine alive, updating multi-client pipeline via IPC: hosts={} config={}"
                ).format(all_hosts, config)
            )
            cfg = {
                "type": "RESTART_PIPELINE",
                "output_mode": "rtp" if all_hosts else "webrtc",
                "client_host": all_hosts,
                "framerate": config.get("fps"),
                "srtp_key": srtp_key,
            }
            for key, val in config.items():
                if key not in cfg:
                    cfg[key] = val

            await self.send_command(cfg)
            return True

        if self.process:
            try:
                self.process.terminate()
                await self.process.wait()
            except Exception:
                pass
        self.reader = None
        self.writer = None

        if os.path.exists(IPC_PATH):
            os.remove(IPC_PATH)

        args = [str(ENGINE_PATH)]

        ignored_keys = {
            "srtp",
            "srtp_key",
            "fps",
            "output_mode",
            "outputmode",
            "udp_host",
            "udphost",
            "token",
            "client_host",
        }

        for k, v in config.items():
            if v is None or k in ignored_keys:
                continue
            flag = f"--{k.replace('_', '-')}"
            if isinstance(v, bool):
                if v:
                    args.append(flag)
            else:
                args.extend([flag, str(v)])

        if fps := config.get("fps"):
            args.extend(["--fps", str(fps)])
        if srtp_key:
            args.extend(["--srtp-key", srtp_key])

        if os.path.exists(TOKEN_FILE):
            try:
                token = Path(TOKEN_FILE).read_text().strip()
                if token:
                    args += ["--token", token]
            except Exception:
                pass

        args += ["--output", "rtp", "--host", all_hosts]

        kwargs = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "env": self._engine_env(),
        }
        if OS_TYPE == "windows":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        logger.info(_("Starting mirror engine: {args}").format(args=args))
        self.process = await asyncio.create_subprocess_exec(*args, **kwargs)

        async def log_engine(stream, prefix):
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode(errors="ignore").strip()
                if text:
                    logger.info(f"MIRROR_ENGINE [{prefix}]: {text}")

        asyncio.create_task(log_engine(self.process.stdout, "OUT"))
        asyncio.create_task(log_engine(self.process.stderr, "ERR"))

        if await self._ensure_ipc():
            return True
        else:
            logger.error("Mirror engine IPC connection failed")
            return False

    async def stop_engine(self):
        """Actually terminate the engine process."""
        await self.kill_engine()

    async def kill_engine(self):
        """Terminate process."""
        if self.process:
            try:
                if OS_TYPE == "windows":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(self.process.pid)],
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=2.0)
            except Exception:
                pass
            self.process = None

        self.srtp_key = None
        self._active_http_clients.clear()
        if self.reader:
            self.reader.close()
        if self.writer:
            self.writer.close()
        self.reader = None
        self.writer = None
        if self.listen_task:
            self.listen_task.cancel()
            self.listen_task = None

    def reset_portal_token(self) -> bool:
        try:
            if os.path.exists(TOKEN_FILE):
                os.remove(TOKEN_FILE)
                return True
        except Exception:
            pass
        return False

    async def send_command(self, cmd: dict):
        if not self.writer or self.writer.is_closing():
            return
        normalized_cmd = {}
        if isinstance(cmd, dict):
            for k, v in cmd.items():
                snake_k = (
                    re.sub(r"(?<!^)(?=[A-Z])", "_", k).lower()
                    if isinstance(k, str)
                    else k
                )
                normalized_cmd[snake_k] = v
        else:
            normalized_cmd = cmd
        self.writer.write(json.dumps(normalized_cmd).encode() + b"\n")
        await self.writer.drain()

    async def _listen_ipc(self):
        while True:
            if not self.reader:
                await asyncio.sleep(0.5)
                continue
            try:
                line = await self.reader.readline()
            except Exception:
                self.reader = None
                self.writer = None
                break

            if not line:
                self.reader = None
                self.writer = None
                break

            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                for sub in list(self._subscribers.keys()):
                    asyncio.create_task(self._safe_notify(sub, msg))
            except Exception:
                pass

    def subscribe(self, callback, name="Unknown", client_ip="127.0.0.1"):
        self._subscribers[callback] = name
        self._subscriber_ips[callback] = client_ip

    async def _safe_notify(self, callback, msg):
        try:
            await callback(msg)
        except Exception:
            pass

    def unsubscribe(self, callback) -> int:
        self._subscribers.pop(callback, None)
        self._subscriber_ips.pop(callback, None)

        remaining_count = len(self._subscribers) + len(self._active_http_clients)
        if remaining_count > 0 and self._engine_alive():
            remaining_hosts = self.get_active_client_hosts()
            logger.info(
                f"Client unsubscribed. Updating pipeline with remaining hosts: {remaining_hosts}"
            )
            asyncio.create_task(
                self.send_command(
                    {"type": "RESTART_PIPELINE", "client_host": remaining_hosts}
                )
            )

        return remaining_count


desktop_streaming_service = DesktopStreamingService()
