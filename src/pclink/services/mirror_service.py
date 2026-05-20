import asyncio
import json
import os
import subprocess
import logging
from pathlib import Path

import platform
import tempfile

logger = logging.getLogger(__name__)

# 1. Platform & CPU Architecture Detection
OS_TYPE = platform.system().lower()  # "linux", "windows", "darwin"
ARCH_RAW = platform.machine().lower()  # "x86_64", "amd64", "arm64", "aarch64"

# Standardize CPU architectures
if ARCH_RAW in ["amd64", "x86_64"]:
    ARCH_NAME = "x86_64"
elif ARCH_RAW in ["aarch64", "arm64"]:
    ARCH_NAME = "arm64"
else:
    ARCH_NAME = ARCH_RAW

# 2. OS-Specific Binary Name and Control Socket Paths
if OS_TYPE == "windows":
    BIN_NAME = "ferrumcast.exe"
    IPC_PATH = r"\\.\pipe\ferrumcast"
    TOKEN_FILE = str(Path(tempfile.gettempdir()) / "ferrumcast.token")
else:
    BIN_NAME = "ferrumcast"
    IPC_PATH = "/tmp/ferrumcast.sock"
    TOKEN_FILE = "/tmp/ferrumcast.token"

# 3. Dynamic Structured Directory Path Resolution (Fallback Supported)
STRUCTURED_PATH = (
    Path(__file__).parent.parent
    / "assets"
    / "bin"
    / f"{OS_TYPE}_{ARCH_NAME}"
    / BIN_NAME
)
LEGACY_PATH = Path(__file__).parent.parent / "assets" / "bin" / BIN_NAME

if STRUCTURED_PATH.exists():
    ENGINE_PATH = STRUCTURED_PATH
else:
    ENGINE_PATH = LEGACY_PATH


