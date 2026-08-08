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
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from fastapi import HTTPException

from ..core.constants import APP_DATA_PATH
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
    BUNDLED_PATH = STRUCTURED_PATH
else:
    BUNDLED_PATH = LEGACY_PATH

FERRUMCAST_DIR = APP_DATA_PATH / "ferrumcast"
VERSIONS_DIR = FERRUMCAST_DIR / "versions"
ACTIVE_CONFIG_FILE = FERRUMCAST_DIR / "active.json"


def get_active_engine_path() -> Path:
    """Resolve the active FerrumCast binary path using active.json or fallback to bundled."""
    if ACTIVE_CONFIG_FILE.exists():
        try:
            with open(ACTIVE_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                active_tag = data.get("active_version")
                if active_tag and active_tag != "bundled":
                    target_bin = VERSIONS_DIR / active_tag / BIN_NAME
                    if target_bin.exists():
                        return target_bin
        except Exception as e:
            logger.warning(f"Failed reading active FerrumCast config: {e}")

    if BUNDLED_PATH.exists():
        return BUNDLED_PATH

    sys_path = shutil.which(BIN_NAME)
    if sys_path:
        return Path(sys_path)

    return BUNDLED_PATH


ENGINE_PATH = get_active_engine_path()


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
        self._releases_cache = None
        self._releases_cache_time = 0
        self._version_cache = {}  # str(path) -> (mtime, version_string)

    def refresh_engine_path(self) -> Path:
        global ENGINE_PATH
        ENGINE_PATH = get_active_engine_path()
        return ENGINE_PATH

    async def get_binary_version(self, path: Path) -> str:
        """Query a binary's version via --version flag with in-memory caching."""
        if not path.exists():
            return "Unknown"

        try:
            mtime = path.stat().st_mtime
            path_key = str(path.resolve())
            if path_key in self._version_cache:
                cached_mtime, cached_ver = self._version_cache[path_key]
                if cached_mtime == mtime:
                    return cached_ver
        except Exception:
            pass

        try:
            proc = await asyncio.create_subprocess_exec(
                str(path),
                "--version",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW
                if platform.system() == "Windows"
                else 0,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=3.0)
            if proc.returncode == 0:
                out = stdout.decode().strip()
                parts = out.split()
                ver = parts[1] if len(parts) >= 2 else out
                try:
                    self._version_cache[str(path.resolve())] = (
                        path.stat().st_mtime,
                        ver,
                    )
                except Exception:
                    pass
                return ver
        except Exception:
            pass
        return "v0.1.0"

    async def get_installed_versions(self) -> list:
        """Return list of installed version objects (bundled + config versions)."""
        active_path = get_active_engine_path()
        versions = []

        bundled_exists = BUNDLED_PATH.exists()
        bundled_ver = (
            await self.get_binary_version(BUNDLED_PATH) if bundled_exists else "v0.1.0"
        )
        versions.append(
            {
                "tag": "bundled",
                "display_name": f"{bundled_ver} (Bundled)",
                "is_bundled": True,
                "is_active": (active_path == BUNDLED_PATH),
                "size_bytes": BUNDLED_PATH.stat().st_size if bundled_exists else 0,
                "path": str(BUNDLED_PATH),
            }
        )

        if VERSIONS_DIR.exists():
            for item in VERSIONS_DIR.iterdir():
                if item.is_dir():
                    bin_file = item / BIN_NAME
                    if bin_file.exists():
                        ver_str = await self.get_binary_version(bin_file)
                        info_file = item / "info.json"
                        tag_name = item.name
                        if info_file.exists():
                            try:
                                with open(info_file, "r", encoding="utf-8") as f:
                                    tag_name = json.load(f).get("tag_name", item.name)
                            except Exception:
                                pass
                        versions.append(
                            {
                                "tag": tag_name,
                                "display_name": f"{tag_name} ({ver_str})",
                                "is_bundled": False,
                                "is_active": (active_path == bin_file),
                                "size_bytes": bin_file.stat().st_size,
                                "path": str(bin_file),
                            }
                        )

        return versions

    def select_active_version(self, tag_name: str) -> dict:
        """Switch active version tag."""
        if self._engine_alive():
            raise HTTPException(
                status_code=400,
                detail="Cannot switch version while desktop streaming is active.",
            )

        FERRUMCAST_DIR.mkdir(parents=True, exist_ok=True)

        if tag_name == "bundled":
            target_data = {"active_version": "bundled"}
        else:
            target_bin = VERSIONS_DIR / tag_name / BIN_NAME
            if not target_bin.exists():
                raise HTTPException(
                    status_code=404, detail=f"Version '{tag_name}' is not installed."
                )
            target_data = {"active_version": tag_name}

        with open(ACTIVE_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(target_data, f, indent=2)

        new_path = self.refresh_engine_path()
        return {
            "success": True,
            "active_version": tag_name,
            "active_path": str(new_path),
        }

    def delete_version_cache(self, tag_name: str) -> dict:
        """Delete cached version folder."""
        if tag_name == "bundled":
            raise HTTPException(status_code=400, detail="Cannot delete bundled binary.")

        active_path = get_active_engine_path()
        target_dir = VERSIONS_DIR / tag_name
        target_bin = target_dir / BIN_NAME

        if active_path == target_bin:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete currently active version. Switch to another version first.",
            )

        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
            return {"success": True, "deleted": tag_name}

        raise HTTPException(
            status_code=404, detail=f"Version folder '{tag_name}' not found."
        )

    async def fetch_github_releases(self) -> list:
        """Fetch FerrumCast releases from GitHub API with 5min cache."""
        import time

        now = time.time()
        if self._releases_cache and (now - self._releases_cache_time < 300):
            return self._releases_cache

        url = "https://api.github.com/repos/BYTEDz/FerrumCast/releases"
        req = urllib.request.Request(url, headers={"User-Agent": "PCLink-Server"})
        loop = asyncio.get_running_loop()

        def _do_fetch():
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
            return []

        try:
            raw_releases = await loop.run_in_executor(None, _do_fetch)
            parsed = []
            for r in raw_releases:
                tag = r.get("tag_name")
                body = r.get("body", "")
                assets = r.get("assets", [])

                target_triple = (
                    "x86_64"
                    if ARCH_NAME in ["x86_64", "amd64"]
                    else ("aarch64" if ARCH_NAME in ["arm64", "aarch64"] else ARCH_NAME)
                )

                matching_asset = None
                # First pass: Exact match for OS + Architecture target string
                for a in assets:
                    name = a.get("name", "").lower()
                    if OS_TYPE in name and target_triple in name:
                        matching_asset = a.get("browser_download_url")
                        break

                # Second pass: OS match fallback
                if not matching_asset:
                    for a in assets:
                        name = a.get("name", "").lower()
                        if OS_TYPE in name or (
                            OS_TYPE == "windows" and name.endswith(".exe")
                        ):
                            matching_asset = a.get("browser_download_url")
                            break

                if not matching_asset and assets:
                    matching_asset = assets[0].get("browser_download_url")

                parsed.append(
                    {
                        "tag_name": tag,
                        "name": r.get("name") or tag,
                        "published_at": r.get("published_at"),
                        "body": body,
                        "download_url": matching_asset,
                        "prerelease": r.get("prerelease", False),
                    }
                )

            self._releases_cache = parsed
            self._releases_cache_time = now
            return parsed
        except Exception as e:
            logger.error(f"Failed fetching GitHub releases for FerrumCast: {e}")
            return self._releases_cache or []

    async def download_version(self, tag_name: str, download_url: str = None) -> dict:
        """Download a FerrumCast release into config version cache."""
        if self._engine_alive():
            raise HTTPException(
                status_code=400,
                detail="Cannot update binary while desktop streaming is active.",
            )

        if not download_url:
            releases = await self.fetch_github_releases()
            for r in releases:
                if r["tag_name"] == tag_name:
                    download_url = r.get("download_url")
                    break

        if not download_url:
            ext = ".exe" if OS_TYPE == "windows" else ""
            download_url = f"https://github.com/BYTEDz/FerrumCast/releases/download/{tag_name}/ferrumcast_{OS_TYPE}_{ARCH_NAME}{ext}"

        FERRUMCAST_DIR.mkdir(parents=True, exist_ok=True)
        VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
        target_dir = VERSIONS_DIR / tag_name
        target_dir.mkdir(parents=True, exist_ok=True)

        tmp_bin = target_dir / f"{BIN_NAME}.tmp"
        target_bin = target_dir / BIN_NAME

        loop = asyncio.get_running_loop()

        def _do_download():
            req = urllib.request.Request(
                download_url, headers={"User-Agent": "PCLink-Server"}
            )
            with urllib.request.urlopen(req, timeout=60) as response, open(
                tmp_bin, "wb"
            ) as out_file:
                shutil.copyfileobj(response, out_file)

        logger.info(f"Downloading FerrumCast {tag_name} from {download_url}...")
        try:
            await loop.run_in_executor(None, _do_download)
        except Exception as e:
            logger.error(f"Failed to download FerrumCast version {tag_name}: {e}")
            if tmp_bin.exists():
                tmp_bin.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail=f"Download failed: {e}")

        # Check if the downloaded file is a compressed archive (.zip, .tar.gz, .tgz)
        import tarfile
        import zipfile

        extracted_file = None
        if zipfile.is_zipfile(tmp_bin):
            logger.info(f"Extracting zip archive for {tag_name}...")
            with zipfile.ZipFile(tmp_bin, "r") as zip_ref:
                for member in zip_ref.namelist():
                    if member.endswith(BIN_NAME) or member == BIN_NAME:
                        zip_ref.extract(member, target_dir)
                        extracted_file = target_dir / member
                        break
        elif tarfile.is_tarfile(tmp_bin):
            logger.info(f"Extracting tar archive for {tag_name}...")
            with tarfile.open(tmp_bin, "r:*") as tar_ref:
                for member in tar_ref.getmembers():
                    if member.name.endswith(BIN_NAME) or member.name == BIN_NAME:
                        tar_ref.extract(member, target_dir)
                        extracted_file = target_dir / member.name
                        break

        if extracted_file and extracted_file.exists():
            if extracted_file != target_bin:
                shutil.move(str(extracted_file), str(target_bin))
            if tmp_bin.exists() and tmp_bin != target_bin:
                tmp_bin.unlink(missing_ok=True)
        else:
            # Not an archive or extracted directly
            os.replace(tmp_bin, target_bin)

        if OS_TYPE != "windows":
            os.chmod(target_bin, 0o755)

        tmp_ver = await self.get_binary_version(target_bin)
        logger.info(f"Downloaded binary version: {tmp_ver}")

        with open(target_dir / "info.json", "w", encoding="utf-8") as f:
            json.dump(
                {
                    "tag_name": tag_name,
                    "version_string": tmp_ver,
                    "download_url": download_url,
                },
                f,
                indent=2,
            )

        self.select_active_version(tag_name)

        return {
            "success": True,
            "tag": tag_name,
            "version": tmp_ver,
            "path": str(target_bin),
        }

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
