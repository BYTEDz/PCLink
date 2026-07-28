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
    TOKEN_FILE = "/tmp/ferrumcast.token"

# Compute the absolute paths for the native engine binary, supporting structured system directories with legacy fallbacks.

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
        self._subscribers = set()
        self.srtp_key = None

    def _engine_env(self) -> dict:
        """Prepare the environment for the FerrumCast engine process."""
        env = os.environ.copy()
        if OS_TYPE == "windows":
            candidates = [
                Path(r"C:\Program Files\gstreamer\1.0\msvc_x86_64"),
                Path(r"C:\gstreamer\1.0\msvc_x86_64"),
            ]
            for base in candidates:
                if base.exists() and base.is_dir():
                    gst_bin = base / "bin"
                    gst_plugin_path = base / "lib" / "gstreamer-1.0"
                    if gst_bin.exists():
                        path = env.get("PATH", "")
                        if str(gst_bin) not in path:
                            env["PATH"] = str(gst_bin) + os.pathsep + path
                    if gst_plugin_path.exists():
                        plugin_path = str(gst_plugin_path)
                        if (
                            "GST_PLUGIN_PATH" not in env
                            or plugin_path not in env["GST_PLUGIN_PATH"]
                        ):
                            env["GST_PLUGIN_PATH"] = plugin_path
                        if (
                            "GST_PLUGIN_SYSTEM_PATH" not in env
                            or plugin_path not in env["GST_PLUGIN_SYSTEM_PATH"]
                        ):
                            env["GST_PLUGIN_SYSTEM_PATH"] = plugin_path
                    scanner = gst_bin / "gst-plugin-scanner.exe"
                    if scanner.exists():
                        env["GST_PLUGIN_SCANNER"] = str(scanner)
                    break
        return env

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

    async def collect_engine_diagnostics(self) -> dict:
        """Collect GStreamer and environment diagnostics useful for debugging engine failures."""
        result = {
            "gst_inspect_version": None,
            "gst_inspect_plugins": None,
            "env": {},
            "errors": [],
        }

        env = self._engine_env()

        for key in (
            "PATH",
            "GST_PLUGIN_PATH",
            "GST_PLUGIN_SYSTEM_PATH",
            "GST_PLUGIN_SCANNER",
        ):
            result["env"][key] = env.get(key)

        async def run_cmd(*cmd):
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
                )
                stdout, stderr = await proc.communicate()
                return (
                    proc.returncode,
                    stdout.decode(errors="ignore"),
                    stderr.decode(errors="ignore"),
                )
            except FileNotFoundError as e:
                return 127, "", str(e)
            except Exception as e:
                return 1, "", str(e)

        code, out, err = await run_cmd("gst-inspect-1.0", "--version")
        if code == 0:
            result["gst_inspect_version"] = out.strip()
        else:
            result["errors"].append({"gst-inspect-version": err or out})

        plugins_to_check = [
            "webrtcbin",
            "d3d11screencapturesrc",
            "x264enc",
            "mfh264enc",
        ]
        plugin_outputs = {}
        for p in plugins_to_check:
            code, out, err = await run_cmd("gst-inspect-1.0", p)
            plugin_outputs[p] = {
                "returncode": code,
                "stdout": out.strip(),
                "stderr": err.strip(),
            }

        result["gst_inspect_plugins"] = plugin_outputs

        code, out, err = await run_cmd("gst-inspect-1.0", "--plugins")
        if code == 0:
            lines = [
                line
                for line in out.splitlines()
                if any(
                    k in line
                    for k in (
                        "webrtcbin",
                        "d3d11screencapturesrc",
                        "x264enc",
                        "mfh264enc",
                        "gstpython",
                    )
                )
            ]
            result["gst_plugins_list"] = "\n".join(lines)
        else:
            result["gst_plugins_list"] = err or out

        return result

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
        """Start or reuse engine. Dynamically forwards config params to IPC or CLI."""
        self.srtp_key = srtp_key
        if not ENGINE_PATH.exists():
            logger.error(_("Mirror engine not found at {}").format(ENGINE_PATH))
            return False

        # Defaults for CLI flags / IPC payload
        defaults = {
            "encoder": "auto",
            "bitrate": 4000,
            "audio": True,
            "gdi": False,
            "speed_preset": "ultrafast",
            "tune": "zerolatency",
            "nvenc_preset": "p4",
            "nvenc_tune": "ultra-low-latency",
            "vaapi_target_usage": 1,
            "qsv_target_usage": 7,
            "rc_mode": "cbr",
            "cqp_value": 26,
            "key_int_max": 60,
            "bframes": 0,
            "ref_frames": 1,
            "rtp_mtu": 1200,
            "queue_max_time_ns": 0,
            "queue_max_buffers": 2,
            "aggregate_mode": "zero-latency",
            "udp_buffer_size": 2097152,
            "show_cursor": True,
            "colorimetry": "bt709",
        }

        # Normalize camelCase to snake_case from incoming kwargs
        config = defaults.copy()
        for k, v in kwargs.items():
            snake_k = re.sub(r"(?<!^)(?=[A-Z])", "_", k).lower()
            config[snake_k] = v

        if self._engine_alive() and await self._ensure_ipc():
            logger.info(
                _(
                    "Engine alive, restarting pipeline via IPC: host={} encoder={} res={}x{}@{}"
                ).format(
                    client_host,
                    config.get("encoder"),
                    config.get("width"),
                    config.get("height"),
                    config.get("fps"),
                )
            )
            cfg = {
                "type": "RESTART_PIPELINE",
                "output_mode": "rtp" if client_host else "webrtc",
                "client_host": client_host or "127.0.0.1",
                "framerate": config.get("fps"),
                "srtp_key": srtp_key,
                **config,
            }
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

        # Map snake_case config keys to CLI flags e.g. speed_preset -> --speed-preset
        cli_key_map = {
            "speed_preset": "--speed-preset",
            "nvenc_preset": "--nvenc-preset",
            "nvenc_tune": "--nvenc-tune",
            "vaapi_target_usage": "--vaapi-target-usage",
            "qsv_target_usage": "--qsv-target-usage",
            "rc_mode": "--rc-mode",
            "cqp_value": "--cqp-value",
            "key_int_max": "--key-int-max",
            "ref_frames": "--ref-frames",
            "rtp_mtu": "--rtp-mtu",
            "queue_max_time_ns": "--queue-max-time-ns",
            "queue_max_buffers": "--queue-max-buffers",
            "aggregate_mode": "--aggregate-mode",
            "udp_buffer_size": "--udp-buffer-size",
            "show_cursor": "--show-cursor",
        }

        # Keys handled specifically outside this generic loop
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
            flag = cli_key_map.get(k, f"--{k.replace('_', '-')}")
            if isinstance(v, bool):
                if k in ("gdi",):
                    if v:
                        args.append(flag)
                else:
                    args.extend([flag, "true" if v else "false"])
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
                    logger.info(
                        _("Using cached portal token from {}").format(TOKEN_FILE)
                    )
            except Exception:
                pass

        if client_host:
            args += ["--output", "rtp", "--host", client_host]
        else:
            args += ["--output", "webrtc"]

        kwargs = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "env": self._engine_env(),
        }
        if OS_TYPE == "windows":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        # Sanitize sensitive CLI arguments before logging
        sanitized_args = []
        skip_next = False
        for arg in args:
            if skip_next:
                sanitized_args.append("***REDACTED***")
                skip_next = False
            elif arg in ("--srtp-key", "--token"):
                sanitized_args.append(arg)
                skip_next = True
            else:
                sanitized_args.append(arg)

        logger.info(_("Starting mirror engine: {args}").format(args=sanitized_args))
        self.process = await asyncio.create_subprocess_exec(*args, **kwargs)

        async def log_engine(stream, prefix):
            ansi_regex = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
            key_regex = re.compile(r"(key=[\"'])[a-fA-F0-9]{20,}([\"'])", re.IGNORECASE)
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode(errors="ignore").strip()
                clean_text = ansi_regex.sub("", text)
                clean_text = key_regex.sub(r"\1***REDACTED***\2", clean_text)
                if clean_text:
                    logger.info(f"MIRROR_ENGINE [{prefix}]: {clean_text}")

        asyncio.create_task(log_engine(self.process.stdout, "OUT"))
        asyncio.create_task(log_engine(self.process.stderr, "ERR"))

        if await self._ensure_ipc():
            return True
        else:
            logger.error("Mirror engine IPC connection failed")
            try:
                diags = await self.collect_engine_diagnostics()
                logger.error("Engine diagnostics: %s", json.dumps(diags))
            except Exception as e:
                logger.error("Failed to collect engine diagnostics: %s", e)
            return False

    async def stop_engine(self):
        """Actually terminate the engine process to release the portal and system tray icon."""
        await self.kill_engine()

    async def kill_engine(self):
        """Terminate the underlying process, freeing OS portal sessions, active capture descriptors, and taskbar icons."""
        if self.process:
            try:
                if OS_TYPE == "windows":
                    try:
                        await asyncio.wait_for(
                            asyncio.to_thread(
                                subprocess.run,
                                ["taskkill", "/F", "/T", "/PID", str(self.process.pid)],
                                creationflags=subprocess.CREATE_NO_WINDOW,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                timeout=5,
                            ),
                            timeout=10.0,
                        )
                    except (subprocess.TimeoutExpired, asyncio.TimeoutError):
                        logger.warning(
                            _("taskkill timed out, attempting direct terminate")
                        )
                        try:
                            self.process.terminate()
                        except Exception:
                            pass
                else:
                    self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                logger.warning(_("Engine process did not exit within timeout"))
            except Exception as e:
                logger.warning(_("Error killing engine: {}").format(e))
            self.process = None
            logger.info(_("Mirror engine process terminated."))

        self.srtp_key = None
        if self.reader:
            self.reader.close()
        if self.writer:
            self.writer.close()
        self.reader = None
        self.writer = None
        if self.listen_task:
            self.listen_task.cancel()
            try:
                await self.listen_task
            except asyncio.CancelledError:
                pass
            self.listen_task = None

    def reset_portal_token(self) -> bool:
        """Remove the persistent capture token to force native system authorization dialogs during the next startup sequence."""
        try:
            if os.path.exists(TOKEN_FILE):
                os.remove(TOKEN_FILE)
                logger.info(f"Cached portal token {TOKEN_FILE} has been cleared")
                return True
        except Exception as e:
            logger.error(f"Failed to clear portal token file: {e}")
        return False

    async def send_command(self, cmd: dict):
        if not self.writer or self.writer.is_closing():
            logger.warning("IPC not connected, cannot send command")
            return
        self.writer.write(json.dumps(cmd).encode() + b"\n")
        await self.writer.drain()

    async def _listen_ipc(self):
        """Listen for IPC messages from the engine."""
        while True:
            if not self.reader:
                await asyncio.sleep(0.5)
                continue
            try:
                line = await self.reader.readline()
            except Exception as e:
                logger.warning(_("IPC read error: {}").format(e))
                self.reader = None
                self.writer = None
                break

            if not line:
                logger.warning(_("Mirror engine IPC closed"))
                self.reader = None
                self.writer = None
                break

            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                if msg.get("type") == "WAITING_FOR_PORTAL_APPROVAL":
                    logger.info(_("Engine is waiting for Wayland portal approval"))

                for sub in list(self._subscribers):
                    asyncio.create_task(self._safe_notify(sub, msg))
            except Exception as e:
                logger.error(_("Mirror IPC decode fail: {}").format(e))

    def subscribe(self, callback):
        self._subscribers.add(callback)

    async def _safe_notify(self, callback, msg):
        try:
            await callback(msg)
        except Exception:
            pass

    def unsubscribe(self, callback) -> int:
        self._subscribers.discard(callback)
        return len(self._subscribers)


desktop_streaming_service = DesktopStreamingService()
