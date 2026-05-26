import asyncio
import json
import os
import subprocess
import logging
from pathlib import Path

import platform
import tempfile

from ..core.utils import resource_path

logger = logging.getLogger(__name__)

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

    def _engine_env(self) -> dict:
        """Prepare the environment for the FerrumCast engine process."""
        env = os.environ.copy()
        if OS_TYPE == "windows":
            # Attempt to locate and configure the standard MSVC GStreamer runtime directories
            # to establish plugin registries and bin paths before spawning the engine subprocess.
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
        import platform

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
                # Primary strategy: Check the process table for active portal contexts using pgrep.
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
                    # Secondary fallback: Query systemd user service status if direct process lookup fails.
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
        """Collect GStreamer and environment diagnostics useful for debugging engine failures.

        Returns a dict containing gst-inspect outputs and the environment as seen
        by the spawned engine process (PATH, GST_PLUGIN_PATH, GST_PLUGIN_SCANNER).
        """
        result = {
            "gst_inspect_version": None,
            "gst_inspect_plugins": None,
            "env": {},
            "errors": [],
        }

        # Replicate the exact environment configuration passed to the engine process
        # to guarantee diagnostic commands run under identical conditions.
        env = self._engine_env()

        # Extract relevant path and registry variables crucial for troubleshooting
        # dynamic library search paths and GStreamer plugin resolution.
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

        # Verify core GStreamer runtime installation and tool availability.
        code, out, err = await run_cmd("gst-inspect-1.0", "--version")
        if code == 0:
            result["gst_inspect_version"] = out.strip()
        else:
            result["errors"].append({"gst-inspect-version": err or out})

        # Inspect critical streaming and acceleration modules to verify support
        # for targeted encoders and capture pipelines.
        plugins_to_check = [
            "webrtcbin",
            "d3d11screencapturesrc",
            "x264enc",
            "mfh264enc",
            "gstpython",
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

        # Filter global registry list to avoid downstream logger buffer bloat
        # while preserving core media element traces.
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
            # Establish a connection to the Windows Named Pipe. Because standard synchronous file I/O
            # blocks the asyncio event loop, operations are delegated to a worker thread via asyncio.to_thread.
            for _ in range(300):
                try:
                    # Use timeout on pipe open to prevent indefinite blocking if the pipe exists
                    # but the engine is not ready to accept connections.
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

                        def write(self, data):
                            self._pipe.write(data)

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

    async def start_engine(
        self,
        client_host=None,
        encoder="auto",
        width=None,
        height=None,
        fps=None,
        bitrate=4000,
        audio=False,
        gdi=False,
        speed_preset="ultrafast",
        tune="zerolatency",
        nvenc_preset="p4",
        nvenc_tune="ultra-low-latency",
        vaapi_target_usage=1,
        qsv_target_usage=7,
        rc_mode="cbr",
        cqp_value=26,
        key_int_max=60,
        bframes=0,
        ref_frames=1,
        rtp_mtu=1200,
        queue_max_time_ns=0,
        queue_max_buffers=2,
        aggregate_mode="zero-latency",
        udp_buffer_size=2097152,
        show_cursor=True,
        colorimetry="bt709",
    ):
        """Start or reuse engine. If already running, restart pipeline via IPC."""
        if not ENGINE_PATH.exists():
            logger.error(f"Mirror engine not found at {ENGINE_PATH}")
            return False

        # If the engine process is already active, request an in-place pipeline reconfiguration
        # via IPC to bypass redundant screen authorization dialog prompts.
        if self._engine_alive() and await self._ensure_ipc():
            logger.info(
                f"Engine alive, restarting pipeline via IPC: host={client_host} encoder={encoder} res={width}x{height}@{fps}"
            )
            cfg = {
                "type": "RESTART_PIPELINE",
                "encoder": encoder,
                "bitrate": bitrate,
                "output_mode": "rtp" if client_host else "webrtc",
                "client_host": client_host or "127.0.0.1",
                "audio": audio,
                "width": width,
                "height": height,
                "framerate": fps,
                "token": None,
                "gdi": gdi,
                "speed_preset": speed_preset,
                "tune": tune,
                "nvenc_preset": nvenc_preset,
                "nvenc_tune": nvenc_tune,
                "vaapi_target_usage": vaapi_target_usage,
                "qsv_target_usage": qsv_target_usage,
                "rc_mode": rc_mode,
                "cqp_value": cqp_value,
                "key_int_max": key_int_max,
                "bframes": bframes,
                "ref_frames": ref_frames,
                "rtp_mtu": rtp_mtu,
                "queue_max_time_ns": queue_max_time_ns,
                "queue_max_buffers": queue_max_buffers,
                "aggregate_mode": aggregate_mode,
                "udp_buffer_size": udp_buffer_size,
                "show_cursor": show_cursor,
                "colorimetry": colorimetry,
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

        args = [
            str(ENGINE_PATH),
            "--encoder",
            encoder,
            "--bitrate",
            str(bitrate),
            "--audio",
            "true" if audio else "false",
            "--speed-preset",
            speed_preset,
            "--tune",
            tune,
            "--nvenc-preset",
            nvenc_preset,
            "--nvenc-tune",
            nvenc_tune,
            "--vaapi-target-usage",
            str(vaapi_target_usage),
            "--qsv-target-usage",
            str(qsv_target_usage),
            "--rc-mode",
            rc_mode,
            "--cqp-value",
            str(cqp_value),
            "--key-int-max",
            str(key_int_max),
            "--bframes",
            str(bframes),
            "--ref-frames",
            str(ref_frames),
            "--rtp-mtu",
            str(rtp_mtu),
            "--queue-max-time-ns",
            str(queue_max_time_ns),
            "--queue-max-buffers",
            str(queue_max_buffers),
            "--aggregate-mode",
            aggregate_mode,
            "--udp-buffer-size",
            str(udp_buffer_size),
            "--show-cursor",
            "true" if show_cursor else "false",
            "--colorimetry",
            colorimetry,
        ]
        if width:
            args += ["--width", str(width)]
        if height:
            args += ["--height", str(height)]
        if fps:
            args += ["--fps", str(fps)]
        if gdi:
            args.append("--gdi")

        if os.path.exists(TOKEN_FILE):
            try:
                token = Path(TOKEN_FILE).read_text().strip()
                if token:
                    # Supply the cached screen-capture authorization token to bypass user-facing prompts on startup.
                    args += ["--token", token]
                    logger.info(f"Using cached portal token from {TOKEN_FILE}")
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

        logger.info(f"Starting mirror engine: {args}")
        self.process = await asyncio.create_subprocess_exec(*args, **kwargs)

        async def log_engine(stream, prefix):
            while True:
                line = await stream.readline()
                if not line:
                    break
                logger.info(f"MIRROR_ENGINE [{prefix}]: {line.decode().strip()}")

        asyncio.create_task(log_engine(self.process.stdout, "OUT"))
        asyncio.create_task(log_engine(self.process.stderr, "ERR"))

        if await self._ensure_ipc():
            return True
        else:
            logger.error("Mirror engine IPC connection failed")
            # Execute system capability discovery to diagnose library linkage
            # or runtime pipeline initialization failures on startup crash.
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
                    # Use timeout on taskkill to prevent indefinite blocking if the process
                    # is in a zombie state. This prevents thread pool exhaustion.
                    try:
                        await asyncio.wait_for(
                            asyncio.to_thread(
                                subprocess.run,
                                ["taskkill", "/F", "/T", "/PID", str(self.process.pid)],
                                creationflags=subprocess.CREATE_NO_WINDOW,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                timeout=5,  # Add timeout to subprocess.run itself
                            ),
                            timeout=10.0,  # Outer timeout as safety net
                        )
                    except (subprocess.TimeoutExpired, asyncio.TimeoutError):
                        logger.warning(
                            "taskkill timed out, attempting direct terminate"
                        )
                        try:
                            self.process.terminate()
                        except Exception:
                            pass
                else:
                    self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                logger.warning("Engine process did not exit within timeout")
            except Exception as e:
                logger.warning(f"Error killing engine: {e}")
            self.process = None
        # Clear IPC state to unblock any pending reads
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
        logger.info("Mirror engine killed")

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
        """Listen for IPC messages from the engine with timeout protection.

        On Windows, the underlying pipe.readline() is a blocking synchronous call
        delegated to a thread pool. If the engine process is killed without properly
        closing the pipe, the readline can block indefinitely, exhausting thread pool
        workers and freezing the server. We use asyncio.wait_for() with a timeout to
        prevent this.
        """
        while True:
            if not self.reader:
                await asyncio.sleep(0.5)
                continue
            try:
                # Use a timeout to prevent indefinite blocking on Windows named pipes.
                # If the engine is killed, the pipe may not close cleanly, leaving
                # the blocking readline() in the thread pool stuck forever.
                line = await asyncio.wait_for(self.reader.readline(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("IPC readline timeout - engine may be unresponsive")
                # Check if the engine process is still alive
                if self.process and self.process.returncode is not None:
                    logger.info("Engine process has exited, closing IPC")
                    self.reader = None
                    self.writer = None
                    break
                # If still alive, continue waiting (timeout will recur)
                continue
            except Exception as e:
                logger.warning(f"IPC read error: {e}")
                self.reader = None
                self.writer = None
                break

            if not line:
                logger.warning("Mirror engine IPC closed")
                self.reader = None
                self.writer = None
                break

            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                # relay portal approval status to frontend subscribers
                if msg.get("type") == "WAITING_FOR_PORTAL_APPROVAL":
                    logger.info("Engine is waiting for Wayland portal approval")

                for sub in list(self._subscribers):
                    # Call subscribers as background tasks to prevent a slow client
                    # (e.g. app in background) from blocking the IPC listener loop.
                    asyncio.create_task(self._safe_notify(sub, msg))
            except Exception as e:
                logger.error(f"Mirror IPC decode fail: {e}")

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
