# src/pclink/core/extension_manager.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import gettext
import importlib.util
import inspect
import logging
import multiprocessing
import os
import platform as py_platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Type

import psutil
import yaml

from pclink.core.extension_base import (
    ExtensionBase,
    ExtensionMetadata,
    StaticExtension,
)
from pclink.core.extension_context import ExtensionContext
from pclink.core.extension_runner import run_extension_process
from pclink.core.version import __version__ as PCLINK_VERSION

log = logging.getLogger(__name__)
_ = gettext.gettext


# --- Security Configuration ---
DANGEROUS_PERMISSIONS = {
    "system.exec",
    "filesystem.read",
    "filesystem.write",
    "input.inject",
    "input.monitor",
}

# Safe Mode: Maximum consecutive crashes before disabling extensions
SAFE_MODE_CRASH_THRESHOLD = 2


class ExtensionManager:
    _instance = None
    _import_lock = threading.Lock()  # Prevents sys.path race conditions

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ExtensionManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "initialized"):
            from ..core import constants

            self.extensions_path = constants.APP_DATA_PATH / "extensions"
            self.extensions_path.mkdir(parents=True, exist_ok=True)
            self.extensions: Dict[str, ExtensionBase] = {}
            self.isolated_processes: Dict[str, Dict[str, Any]] = {}
            self._pending_http_requests: Dict[str, Any] = {}
            self._app = None  # Reference to FastAPI app for dynamic routing
            self._mounted_extensions: Set[str] = set()
            self.logs: Dict[str, List[str]] = {}
            self.initialized = True
            self.safe_mode = False

            # Cache hardware and OS info once per lifecycle
            self._init_system_info()

            # Registry of extensions that failed to load
            self.failed_extensions: Dict[str, float] = {}
            self.LOAD_RETRY_COOLDOWN = 60.0  # seconds

            # Safe Mode crash tracking
            self._crash_file = constants.APP_DATA_PATH / ".extension_crashes"
            self._check_safe_mode()

            # Metadata Cache: eid -> (last_mtime, manifest_dict)
            self._metadata_cache: Dict[str, tuple[float, Dict]] = {}

            # Runtime failure tracking: eid -> count
            self._runtime_failures: Dict[str, int] = {}

            # Ensure 'pclink.extensions' exists as a dummy package
            if "pclink.extensions" not in sys.modules:
                from types import ModuleType

                m = ModuleType("pclink.extensions")
                m.__path__ = []
                sys.modules["pclink.extensions"] = m

            # Venv base path - each extension gets its own venv
            self._venvs_base = constants.APP_DATA_PATH / "venvs"
            self._venvs_base.mkdir(parents=True, exist_ok=True)
            self.install_states: Dict[str, Dict[str, Any]] = {}

    @property
    def app(self):
        return self._app

    @app.setter
    def app(self, value):
        self._app = value
        if hasattr(self, "_mounted_extensions"):
            self._mounted_extensions.clear()
        if value:
            log.info(
                "New FastAPI app assigned to ExtensionManager. Dynamic Mounting Cache cleared."
            )

    def _check_safe_mode(self):
        """Check if safe mode should be entered due to repeated crashes."""
        crash_count = 0
        if self._crash_file.exists():
            try:
                crash_count = int(self._crash_file.read_text().strip())
            except (ValueError, OSError):
                crash_count = 0

        if crash_count >= SAFE_MODE_CRASH_THRESHOLD:
            log.warning(
                "⚠️ SAFE MODE: Extensions disabled due to repeated startup crashes."
            )
            log.warning("⚠️ To exit safe mode, manually delete: %s", self._crash_file)
            self.safe_mode = True
        else:
            self._crash_file.write_text(str(crash_count + 1))

    def _init_system_info(self):
        """Cache hardware and OS info once per lifecycle."""
        if hasattr(self, "_sys_info"):
            return

        current_arch = py_platform.machine().lower()
        arch_aliases = {
            "x86_64": ["x86_64", "amd64"],
            "amd64": ["x86_64", "amd64"],
            "aarch64": ["aarch64", "arm64"],
            "arm64": ["aarch64", "arm64"],
        }

        os_distro = "unknown"
        if py_platform.system().lower() == "linux":
            try:
                import distro

                os_distro = distro.id().lower()
            except ImportError:
                if os.path.exists("/etc/os-release"):
                    with open("/etc/os-release", "r") as f:
                        m = re.search(r'^ID=["\']?(.+?)["\']?$', f.read(), re.M)
                        if m:
                            os_distro = m.group(1).lower()

        self._sys_info = {
            "platform": py_platform.system().lower(),
            "arch_aliases": arch_aliases.get(current_arch, [current_arch]),
            "distro": os_distro,
        }

    def _is_compatible(self, metadata: ExtensionMetadata) -> bool:
        """Isolated check for platform compatibility."""
        sys_info = self._sys_info
        if sys_info["platform"] not in [
            p.lower() for p in metadata.supported_platforms
        ]:
            return False

        supported_archs = [a.lower() for a in metadata.supported_architectures]
        if not any(alias in supported_archs for alias in sys_info["arch_aliases"]):
            return False

        if sys_info["platform"] == "linux" and metadata.supported_distros:
            if sys_info["distro"] not in [
                d.lower() for d in metadata.supported_distros
            ]:
                return False

        return True

    def _update_install_state(
        self,
        extension_id: str,
        status: str,
        progress: int,
        error: Optional[str] = None,
        task_id: Optional[str] = None,
    ):
        state = {"status": status, "progress": progress, "error": error}
        if extension_id:
            self.install_states[extension_id] = state
        if task_id:
            self.install_states[task_id] = state

    def _create_venv(
        self, extension_id: str, requirements_path: Path, task_id: Optional[str] = None
    ) -> Optional[Path]:
        """Creates a dedicated virtual environment for an extension."""
        venv_path = self._venvs_base / extension_id
        self._update_install_state(extension_id, "preparing", 10, task_id=task_id)

        if venv_path.exists():
            if (venv_path / "pyvenv.cfg").exists():
                log.debug(f"Venv already exists for {extension_id}, skipping creation")
                self._update_install_state(
                    extension_id, "completed", 100, task_id=task_id
                )
                return venv_path

        log.info(f"Creating venv for extension: {extension_id}")
        self._update_install_state(extension_id, "creating_venv", 25, task_id=task_id)

        try:
            result = subprocess.run(
                [sys.executable, "-m", "venv", str(venv_path)],
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode != 0:
                log.error(f"Failed to create venv for {extension_id}: {result.stderr}")
                self._update_install_state(
                    extension_id,
                    "failed",
                    0,
                    f"Venv creation failed: {result.stderr}",
                    task_id=task_id,
                )
                return None

            if sys.platform == "win32":
                pip_path = venv_path / "Scripts" / "pip.exe"
                python_path = venv_path / "Scripts" / "python.exe"
            else:
                pip_path = venv_path / "bin" / "pip"
                python_path = venv_path / "bin" / "python"

            if not pip_path.exists():
                log.error(f"Pip not found at {pip_path}")
                self._update_install_state(
                    extension_id,
                    "failed",
                    0,
                    "Pip executable not found in venv",
                    task_id=task_id,
                )
                return None

            self._update_install_state(
                extension_id, "upgrading_pip", 45, task_id=task_id
            )

            result = subprocess.run(
                [str(python_path), "-m", "pip", "install", "--upgrade", "pip"],
                capture_output=True,
                text=True,
                timeout=180,
            )

            if result.returncode != 0:
                log.warning(
                    f"Failed to upgrade pip for {extension_id}: {result.stderr}"
                )

            self._update_install_state(
                extension_id, "installing_requirements", 60, task_id=task_id
            )

            proc = subprocess.Popen(
                [str(pip_path), "install", "-r", str(requirements_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            while True:
                line = proc.stdout.readline()
                if not line:
                    break
                log.debug(f"[{extension_id} pip]: {line.strip()}")
                if "Downloading" in line:
                    self._update_install_state(
                        extension_id, "installing_requirements", 75, task_id=task_id
                    )
                elif "Installing collected packages" in line:
                    self._update_install_state(
                        extension_id, "installing_requirements", 90, task_id=task_id
                    )

            proc.wait(timeout=300)

            if proc.returncode != 0:
                stderr_output = proc.stderr.read()
                log.error(
                    f"Failed to install requirements for {extension_id}: {stderr_output}"
                )
                self._update_install_state(
                    extension_id,
                    "failed",
                    0,
                    f"Pip install failed: {stderr_output}",
                    task_id=task_id,
                )
                return None

            self._update_install_state(extension_id, "completed", 100, task_id=task_id)
            log.info(
                f"Successfully created venv and installed requirements for {extension_id}"
            )
            return venv_path

        except subprocess.TimeoutExpired:
            log.error(f"Timeout creating venv for {extension_id}")
            self._update_install_state(
                extension_id, "failed", 0, "Process timed out", task_id=task_id
            )
            return None
        except Exception as e:
            log.error(f"Error creating venv for {extension_id}: {e}")
            self._update_install_state(
                extension_id, "failed", 0, str(e), task_id=task_id
            )
            return None

    def _get_venv_site_packages(self, venv_path: Path) -> Optional[Path]:
        """Returns the site-packages path for a given venv."""
        if sys.platform == "win32":
            return venv_path / "Lib" / "site-packages"
        else:
            result = subprocess.run(
                [
                    str(venv_path / "bin" / "python"),
                    "-c",
                    "import site; print(site.getsitepackages()[0])",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return Path(result.stdout.strip())
            return None

    def _cleanup_venv(self, extension_id: str) -> bool:
        """Removes the venv for an extension."""
        venv_path = self._venvs_base / extension_id
        if not venv_path.exists():
            return True

        try:
            shutil.rmtree(venv_path)
            log.info(f"Cleaned up venv for extension: {extension_id}")
            return True
        except Exception as e:
            log.error(f"Failed to cleanup venv for {extension_id}: {e}")
            return False

    def _run_coro(self, coro):
        """Helper to run async function in sync context."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)

        if loop.is_running():
            res, err = None, None

            def target():
                nonlocal res, err
                try:
                    res = asyncio.run(coro)
                except Exception as e:
                    err = e

            t = threading.Thread(target=target)
            t.start()
            t.join()
            if err:
                raise err
            return res
        return loop.run_until_complete(coro)

    def _import_module_safely(
        self, extension_id: str, entry_point: Path, lib_path: Path
    ):
        """Thread-safe dynamic module import."""
        lib_path_str = str(lib_path)
        with self._import_lock:
            added_to_path = False
            if lib_path.is_dir() and lib_path_str not in sys.path:
                sys.path.insert(0, lib_path_str)
                added_to_path = True

            try:
                module_name = f"pclink.extensions.{extension_id.replace('-', '_')}"
                spec = importlib.util.spec_from_file_location(module_name, entry_point)
                if not spec or not spec.loader:
                    return None
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                return module
            finally:
                if added_to_path:
                    sys.path.remove(lib_path_str)

    def mark_startup_success(self):
        """Called after successful server startup to clear crash counter."""
        if self._crash_file.exists():
            try:
                self._crash_file.unlink()
                log.debug("Startup successful, crash counter cleared.")
            except OSError:
                pass

    def get_manifest(self, extension_id: str) -> Optional[Dict]:
        """Reads extension manifest with smart in-memory caching."""
        manifest_path = self.extensions_path / extension_id / "extension.yaml"
        if not manifest_path.exists():
            return None

        try:
            mtime = os.path.getmtime(manifest_path)
            cached_mtime, cached_data = self._metadata_cache.get(
                extension_id, (0, None)
            )

            if mtime == cached_mtime and cached_data is not None:
                return cached_data

            with open(manifest_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            self._metadata_cache[extension_id] = (mtime, data)
            return data
        except Exception as e:
            log.error(f"Failed to read manifest for {extension_id}: {e}")
            return None

    def _is_safe_name(self, name: str) -> bool:
        """Security: Verify name is a simple alphanumeric/hyphen string."""
        return bool(re.match(r"^[a-z0-9\-]+$", name))

    def discover_extensions(self) -> List[str]:
        """Scans the extensions folder for valid extension directories."""
        if not self.extensions_path.exists():
            return []

        discovered = []
        for entry in self.extensions_path.iterdir():
            if entry.is_dir() and (entry / "extension.yaml").exists():
                discovered.append(entry.name)
        return discovered

    def get_extension_telemetry(self, extension_id: str) -> Dict[str, Any]:
        """Retrieves process telemetry (PID, CPU %, Memory MB) for an isolated extension process."""
        info = self.isolated_processes.get(extension_id)
        if not info:
            return {}

        pid = info.get("pid")
        if not pid:
            return {}

        try:
            proc = psutil.Process(pid)
            mem_mb = round(proc.memory_info().rss / (1024 * 1024), 1)
            cpu_pct = round(proc.cpu_percent(interval=None), 1)
            return {"pid": pid, "cpu_percent": cpu_pct, "memory_mb": mem_mb}
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return {"pid": pid, "cpu_percent": 0.0, "memory_mb": 0.0}

    def dispatch_event(self, event_name: str, data: Dict[str, Any]):
        """Dispatches an event hook asynchronously to all active isolated extension processes."""
        for extension_id, info in list(self.isolated_processes.items()):
            pipe = info.get("pipe")
            if pipe:
                try:
                    pipe.send(
                        {"type": "EVENT_DISPATCH", "event": event_name, "data": data}
                    )
                except Exception as e:
                    log.error(
                        f"Failed to dispatch event '{event_name}' to extension '{extension_id}': {e}"
                    )

    def dispatch_ipc_http_request(
        self,
        extension_id: str,
        method: str,
        subpath: str,
        body: Optional[Any] = None,
        timeout: float = 10.0,
    ) -> Optional[Dict[str, Any]]:
        """
        Forwards an HTTP request across IPC Pipe to the isolated extension worker process
        and waits for the HTTP response.
        """
        info = self.isolated_processes.get(extension_id)
        if not info:
            return None

        pipe = info.get("pipe")
        if not pipe:
            return None

        req_id = f"req-{uuid.uuid4().hex[:8]}"

        try:
            pipe.send(
                {
                    "type": "HTTP_REQUEST",
                    "req_id": req_id,
                    "method": method,
                    "subpath": subpath,
                    "body": body,
                }
            )

            start = time.time()
            while time.time() - start < timeout:
                if req_id in self._pending_http_requests:
                    return self._pending_http_requests.pop(req_id)
                time.sleep(0.01)

            log.error(f"IPC HTTP Request timed out for extension '{extension_id}'")
            return {"status_code": 504, "error": "Extension IPC timeout"}

        except Exception as e:
            log.error(f"IPC HTTP request dispatch failed for {extension_id}: {e}")
            return {"status_code": 500, "error": str(e)}

    def _handle_ipc_requests(
        self, extension_id: str, host_pipe, metadata: ExtensionMetadata
    ):
        """
        Listens on IPC pipe from child process and handles host context calls and HTTP responses.
        """
        temp_context = ExtensionContext(metadata, ipc_conn=host_pipe)

        while extension_id in self.isolated_processes:
            try:
                if not host_pipe.poll(0.5):
                    continue

                msg = host_pipe.recv()
                msg_type = msg.get("type")

                if msg_type == "HTTP_RESPONSE":
                    req_id = msg.get("req_id")
                    if req_id:
                        self._pending_http_requests[req_id] = msg

                elif msg_type == "CONTEXT_CALL":
                    api_name = msg.get("api")
                    method_name = msg.get("method")
                    kwargs = msg.get("kwargs", {})

                    try:
                        api_obj = getattr(temp_context, api_name, None)
                        if not api_obj:
                            raise AttributeError(f"API '{api_name}' not found")

                        method_func = getattr(api_obj, method_name, None)
                        if not method_func:
                            raise AttributeError(
                                f"Method '{method_name}' not found on {api_name}"
                            )

                        res = method_func(**kwargs)
                        host_pipe.send({"status": "success", "result": res})
                    except Exception as e:
                        log.error(
                            f"Error executing IPC context call for {extension_id}: {e}"
                        )
                        host_pipe.send({"status": "error", "error": str(e)})

            except (EOFError, BrokenPipeError, OSError):
                log.info(f"IPC pipe closed for extension: {extension_id}")
                break
            except Exception as e:
                log.error(f"IPC listener error for {extension_id}: {e}")
                break

    def _spawn_isolated_extension(
        self,
        extension_id: str,
        metadata: ExtensionMetadata,
        extension_dir: Path,
        manifest: Dict[str, Any],
        task_id: Optional[str] = None,
    ) -> bool:
        """Spawns extension inside an isolated, supervised worker process."""
        log.info(f"Spawning process-isolated extension: {extension_id}")
        host_pipe, child_pipe = multiprocessing.Pipe()

        proc = multiprocessing.Process(
            target=run_extension_process,
            args=(
                extension_id,
                str(extension_dir),
                metadata.model_dump()
                if hasattr(metadata, "model_dump")
                else metadata.dict(),
                manifest,
                child_pipe,
            ),
            name=f"pclink-ext-{extension_id}",
            daemon=True,
        )

        proc.start()

        ready_received = False
        start_time = time.time()

        while time.time() - start_time < 15.0:
            if host_pipe.poll(0.2):
                msg = host_pipe.recv()
                if msg.get("status") == "ready":
                    ready_received = True
                    break
                elif msg.get("status") in ("error", "crash"):
                    err = msg.get("error", "Process initialization crash")
                    log.error(f"Isolated extension '{extension_id}' failed: {err}")
                    proc.terminate()
                    proc.join(timeout=1.0)
                    self._update_install_state(
                        extension_id, "failed", 0, err, task_id=task_id
                    )
                    self.failed_extensions[extension_id] = time.time()
                    return False

            if not proc.is_alive():
                log.error(
                    f"Isolated extension process '{extension_id}' terminated unexpectedly (exitcode={proc.exitcode})."
                )
                self._update_install_state(
                    extension_id,
                    "failed",
                    0,
                    f"Process crashed with exitcode {proc.exitcode}",
                    task_id=task_id,
                )
                self.failed_extensions[extension_id] = time.time()
                return False

        if not ready_received:
            log.error(
                f"Isolated extension '{extension_id}' timed out during initialization."
            )
            proc.terminate()
            proc.join(timeout=1.0)
            self._update_install_state(
                extension_id, "failed", 0, "Initialization timeout", task_id=task_id
            )
            self.failed_extensions[extension_id] = time.time()
            return False

        self.isolated_processes[extension_id] = {
            "process": proc,
            "pipe": host_pipe,
            "pid": proc.pid,
            "started_at": time.time(),
            "metadata": metadata,
        }

        listener_thread = threading.Thread(
            target=self._handle_ipc_requests,
            args=(extension_id, host_pipe, metadata),
            name=f"ipc-listener-{extension_id}",
            daemon=True,
        )
        listener_thread.start()

        self._update_install_state(extension_id, "completed", 100, task_id=task_id)
        self.failed_extensions.pop(extension_id, None)
        log.info(
            f"Successfully spawned isolated extension: {metadata.display_name} (PID={proc.pid})"
        )
        return True

    def load_extension(
        self, extension_id: str, background: bool = False, task_id: Optional[str] = None
    ) -> bool:
        """Loads a specific extension by its directory name (extension_id)."""
        from ..core.config import config_manager

        if extension_id in self.extensions or extension_id in self.isolated_processes:
            if self.app and extension_id not in self._mounted_extensions:
                log.info(f"Dynamically mounting routes for extension: {extension_id}")
                ext = self.extensions.get(extension_id)
                if ext:
                    try:
                        self.app.include_router(
                            ext.get_routes(),
                            prefix=f"/extensions/{extension_id}",
                            tags=[f"extension-{extension_id}"],
                        )
                        self._mounted_extensions.add(extension_id)
                    except Exception as e:
                        log.error(f"Failed to mount router for {extension_id}: {e}")
            return True

        last_fail = self.failed_extensions.get(extension_id, 0)
        if time.time() - last_fail < self.LOAD_RETRY_COOLDOWN:
            log.debug(
                f"Skipping load attempt for '{extension_id}' (in cooldown after failure)"
            )
            return False

        if not config_manager.get("allow_extensions", False):
            log.warning(
                f"Attempted to load extension '{extension_id}' while extensions are globally disabled."
            )
            return False

        if background:
            self._update_install_state(extension_id, "pending", 0, task_id=task_id)

            def run_load():
                try:
                    self._load_extension_impl(extension_id, task_id=task_id)
                except Exception as e:
                    log.exception(f"Background load failed for {extension_id}: {e}")
                    self._update_install_state(
                        extension_id, "failed", 0, str(e), task_id=task_id
                    )

            threading.Thread(target=run_load, name=f"ext-loader-{extension_id}").start()
            return True

        return self._load_extension_impl(extension_id, task_id=task_id)

    def _load_extension_impl(
        self, extension_id: str, task_id: Optional[str] = None
    ) -> bool:
        log.info(f"Loading extension: {extension_id}")

        manifest = self.get_manifest(extension_id)
        if not manifest:
            return False

        try:
            metadata = ExtensionMetadata(**manifest)

            if not self._is_compatible(metadata):
                log.warning(
                    f"Extension '{extension_id}' is incompatible with this system. Skipping."
                )
                self.failed_extensions[extension_id] = time.time()
                return False

            extension_dir = self.extensions_path / extension_id

            # --- Pure JS/HTML/CSS Extension Handling ---
            if not metadata.entry_point:
                ui_entry = metadata.ui_entry or "index.html"
                ui_entry_path = extension_dir / ui_entry
                if metadata.ui_entry and not ui_entry_path.exists():
                    log.error(
                        _(
                            "UI entry point '{ui_entry}' not found for static extension '{extension_id}'"
                        ).format(ui_entry=ui_entry, extension_id=extension_id)
                    )
                    self.failed_extensions[extension_id] = time.time()
                    return False

                context = ExtensionContext(metadata)
                extension_instance = StaticExtension(
                    metadata=metadata,
                    extension_path=extension_dir,
                    config=manifest,
                    context=context,
                )
                self.extensions[extension_id] = extension_instance
                if self.app:
                    try:
                        self.app.include_router(
                            extension_instance.get_routes(),
                            prefix=f"/extensions/{extension_id}",
                            tags=[f"extension-{extension_id}"],
                        )
                        self._mounted_extensions.add(extension_id)
                    except Exception as e:
                        log.error(f"Failed to mount router for {extension_id}: {e}")

                log.info(
                    f"Successfully loaded static JS/HTML extension: {metadata.display_name} ({metadata.version})"
                )
                self._update_install_state(
                    extension_id, "completed", 100, task_id=task_id
                )
                self.failed_extensions.pop(extension_id, None)
                return True

            entry_point_path = extension_dir / metadata.entry_point
            lib_path = extension_dir / "lib"

            if not entry_point_path.exists():
                log.error(
                    f"Entry point {metadata.entry_point} not found for extension {extension_id}"
                )
                self.failed_extensions[extension_id] = time.time()
                return False

            # --- Isolated Process Mode Execution ---
            if metadata.isolated_process:
                return self._spawn_isolated_extension(
                    extension_id, metadata, extension_dir, manifest, task_id=task_id
                )

            # --- In-Process Mode Fallback ---
            venv_path: Optional[Path] = None
            added_venv_to_path = False
            site_packages = None

            if metadata.requirements_file:
                requirements_path = extension_dir / metadata.requirements_file
                if requirements_path.exists():
                    venv_path = self._create_venv(
                        extension_id, requirements_path, task_id=task_id
                    )
                    if venv_path:
                        site_packages = self._get_venv_site_packages(venv_path)
                        if (
                            site_packages
                            and site_packages.exists()
                            and str(site_packages) not in sys.path
                        ):
                            sys.path.insert(0, str(site_packages))
                            added_venv_to_path = True

            module = self._import_module_safely(
                extension_id, entry_point_path, lib_path
            )

            if not module:
                if added_venv_to_path and site_packages:
                    try:
                        sys.path.remove(str(site_packages))
                    except ValueError:
                        pass
                self._update_install_state(
                    extension_id,
                    "failed",
                    0,
                    "Failed to import safely",
                    task_id=task_id,
                )
                self.failed_extensions[extension_id] = time.time()
                return False

            extension_class: Optional[Type[ExtensionBase]] = getattr(
                module, "Extension", None
            )
            if not extension_class:
                if added_venv_to_path and site_packages:
                    try:
                        sys.path.remove(str(site_packages))
                    except ValueError:
                        pass
                log.error(f"No 'Extension' class found in {entry_point_path}")
                self._update_install_state(
                    extension_id,
                    "failed",
                    0,
                    "No Extension class found",
                    task_id=task_id,
                )
                self.failed_extensions[extension_id] = time.time()
                return False

            context = ExtensionContext(metadata)
            extension_instance = extension_class(
                metadata=metadata,
                extension_path=extension_dir,
                config=manifest,
                context=context,
            )

            if venv_path:
                extension_instance._venv_path = venv_path

            init_result = extension_instance.initialize()
            init_success = False

            if inspect.iscoroutinefunction(
                extension_instance.initialize
            ) or inspect.iscoroutine(init_result):
                try:
                    init_success = self._run_coro(init_result)
                except Exception as e:
                    log.error(f"Failed to run async initialize for {extension_id}: {e}")
                    init_success = False
            else:
                init_success = init_result

            if init_success:
                self.extensions[extension_id] = extension_instance
                if self.app:
                    try:
                        self.app.include_router(
                            extension_instance.get_routes(),
                            prefix=f"/extensions/{extension_id}",
                            tags=[f"extension-{extension_id}"],
                        )
                        self._mounted_extensions.add(extension_id)
                    except Exception as e:
                        log.error(f"Failed to mount router for {extension_id}: {e}")

                log.info(
                    f"Successfully loaded extension: {metadata.display_name} ({metadata.version})"
                )
                self._update_install_state(
                    extension_id, "completed", 100, task_id=task_id
                )
                self.failed_extensions.pop(extension_id, None)
                return True
            else:
                if added_venv_to_path and site_packages:
                    try:
                        sys.path.remove(str(site_packages))
                    except ValueError:
                        pass
                log.error(f"Extension '{extension_id}' initialize() returned False")
                self._update_install_state(
                    extension_id,
                    "failed",
                    0,
                    "Initialize returned False",
                    task_id=task_id,
                )
                self.failed_extensions[extension_id] = time.time()
                return False

        except Exception as e:
            if (
                "added_venv_to_path" in locals()
                and added_venv_to_path
                and "site_packages" in locals()
                and site_packages
            ):
                try:
                    sys.path.remove(str(site_packages))
                except ValueError:
                    pass
            self._update_install_state(
                extension_id, "failed", 0, str(e), task_id=task_id
            )
            self.failed_extensions[extension_id] = time.time()
            log.exception(f"Critical error loading extension '{extension_id}': {e}")
            return False

    def load_all_extensions(self):
        """Loads all discovered extensions that ARE enabled."""
        from ..core.config import config_manager

        if not config_manager.get("allow_extensions", False):
            log.info(
                "Extensions are disabled. Enable them via Web UI Settings to use extensions."
            )
            return

        if self.safe_mode:
            log.warning("SAFE MODE ACTIVE: Skipping all extension loading.")
            log.warning(
                "To re-enable extensions, delete the crash file and restart PCLink."
            )
            return

        for extension_id in self.discover_extensions():
            extension_dir = self.extensions_path / extension_id
            manifest_path = extension_dir / "extension.yaml"
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f)
                if config.get("enabled", True):
                    self.load_extension(extension_id)
            except Exception:
                pass

    def unload_all_extensions(self):
        """Unloads all currently loaded extensions."""
        extension_ids = list(self.extensions.keys()) + list(
            self.isolated_processes.keys()
        )
        for extension_id in extension_ids:
            self.unload_extension(extension_id)
        log.info("All extensions have been unloaded.")

    def unload_extension(self, extension_id: str):
        """Unloads an extension and terminates its process if isolated."""
        if not self._is_safe_name(extension_id):
            return

        # 1. Handle Isolated Process Extension
        if extension_id in self.isolated_processes:
            info = self.isolated_processes.pop(extension_id)
            proc = info["process"]
            pipe = info["pipe"]

            try:
                pipe.send({"type": "CLEANUP"})
                time.sleep(0.1)
                proc.terminate()
                proc.join(timeout=2.0)
                if proc.is_alive():
                    proc.kill()
                    proc.join(timeout=1.0)
                pipe.close()
                log.info(f"Terminated isolated process for extension: {extension_id}")
            except Exception as e:
                log.error(f"Error terminating process for {extension_id}: {e}")

            self._cleanup_venv(extension_id)
            return

        # 2. Handle In-Process Extension
        if extension_id in self.extensions:
            extension = self.extensions[extension_id]
            try:
                cleanup_result = extension.cleanup()

                if inspect.iscoroutinefunction(
                    extension.cleanup
                ) or inspect.iscoroutine(cleanup_result):
                    try:
                        self._run_coro(cleanup_result)
                    except Exception as e:
                        log.error(
                            f"Failed to run async cleanup for {extension_id}: {e}"
                        )

                if extension.venv_path:
                    site_packages = self._get_venv_site_packages(extension.venv_path)
                    if site_packages:
                        try:
                            sys.path.remove(str(site_packages))
                        except ValueError:
                            pass

                del self.extensions[extension_id]

                module_prefix = f"pclink.extensions.{extension_id.replace('-', '_')}"
                to_remove = [
                    m
                    for m in sys.modules
                    if m == module_prefix or m.startswith(f"{module_prefix}.")
                ]
                for m in to_remove:
                    del sys.modules[m]

                self._cleanup_venv(extension_id)

                log.info(
                    f"Unloaded extension and purged {len(to_remove)} modules: {extension_id}"
                )
            except Exception as e:
                log.error(f"Error cleaning up extension {extension_id}: {e}")

    def get_extension(self, extension_id: str) -> Optional[Any]:
        """Returns the in-process extension instance or isolated process status dict."""
        if extension_id in self.extensions:
            return self.extensions[extension_id]
        if extension_id in self.isolated_processes:
            return self.isolated_processes[extension_id]
        return None

    def get_extension_logs(self, extension_id: str) -> List[str]:
        """Retrieve logs for a specific extension."""
        return self.logs.get(extension_id, [])

    def clear_extension_logs(self, extension_id: str):
        """Clear logs for a specific extension."""
        if extension_id in self.logs:
            self.logs[extension_id] = []

    def get_all_extensions(self) -> List[Any]:
        return list(self.extensions.values()) + list(self.isolated_processes.values())

    def verify_extension_bundle(self, bundle_path: Path) -> Optional[ExtensionMetadata]:
        """Verifies an extension bundle (zip) without installing it."""
        if not zipfile.is_zipfile(bundle_path):
            log.error(f"File {bundle_path} is not a valid zip file")
            return None

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            try:
                with zipfile.ZipFile(bundle_path, "r") as zip_ref:
                    if "extension.yaml" not in zip_ref.namelist():
                        log.error("Bundle missing 'extension.yaml'")
                        return None

                    zip_ref.extract("extension.yaml", temp_path)

                with open(temp_path / "extension.yaml", "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f)

                metadata = ExtensionMetadata(**config)

                if metadata.pclink_version:
                    log.info(
                        f"Extension {metadata.name} requires PCLink {metadata.pclink_version} (Current: {PCLINK_VERSION})"
                    )

                return metadata
            except Exception as e:
                log.error(f"Verification failed: {e}")
                return None

    def install_extension(
        self, bundle_path: Path, task_id: Optional[str] = None
    ) -> bool:
        """Installs an extension from a zip bundle."""
        from ..core.config import config_manager

        if not config_manager.get("allow_extensions", False):
            log.warning(
                "Attempted to install extension while extensions are globally disabled."
            )
            return False

        metadata = self.verify_extension_bundle(bundle_path)
        if not metadata:
            return False

        target_dir = self.extensions_path / metadata.name

        if metadata.name in self.extensions or metadata.name in self.isolated_processes:
            self.unload_extension(metadata.name)

        try:
            if target_dir.exists():
                shutil.rmtree(target_dir)

            target_dir.mkdir(parents=True)
            with zipfile.ZipFile(bundle_path, "r") as zip_ref:
                target_resolved = target_dir.resolve()
                for member in zip_ref.infolist():
                    extracted_path = (target_dir / member.filename).resolve()
                    if not extracted_path.is_relative_to(target_resolved):
                        log.error(
                            f"Security violation: Zip slip attempt blocked for '{member.filename}'"
                        )
                        shutil.rmtree(target_dir, ignore_errors=True)
                        return False
                zip_ref.extractall(target_dir)

            has_dangerous = any(
                p in DANGEROUS_PERMISSIONS for p in metadata.permissions
            )
            if has_dangerous:
                log.warning(
                    f"Extension {metadata.name} requests dangerous permissions: {metadata.permissions}"
                )
                log.warning(
                    f"Disabling extension {metadata.name} by default until user approval."
                )

                manifest_path = target_dir / "extension.yaml"
                try:
                    with open(manifest_path, "r", encoding="utf-8") as f:
                        config = yaml.safe_load(f)

                    config["enabled"] = False
                    config["security_consent_needed"] = True

                    with open(manifest_path, "w", encoding="utf-8") as f:
                        yaml.safe_dump(config, f)
                except Exception as e:
                    log.error(f"Failed to apply security lock to extension: {e}")
                    return False

                log.info(
                    f"Installed extension {metadata.name} to {target_dir} (Disabled pending approval)"
                )
                if task_id:
                    self._update_install_state(
                        metadata.name, "completed", 100, task_id=task_id
                    )
                return True
            else:
                log.info(f"Installed extension {metadata.name} to {target_dir}")
                self.failed_extensions.pop(metadata.name, None)
                return self.load_extension(
                    metadata.name, background=True, task_id=task_id
                )
        except Exception as e:
            log.error(f"Installation failed: {e}")
            if task_id:
                self._update_install_state(
                    metadata.name, "failed", 0, str(e), task_id=task_id
                )
            return False

    def delete_extension(self, extension_id: str) -> bool:
        """Unloads and permanently deletes an extension."""
        from ..core.config import config_manager

        if not config_manager.get("allow_extensions", False):
            log.warning(
                f"Attempted to delete extension '{extension_id}' while extensions are globally disabled."
            )
            return False

        if not self._is_safe_name(extension_id):
            return False

        self.unload_extension(extension_id)
        target_dir = (self.extensions_path / extension_id).resolve()

        if not target_dir.is_relative_to(self.extensions_path.resolve()):
            log.error(
                f"Security violation: Attempted to delete outside extensions path: {target_dir}"
            )
            return False

        try:
            if target_dir.exists():
                shutil.rmtree(target_dir)
            log.info(f"Deleted extension {extension_id}")
            return True
        except Exception as e:
            log.error(f"Failed to delete extension {extension_id}: {e}")
            return False

    def toggle_extension(self, extension_id: str, enabled: bool) -> bool:
        """Enables or disables an extension by updating its manifest."""
        from ..core.config import config_manager

        if not config_manager.get("allow_extensions", False):
            log.warning(
                f"Attempted to toggle extension '{extension_id}' while extensions are globally disabled."
            )
            return False

        extension = self.get_extension(extension_id)
        if not extension:
            extension_dir = self.extensions_path / extension_id
            manifest_path = extension_dir / "extension.yaml"
            if not manifest_path.exists():
                return False
        else:
            manifest_path = self.extensions_path / extension_id / "extension.yaml"

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)

            config["enabled"] = enabled

            with open(manifest_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(config, f)

            log.info(f"Extension {extension_id} {'enabled' if enabled else 'disabled'}")

            if enabled:
                self.failed_extensions.pop(extension_id, None)
                self.load_extension(extension_id, background=True)
                return True
            else:
                self.unload_extension(extension_id)
                return True
        except Exception as e:
            log.error(f"Failed to toggle extension {extension_id}: {e}")
            return False