class MirrorService:
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
            # Prefer the installed MSVC GStreamer runtime if available.
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
                        if "GST_PLUGIN_PATH" not in env or plugin_path not in env["GST_PLUGIN_PATH"]:
                            env["GST_PLUGIN_PATH"] = plugin_path
                        if "GST_PLUGIN_SYSTEM_PATH" not in env or plugin_path not in env["GST_PLUGIN_SYSTEM_PATH"]:
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

        # 1. Check display server
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

            # Check Pipewire
            pipewire_running = False
            try:
                pw_socket = Path(f"/run/user/{os.getuid()}/pipewire-0")
                if pw_socket.exists() or shutil.which("pipewire") is not None:
                    pipewire_running = True
            except Exception:
                pass
            info["pipewire"] = "running" if pipewire_running else "not_detected"

            # Check XDG Desktop Portal
            portal_running = False
            try:
                # Strategy 1: Check pgrep -f (full CLI match) to find portal process
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
                    # Strategy 2: Check systemd user services
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

        # 2. Check GStreamer hardware encoders
        if info["binary_exists"]:
            try:
                proc = await asyncio.create_subprocess_exec(
                    str(ENGINE_PATH),
                    "--probe",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=self._engine_env(),
                    creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0,
                )
                try:
                    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
                except asyncio.TimeoutError:
                    proc.kill()
                    info["probe_error"] = "Probe timeout (10s) - GStreamer initialization may be failing"
                    info["status"] = "binary_failure"
                    logger.error("FerrumCast probe timed out after 10 seconds")
                    return info
                if proc.returncode == 0:
                    lines = stdout.decode().strip().split("\n")
                    if lines:
                        caps = json.loads(lines[-1])
                        info["encoders"] = caps.get("encoders", [])
                else:
                    error_text = stderr.decode(errors="ignore").strip() or stdout.decode(errors="ignore").strip()
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

        # 3. Determine overall support status
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

        # Prepare env same as engine will see
        env = self._engine_env()

        # Capture a minimal set of env variables for debugging
        for key in ("PATH", "GST_PLUGIN_PATH", "GST_PLUGIN_SYSTEM_PATH", "GST_PLUGIN_SCANNER"):
            result["env"][key] = env.get(key)

        async def run_cmd(*cmd):
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
                )
                stdout, stderr = await proc.communicate()
                return proc.returncode, stdout.decode(errors="ignore"), stderr.decode(errors="ignore")
            except FileNotFoundError as e:
                return 127, "", str(e)
            except Exception as e:
                return 1, "", str(e)

        # 1) gst-inspect version
        code, out, err = await run_cmd("gst-inspect-1.0", "--version")
        if code == 0:
            result["gst_inspect_version"] = out.strip()
        else:
            result["errors"].append({"gst-inspect-version": err or out})

        # 2) inspect specific plugins useful for troubleshooting
        plugins_to_check = ["webrtcbin", "d3d11screencapturesrc", "x264enc", "mfh264enc", "gstpython"]
        plugin_outputs = {}
        for p in plugins_to_check:
            code, out, err = await run_cmd("gst-inspect-1.0", p)
            plugin_outputs[p] = {"returncode": code, "stdout": out.strip(), "stderr": err.strip()}

        result["gst_inspect_plugins"] = plugin_outputs

        # 3) list plugins (grep for relevant ones)
        code, out, err = await run_cmd("gst-inspect-1.0", "--plugins")
        if code == 0:
            # Keep only relevant lines to avoid huge blobs in logs
            lines = [l for l in out.splitlines() if any(k in l for k in ("webrtcbin", "d3d11screencapturesrc", "x264enc", "mfh264enc", "gstpython"))]
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
            # Natively connect to Windows Named Pipe using standard file I/O wrapped in thread pool
            for _ in range(300):  # 30s timeout
                try:
                    pipe = open(IPC_PATH, "r+b", buffering=0)
                    logger.info("Mirror engine IPC connected (Windows Named Pipe)")

                    class PipeReader:
                        async def readline(self):
                            return await asyncio.to_thread(pipe.readline)

                    class PipeWriter:
                        def write(self, data):
                            pipe.write(data)

                        async def drain(self):
                            await asyncio.to_thread(pipe.flush)

                        def is_closing(self):
                            return False

                    self.reader = PipeReader()
                    self.writer = PipeWriter()

                    if not self.listen_task or self.listen_task.done():
                        self.listen_task = asyncio.create_task(self._listen_ipc())
                    return True
                except Exception:
                    pass
                await asyncio.sleep(0.1)
        else:
            # Unix Domain Sockets for Linux/macOS
            for _ in range(300):  # 30s timeout
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
        audio=True,
        gdi=False,
    ):
        """Start or reuse engine. If already running, restart pipeline via IPC."""
        if not ENGINE_PATH.exists():
            logger.error(f"Mirror engine not found at {ENGINE_PATH}")
            return False

        # If engine already running → restart pipeline via IPC (no portal dialog)
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
            }
            await self.send_command(cfg)
            return True

        # Engine not running → spawn new process
        if self.process:
            try:
                self.process.terminate()
                await self.process.wait()
            except Exception:
                pass
        self.reader = None
        self.writer = None

        # Clean stale socket
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
        ]
        if width:
            args += ["--width", str(width)]
        if height:
            args += ["--height", str(height)]
        if fps:
            args += ["--fps", str(fps)]
        if gdi:
            args.append("--gdi")

        # Pass cached portal token if available
        if os.path.exists(TOKEN_FILE):
            try:
                token = Path(TOKEN_FILE).read_text().strip()
                if token:
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
        self.process = await asyncio.create_subprocess_exec(
            *args,
            **kwargs
        )

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
            # Collect diagnostics to aid debugging of plugin/DLL issues
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
        """Actually terminate the engine process."""
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
        self.reader = None
        self.writer = None
        if self.listen_task:
            self.listen_task.cancel()
            self.listen_task = None
        logger.info("Mirror engine killed")

    def reset_portal_token(self) -> bool:
        """Reset/Clear cached XDG screen share portal token to force system prompts on next launch."""
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
        while True:
            if not self.reader:
                await asyncio.sleep(0.5)
                continue
            line = await self.reader.readline()
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
                for sub in list(self._subscribers):
                    try:
                        await sub(msg)
                    except Exception:
                        pass
            except Exception as e:
                logger.error(f"Mirror IPC decode fail: {e}")

    def subscribe(self, callback):
        self._subscribers.add(callback)

    def unsubscribe(self, callback):
        self._subscribers.discard(callback)


mirror_service = MirrorService()
