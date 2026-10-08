# src/pclink/services/tunnel_service.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import gettext
import logging
import platform
import shutil
import socket
import subprocess
import tarfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from ..core import constants
from ..core.config import config_manager

log = logging.getLogger(__name__)
_ = gettext.gettext

TUNNEL_ENGINE_URLS = {
    (
        "windows",
        "x86_64",
    ): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
    (
        "windows",
        "arm64",
    ): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-arm64.exe",
    (
        "linux",
        "x86_64",
    ): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
    (
        "linux",
        "arm64",
    ): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64",
    (
        "darwin",
        "x86_64",
    ): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz",
    (
        "darwin",
        "arm64",
    ): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-arm64.tgz",
}


class TunnelService:
    """Automates Remote Access tunnel provisioning, active health monitoring, and lifecycle recovery."""

    def __init__(self):
        self._process: Optional[subprocess.Popen] = None
        self._active_hostname: Optional[str] = None
        self._consecutive_spawn_failures: int = 0
        self._last_spawn_time: float = 0.0
        self._is_revoked: bool = False
        self._tunnel_status: str = "idle"
        self._last_error: Optional[str] = None
        self._stderr_thread: Optional[threading.Thread] = None

        self._bin_dir: Path = constants.APP_DATA_PATH / "bin"
        self._bin_dir.mkdir(parents=True, exist_ok=True)
        self._bin_path: Path = self._bin_dir / (
            "tunnel-engine.exe"
            if platform.system().lower() == "windows"
            else "tunnel-engine"
        )
        self.setup_progress: Dict[str, Any] = {
            "status": "idle",
            "progress": 0,
            "stage": "",
            "downloaded_bytes": 0,
            "total_bytes": 0,
            "error": None,
        }

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def get_status(self) -> Dict[str, Any]:
        return {
            "running": self.is_running(),
            "hostname": self._active_hostname
            or config_manager.get("remote_access_url", "").replace("https://", ""),
            "tunnel_status": self._tunnel_status,
            "is_revoked": self._is_revoked,
            "last_error": self._last_error,
            "binary_present": self._bin_path.exists()
            or bool(shutil.which("cloudflared") or shutil.which("tunnel-engine")),
            "setup_progress": self.setup_progress,
        }

    def _get_target_triple(self) -> tuple[str, str]:
        os_name = platform.system().lower()
        arch = platform.machine().lower()
        if arch in ("amd64", "x86_64"):
            arch = "x86_64"
        elif arch in ("aarch64", "arm64"):
            arch = "arm64"
        return os_name, arch

    def _broadcast_setup_progress(self) -> None:
        try:
            from ..api_server.ws_manager import ui_manager

            msg = {
                "type": "TUNNEL_SETUP_PROGRESS",
                "data": self.setup_progress,
            }
            ui_manager.broadcast_threadsafe(msg)
        except Exception:
            pass

    def _check_general_internet(self, timeout: float = 3.0) -> bool:
        """Verifies if the host machine has active internet connectivity by probing public Anycast DNS."""
        for target in [("1.1.1.1", 53), ("8.8.8.8", 53)]:
            try:
                socket.create_connection(target, timeout=timeout).close()
                return True
            except OSError:
                continue
        return False

    def _monitor_stderr(self, proc: subprocess.Popen, spawn_time: float) -> None:
        """
        Background worker that continuously drains stderr to prevent pipe deadlocks,
        tracks connection status, and logs diagnostic messages safely without
        triggering false-positive unlinks.
        """
        try:
            if not proc.stderr:
                return

            for raw_line in iter(proc.stderr.readline, b""):
                if not raw_line:
                    break

                line = raw_line.decode("utf-8", errors="replace").strip()
                line_lower = line.lower()

                # Connection confirmed active by daemon
                if (
                    "registered tunnel connection" in line_lower
                    or "connection registered" in line_lower
                ):
                    self._tunnel_status = "active"
                    self._consecutive_spawn_failures = 0
                    self._is_revoked = False
                    self._last_error = None
                    try:
                        from ..api_server.ws_manager import ui_manager

                        msg = {
                            "type": "TUNNEL_STATE_CHANGED",
                            "status": "active",
                            "hostname": self._active_hostname,
                        }
                        ui_manager.broadcast_threadsafe(msg)
                    except Exception:
                        pass
                elif "err " in line_lower or "wrn " in line_lower:
                    self._last_error = line
                    log.debug(f"[TunnelService] Engine log: {line}")
        except Exception as e:
            log.debug(f"[TunnelService] Stderr reader terminated: {e}")

    def prewarm_binary_background(self) -> None:
        """Asynchronously pre-fetches the tunnel binary at server startup without blocking."""

        def _worker():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self.ensure_binary())
                loop.close()
            except Exception as e:
                log.debug(f"Tunnel binary prewarm skipped: {e}")

        threading.Thread(
            target=_worker, daemon=True, name="pclink-tunnel-prewarm"
        ).start()

    async def ensure_binary(self) -> bool:
        """Resolves system binary or downloads platform-specific executable with live progress tracking."""
        for candidate in ("tunnel-engine", "cloudflared"):
            system_bin = shutil.which(candidate)
            if system_bin:
                self._bin_path = Path(system_bin)
                return True

        if self._bin_path.exists() and self._bin_path.stat().st_size > 0:
            return True

        triple = self._get_target_triple()
        download_url = TUNNEL_ENGINE_URLS.get(triple)
        if not download_url:
            log.error(
                _("No automated tunnel binary build available for {os}/{arch}").format(
                    os=triple[0], arch=triple[1]
                )
            )
            self.setup_progress = {
                "status": "failed",
                "progress": 0,
                "stage": _("No build available for this platform"),
                "error": "UNSUPPORTED_PLATFORM",
            }
            self._broadcast_setup_progress()
            return False

        log.info(
            _("Downloading tunnel engine executable from {url}...").format(
                url=download_url
            )
        )
        temp_file = self._bin_path.with_suffix(".tmp")

        self.setup_progress = {
            "status": "downloading",
            "progress": 0,
            "stage": _("Downloading Secure Tunnel Engine..."),
            "downloaded_bytes": 0,
            "total_bytes": 0,
            "error": None,
        }
        self._broadcast_setup_progress()

        def _download():
            req = urllib.request.Request(
                download_url, headers={"User-Agent": "PCLink-Server"}
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                content_len = resp.headers.get("content-length")
                total_bytes = int(content_len) if content_len else 0
                downloaded = 0
                last_reported_pct = 0

                with open(temp_file, "wb") as f:
                    while True:
                        chunk = resp.read(32768)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)

                        pct = (
                            int((downloaded / total_bytes) * 90)
                            if total_bytes > 0
                            else 50
                        )
                        if pct > last_reported_pct + 4:
                            last_reported_pct = pct
                            self.setup_progress = {
                                "status": "downloading",
                                "progress": min(pct, 90),
                                "stage": _("Downloading Secure Tunnel Engine..."),
                                "downloaded_bytes": downloaded,
                                "total_bytes": total_bytes,
                                "error": None,
                            }
                            self._broadcast_setup_progress()

            if download_url.endswith(".tgz"):
                self.setup_progress["stage"] = _("Extracting archive...")
                self.setup_progress["progress"] = 94
                self._broadcast_setup_progress()

                with tarfile.open(temp_file, "r:gz") as tar:
                    for member in tar.getmembers():
                        if member.name.endswith("cloudflared") or member.name.endswith(
                            "tunnel-engine"
                        ):
                            extracted = tar.extractfile(member)
                            if extracted:
                                with open(self._bin_path, "wb") as out:
                                    shutil.copyfileobj(extracted, out)
                                break
                temp_file.unlink(missing_ok=True)
            else:
                temp_file.replace(self._bin_path)

        try:
            await asyncio.to_thread(_download)
            if platform.system().lower() != "windows":
                self._bin_path.chmod(0o755)

            log.info(
                _("Tunnel engine binary ready at {path}").format(path=self._bin_path)
            )

            self.setup_progress = {
                "status": "ready",
                "progress": 100,
                "stage": _("Engine Ready"),
                "downloaded_bytes": self._bin_path.stat().st_size,
                "total_bytes": self._bin_path.stat().st_size,
                "error": None,
            }
            self._broadcast_setup_progress()
            return True
        except Exception as e:
            log.error(_("Failed to download tunnel engine: {error}").format(error=e))
            temp_file.unlink(missing_ok=True)
            self.setup_progress = {
                "status": "failed",
                "progress": 0,
                "stage": _("Download Failed"),
                "error": str(e),
            }
            self._broadcast_setup_progress()
            return False

    def spawn_tunnel(self, token: str, hostname: str) -> bool:
        """Executes the tunnel daemon with live stderr stream inspection."""
        if self.is_running():
            self.stop()

        self._active_hostname = hostname
        self._consecutive_spawn_failures = 0
        self._last_spawn_time = time.time()
        self._is_revoked = False
        self._tunnel_status = "connecting"
        self._last_error = None

        cmd = [
            str(self._bin_path),
            "tunnel",
            "run",
            "--token",
            token,
        ]

        kwargs: Dict[str, Any] = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.PIPE,
        }
        if platform.system().lower() == "windows":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True

        try:
            self._process = subprocess.Popen(cmd, **kwargs)

            # Start background thread to drain stderr safely and prevent OS pipe deadlocks
            self._stderr_thread = threading.Thread(
                target=self._monitor_stderr,
                args=(self._process, self._last_spawn_time),
                daemon=True,
                name="pclink-tunnel-stderr",
            )
            self._stderr_thread.start()

            log.info(
                _("Remote Access tunnel spawned for https://{hostname}").format(
                    hostname=self._active_hostname
                )
            )
            return True
        except Exception as e:
            log.error(f"Failed to spawn tunnel process: {e}")
            self._process = None
            self._tunnel_status = "failed"
            self._last_error = str(e)
            return False

    async def activate_with_token(self, token: str, hostname: str) -> bool:
        """Activates tunnel using credentials received from mobile handshake."""
        if not token or not hostname:
            log.error(_("Tunnel token and hostname cannot be empty"))
            return False

        clean_hostname = hostname.replace("https://", "").rstrip("/")
        config_manager.set("remote_access_token", token)
        config_manager.set("remote_access_url", f"https://{clean_hostname}")
        config_manager.set("enable_remote_access", True)

        self._consecutive_spawn_failures = 0
        self._is_revoked = False

        if not await self.ensure_binary():
            log.error(_("Tunnel binary could not be resolved or downloaded"))
            return False

        return self.spawn_tunnel(token, clean_hostname)

    async def resume_stored_tunnel(self) -> bool:
        """Resumes persisted tunnel token on startup."""
        token = config_manager.get("remote_access_token")
        url = config_manager.get("remote_access_url", "")
        if not token or not url:
            self._tunnel_status = "idle"
            return False

        if not await self.ensure_binary():
            return False

        hostname = url.replace("https://", "").rstrip("/")
        return self.spawn_tunnel(token, hostname)

    def unlink_credentials(self, reason: str = "Unlinked"):
        """
        Explicitly stops the tunnel and purges remote access credentials from local config.
        Only called upon explicit user request or confirmed cloud decommission.
        """
        self.stop()
        config_manager.set("remote_access_token", "")
        config_manager.set("remote_access_url", "")
        self._active_hostname = None
        self._tunnel_status = "idle"
        self._is_revoked = False
        log.warning(f"Remote Access credentials cleared: {reason}")

        try:
            from ..api_server.ws_manager import mobile_manager, ui_manager

            update_msg = {
                "type": "UPDATE_STATE",
                "relay_url": "",
                "remote_access_url": "",
            }
            mobile_manager.broadcast_threadsafe(update_msg)
            ui_manager.broadcast_threadsafe(update_msg)
        except Exception:
            pass

    async def check_and_heal(self) -> None:
        """
        Active Watchdog Supervisor:
        Supervises the tunnel process and restarts it if killed or if system wakes from sleep.
        Never erases credentials automatically.
        """
        if not config_manager.get("enable_remote_access", True):
            return

        token = config_manager.get("remote_access_token", "")
        url = config_manager.get("remote_access_url", "")
        if not token or not url:
            return

        # Process termination check: verify process is running
        if self._process is None or self._process.poll() is not None:
            now = time.time()
            alive_duration = now - self._last_spawn_time

            # Back off if rapid crash loop
            if alive_duration < 5.0:
                self._consecutive_spawn_failures += 1
                log.warning(
                    f"Remote Access tunnel process exited rapidly ({alive_duration:.1f}s, "
                    f"failure count: {self._consecutive_spawn_failures}/5)."
                )
                if self._consecutive_spawn_failures >= 5:
                    log.error(
                        "Repeated tunnel process spawn failures. Pausing watchdog recovery for 30s."
                    )
                    await asyncio.sleep(30.0)
                    self._consecutive_spawn_failures = 0
                else:
                    await asyncio.sleep(2.0)
            else:
                self._consecutive_spawn_failures = 0

            log.info(_("Restoring Remote Access tunnel process..."))
            await self.resume_stored_tunnel()
            return

        self._consecutive_spawn_failures = 0

    async def start(self) -> bool:
        if self.is_running():
            return True
        return await self.resume_stored_tunnel()

    def stop(self):
        """Terminates active tunnel process cleanly without wiping stored credentials."""
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=2.0)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None

        self._consecutive_spawn_failures = 0
        self._tunnel_status = "idle"
        log.info(_("Remote Access tunnel disconnected."))


tunnel_service = TunnelService()
