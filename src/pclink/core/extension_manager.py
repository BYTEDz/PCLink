# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import gettext
import json
import logging
import multiprocessing
import platform as py_platform
import shutil
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil

from .extension_base import (
    DANGEROUS_PERMISSIONS,
    ExtensionMetadata,
    StaticExtension,
)
from .extension_context import ExtensionContext
from .extension_runner import run_extension_process

log = logging.getLogger(__name__)
_ = gettext.gettext

SAFE_MODE_CRASH_THRESHOLD = 3
MAX_UNCOMPRESSED_BUNDLE_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_BUNDLE_FILE_COUNT = 1000


class ExtensionManager:
    _instance = None
    _lock = threading.RLock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(ExtensionManager, cls).__new__(cls)
            return cls._instance

    def __init__(self):
        if not hasattr(self, "initialized"):
            from . import constants

            self.extensions_path: Path = constants.APP_DATA_PATH / "extensions"
            self.extensions_path.mkdir(parents=True, exist_ok=True)

            self.extensions: Dict[str, StaticExtension] = {}
            self.isolated_processes: Dict[str, Dict[str, Any]] = {}
            self._pending_http_requests: Dict[str, Any] = {}
            self.logs: Dict[str, List[str]] = {}
            self.failed_extensions: Dict[str, float] = {}
            self.install_states: Dict[str, Dict[str, Any]] = {}
            self._metadata_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}

            self._crash_file = constants.APP_DATA_PATH / ".extension_crashes"
            self.safe_mode = False
            self._check_safe_mode()
            self._init_system_info()

            self.initialized = True

    def _init_system_info(self):
        current_arch = py_platform.machine().lower()
        arch_aliases = {
            "x86_64": ["x86_64", "amd64"],
            "amd64": ["x86_64", "amd64"],
            "aarch64": ["aarch64", "arm64"],
            "arm64": ["aarch64", "arm64"],
        }
        distro = "unknown"
        if py_platform.system().lower() == "linux":
            try:
                import distro as distro_lib

                distro = distro_lib.id().lower()
            except ImportError:
                pass

        self._sys_info = {
            "platform": py_platform.system().lower(),
            "arch_aliases": arch_aliases.get(current_arch, [current_arch]),
            "distro": distro,
        }

    def _check_safe_mode(self):
        crash_count = 0
        if self._crash_file.exists():
            try:
                crash_count = int(self._crash_file.read_text().strip())
            except (ValueError, OSError):
                crash_count = 0

        if crash_count >= SAFE_MODE_CRASH_THRESHOLD:
            log.warning(
                "Safe mode active: extensions disabled due to repeated startup crashes."
            )
            self.safe_mode = True
        else:
            self._crash_file.write_text(str(crash_count + 1))

    def mark_startup_success(self):
        if self._crash_file.exists():
            try:
                self._crash_file.unlink()
                log.debug("Startup successful; extension crash counter cleared.")
            except OSError:
                pass

    def _is_compatible(self, metadata: ExtensionMetadata) -> bool:
        if self._sys_info["platform"] not in [
            p.lower() for p in metadata.supported_platforms
        ]:
            return False

        supported_archs = [a.lower() for a in metadata.supported_architectures]
        if not any(
            alias in supported_archs for alias in self._sys_info["arch_aliases"]
        ):
            return False

        if self._sys_info["platform"] == "linux" and metadata.supported_distros:
            if self._sys_info["distro"] not in [
                d.lower() for d in metadata.supported_distros
            ]:
                return False

        return True

    def _resolve_extension_dir(self, identifier: str) -> Optional[Path]:
        if not self.extensions_path.exists():
            return None

        # Direct folder match
        direct = self.extensions_path / identifier
        if direct.is_dir() and (direct / "manifest.json").exists():
            return direct

        # Match by manifest 'id' or 'name' across subdirectories
        for entry in self.extensions_path.iterdir():
            if entry.is_dir() and (entry / "manifest.json").exists():
                try:
                    with open(entry / "manifest.json", "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if (
                        data.get("id") == identifier
                        or data.get("name") == identifier
                        or entry.name == identifier
                    ):
                        return entry
                except Exception:
                    continue
        return None

    def get_manifest(self, identifier: str) -> Optional[Dict[str, Any]]:
        ext_dir = self._resolve_extension_dir(identifier)
        if not ext_dir:
            return None

        manifest_path = ext_dir / "manifest.json"
        try:
            mtime = manifest_path.stat().st_mtime
            cache_key = ext_dir.name
            if cache_key in self._metadata_cache:
                cached_mtime, cached_data = self._metadata_cache[cache_key]
                if cached_mtime == mtime:
                    return cached_data

            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if "id" not in data:
                data["id"] = ext_dir.name

            if "declared_permissions" not in data:
                data["declared_permissions"] = list(data.get("permissions", []))

            # Mandatory Security Checkup on Discovery:
            # If an extension declaring dangerous permissions was manually dropped into the folder
            # without an explicit approval signature, quarantine it immediately.
            perms = data.get("permissions", [])
            has_dangerous = any(p in DANGEROUS_PERMISSIONS for p in perms)

            if has_dangerous:
                if "security_consent_needed" not in data:
                    data["enabled"] = False
                    data["security_consent_needed"] = True
                    try:
                        with open(manifest_path, "w", encoding="utf-8") as f:
                            json.dump(data, f, indent=2)
                        mtime = manifest_path.stat().st_mtime
                    except Exception as e:
                        log.error(
                            f"Failed to persist quarantine for '{ext_dir.name}': {e}"
                        )

            self._metadata_cache[cache_key] = (mtime, data)
            return data
        except Exception as e:
            log.error(f"Failed to read manifest for '{identifier}': {e}")
            return None

    def discover_extensions(self) -> List[str]:
        if not self.extensions_path.exists():
            return []

        discovered = []
        for entry in self.extensions_path.iterdir():
            if entry.is_dir() and (entry / "manifest.json").exists():
                discovered.append(entry.name)
        return sorted(discovered)

    def verify_bundle(self, bundle_path: Path) -> Optional[ExtensionMetadata]:
        if not zipfile.is_zipfile(bundle_path):
            return None

        with zipfile.ZipFile(bundle_path, "r") as zf:
            total_size = sum(info.file_size for info in zf.infolist())
            if total_size > MAX_UNCOMPRESSED_BUNDLE_SIZE:
                log.error(
                    _(
                        "Zip extraction exceeded maximum uncompressed size limit ({max_mb} MB)."
                    ).format(max_mb=MAX_UNCOMPRESSED_BUNDLE_SIZE // (1024 * 1024))
                )
                return None

            if len(zf.infolist()) > MAX_BUNDLE_FILE_COUNT:
                log.error("Zip bundle exceeds maximum allowed file count.")
                return None

            if "manifest.json" not in zf.namelist():
                log.error(_("Manifest file (manifest.json) not found in bundle."))
                return None

            try:
                content = zf.read("manifest.json").decode("utf-8")
                raw_meta = json.loads(content)
                if "declared_permissions" not in raw_meta:
                    raw_meta["declared_permissions"] = list(
                        raw_meta.get("permissions", [])
                    )
                return ExtensionMetadata(**raw_meta)
            except Exception as e:
                log.error(
                    _("Extension manifest contains invalid schema: {error}").format(
                        error=e
                    )
                )
                return None

    def install_extension(
        self, bundle_path: Path, task_id: Optional[str] = None
    ) -> bool:
        from ..core.config import config_manager

        if not config_manager.get("allow_extensions", False):
            return False

        metadata = self.verify_bundle(bundle_path)
        if not metadata:
            return False

        target_dir = self.extensions_path / metadata.id
        self.unload_extension(metadata.id)

        try:
            if target_dir.exists():
                shutil.rmtree(target_dir)
            target_dir.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(bundle_path, "r") as zf:
                resolved_target = target_dir.resolve()
                for member in zf.infolist():
                    dest_path = (target_dir / member.filename).resolve()
                    if not dest_path.is_relative_to(resolved_target):
                        log.error(_("Extension bundle contains unsafe file paths."))
                        shutil.rmtree(target_dir, ignore_errors=True)
                        return False
                zf.extractall(target_dir)

            manifest_file = target_dir / "manifest.json"
            manifest_data = self.get_manifest(metadata.id) or {}

            manifest_data["declared_permissions"] = list(
                metadata.declared_permissions or metadata.permissions
            )

            has_dangerous = any(
                p in DANGEROUS_PERMISSIONS for p in metadata.permissions
            )
            if has_dangerous:
                metadata.enabled = False
                metadata.security_consent_needed = True
                manifest_data["enabled"] = False
                manifest_data["security_consent_needed"] = True

                with open(manifest_file, "w", encoding="utf-8") as f:
                    json.dump(manifest_data, f, indent=2)

                log.info(
                    f"Extension '{metadata.id}' installed (quarantined pending consent)."
                )
                return True

            with open(manifest_file, "w", encoding="utf-8") as f:
                json.dump(manifest_data, f, indent=2)

            log.info(f"Extension '{metadata.id}' installed successfully.")
            return self.load_extension(metadata.id, task_id=task_id)

        except Exception as e:
            log.error(f"Failed to install extension '{metadata.id}': {e}")
            if target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)
            return False

    def load_extension(
        self, identifier: str, background: bool = False, task_id: Optional[str] = None
    ) -> bool:
        from ..core.config import config_manager

        if not config_manager.get("allow_extensions", False) or self.safe_mode:
            return False

        ext_dir = self._resolve_extension_dir(identifier)
        if not ext_dir:
            return False

        ext_id = ext_dir.name
        if self.get_extension(ext_id) is not None:
            return True

        if background:
            threading.Thread(
                target=self._load_extension_impl,
                args=(ext_id, task_id),
                daemon=True,
                name=f"ext-loader-{ext_id}",
            ).start()
            return True

        return self._load_extension_impl(ext_id, task_id)

    def _load_extension_impl(
        self, extension_id: str, task_id: Optional[str] = None
    ) -> bool:
        manifest_data = self.get_manifest(extension_id)
        if not manifest_data:
            return False

        try:
            metadata = ExtensionMetadata(**manifest_data)
            if not self._is_compatible(metadata):
                return False

            # Hard Quarantine Gate: Reject runtime initialization if consent is pending
            if metadata.security_consent_needed or not metadata.enabled:
                log.warning(
                    _(
                        "Quarantined: Extension '{extension_id}' contains dangerous permissions and requires administrator approval."
                    ).format(extension_id=metadata.id)
                )
                return False

            ext_dir = self._resolve_extension_dir(extension_id)
            if not ext_dir:
                return False

            canonical_id = metadata.id

            # Tier 1: Pure Web Extension
            if metadata.backend.runtime == "none":
                context = ExtensionContext(metadata)
                instance = StaticExtension(
                    metadata=metadata,
                    extension_path=ext_dir,
                    config=manifest_data,
                    context=context,
                )
                self.extensions[canonical_id] = instance
                self.extensions[ext_dir.name] = instance
                self.failed_extensions.pop(canonical_id, None)
                self.failed_extensions.pop(extension_id, None)
                log.info(f"Loaded web extension: {metadata.name} ({metadata.version})")
                return True

            # Tier 2 & 3: Supervised Process Worker
            return self._spawn_worker_process(
                canonical_id, metadata, ext_dir, manifest_data, task_id
            )

        except Exception as e:
            log.error(f"Error loading extension '{extension_id}': {e}")
            self.failed_extensions[extension_id] = time.time()
            return False

    def _spawn_worker_process(
        self,
        extension_id: str,
        metadata: ExtensionMetadata,
        ext_dir: Path,
        manifest_data: Dict[str, Any],
        task_id: Optional[str] = None,
    ) -> bool:
        host_pipe, child_pipe = multiprocessing.Pipe()
        proc = multiprocessing.Process(
            target=run_extension_process,
            args=(
                extension_id,
                str(ext_dir),
                metadata.model_dump(),
                manifest_data,
                child_pipe,
            ),
            name=f"pclink-ext-{extension_id}",
            daemon=True,
        )
        proc.start()

        start_time = time.time()
        ready = False
        context = ExtensionContext(metadata, ipc_conn=host_pipe)

        # Handshake loop: Answers any initial CONTEXT_CALLs to avoid startup deadlocks
        while time.time() - start_time < 10.0:
            if host_pipe.poll(0.1):
                msg = host_pipe.recv()
                status = msg.get("status")
                msg_type = msg.get("type")

                if status == "ready":
                    ready = True
                    break
                elif status in ("error", "crash"):
                    log.error(
                        _(
                            "Worker process for extension '{ext_id}' failed to initialize."
                        ).format(ext_id=extension_id)
                    )
                    proc.terminate()
                    return False
                elif msg_type == "CONTEXT_CALL":
                    api_name = msg.get("api")
                    method_name = msg.get("method")
                    kwargs = msg.get("kwargs", {})
                    try:
                        api_obj = getattr(context, api_name, None)
                        func = getattr(api_obj, method_name, None)
                        result = func(**kwargs)
                        host_pipe.send({"status": "success", "result": result})
                    except Exception as e:
                        host_pipe.send({"status": "error", "error": str(e)})

            if not proc.is_alive():
                log.error(f"Worker process '{extension_id}' exited prematurely.")
                return False

        if not ready:
            proc.terminate()
            log.error(f"Worker process for '{extension_id}' timed out on startup.")
            return False

        worker_entry = {
            "process": proc,
            "pipe": host_pipe,
            "pid": proc.pid,
            "started_at": time.time(),
            "metadata": metadata,
            "dir_name": ext_dir.name,
        }

        self.isolated_processes[extension_id] = worker_entry
        self.isolated_processes[ext_dir.name] = worker_entry

        threading.Thread(
            target=self._ipc_event_loop,
            args=(extension_id, host_pipe, metadata),
            name=f"ext-ipc-{extension_id}",
            daemon=True,
        ).start()

        self.failed_extensions.pop(extension_id, None)
        log.info(
            f"Spawned isolated worker for extension '{metadata.name}' (PID={proc.pid})"
        )
        return True

    def _ipc_event_loop(
        self, extension_id: str, host_pipe, metadata: ExtensionMetadata
    ):
        context = ExtensionContext(metadata, ipc_conn=host_pipe)

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
                        api_obj = getattr(context, api_name, None)
                        if not api_obj:
                            raise AttributeError(f"API domain '{api_name}' invalid")
                        func = getattr(api_obj, method_name, None)
                        if not func:
                            raise AttributeError(f"Method '{method_name}' invalid")

                        result = func(**kwargs)
                        host_pipe.send({"status": "success", "result": result})
                    except Exception as e:
                        host_pipe.send({"status": "error", "error": str(e)})

            except (EOFError, BrokenPipeError, OSError):
                break
            except Exception as e:
                log.error(f"IPC loop error for '{extension_id}': {e}")
                break

    def dispatch_ipc_http_request(
        self,
        extension_id: str,
        method: str,
        subpath: str,
        body: Optional[Any] = None,
        timeout: float = 10.0,
    ) -> Optional[Dict[str, Any]]:
        info = self.get_extension(extension_id)
        if not info or not isinstance(info, dict):
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

            return {"status_code": 504, "error": "Extension IPC timeout"}
        except Exception as e:
            return {"status_code": 500, "error": str(e)}

    def dispatch_event(self, event_name: str, data: Dict[str, Any]):
        visited_pipes = set()
        for info in list(self.isolated_processes.values()):
            if isinstance(info, dict):
                pipe = info.get("pipe")
                if pipe and id(pipe) not in visited_pipes:
                    visited_pipes.add(id(pipe))
                    try:
                        pipe.send(
                            {
                                "type": "EVENT_DISPATCH",
                                "event": event_name,
                                "data": data,
                            }
                        )
                    except Exception as e:
                        log.error(f"Event dispatch error: {e}")

        visited_exts = set()
        for ext in list(self.extensions.values()):
            if id(ext) not in visited_exts:
                visited_exts.add(id(ext))
                if hasattr(ext, "context") and ext.context:
                    listeners = ext.context._event_listeners.get(event_name, [])
                    for handler in listeners:
                        try:
                            handler(data)
                        except Exception as e:
                            log.error(f"Local event listener error: {e}")

    def unload_extension(self, identifier: str):
        ext_dir = self._resolve_extension_dir(identifier)
        dir_name = ext_dir.name if ext_dir else identifier

        info = self.isolated_processes.pop(
            dir_name, None
        ) or self.isolated_processes.pop(identifier, None)
        if info and isinstance(info, dict):
            proc = info.get("process")
            pipe = info.get("pipe")
            if pipe:
                try:
                    pipe.send({"type": "CLEANUP"})
                except Exception:
                    pass
            if proc:
                try:
                    proc.terminate()
                    proc.join(timeout=1.5)
                    if proc.is_alive():
                        proc.kill()
                except Exception:
                    pass

        self.extensions.pop(dir_name, None)
        self.extensions.pop(identifier, None)

        log.info(f"Unloaded extension '{identifier}'.")

    def load_all_extensions(self):
        from ..core.config import config_manager

        if not config_manager.get("allow_extensions", False) or self.safe_mode:
            return

        for extension_id in self.discover_extensions():
            manifest = self.get_manifest(extension_id)
            if (
                manifest
                and manifest.get("enabled", True)
                and not manifest.get("security_consent_needed", False)
            ):
                self.load_extension(extension_id)

    def unload_all_extensions(self):
        for eid in list(self.extensions.keys()) + list(self.isolated_processes.keys()):
            self.unload_extension(eid)

    def delete_extension(self, identifier: str) -> bool:
        self.unload_extension(identifier)
        ext_dir = self._resolve_extension_dir(identifier)
        if not ext_dir or not ext_dir.is_relative_to(self.extensions_path.resolve()):
            return False

        try:
            if ext_dir.exists():
                shutil.rmtree(ext_dir)
            log.info(f"Deleted extension: '{identifier}'.")
            return True
        except Exception as e:
            log.error(f"Failed to delete extension '{identifier}': {e}")
            return False

    def toggle_extension(self, identifier: str, enabled: bool) -> bool:
        ext_dir = self._resolve_extension_dir(identifier)
        if not ext_dir:
            return False

        manifest_data = self.get_manifest(identifier)
        if not manifest_data:
            return False

        manifest_file = ext_dir / "manifest.json"
        try:
            manifest_data["enabled"] = enabled
            if enabled:
                manifest_data["security_consent_needed"] = False

            with open(manifest_file, "w", encoding="utf-8") as f:
                json.dump(manifest_data, f, indent=2)

            self._metadata_cache.pop(ext_dir.name, None)

            if enabled:
                return self.load_extension(ext_dir.name)
            else:
                self.unload_extension(ext_dir.name)
                return True
        except Exception as e:
            log.error(f"Failed to toggle extension '{identifier}': {e}")
            return False

    def get_extension(self, identifier: str) -> Optional[Any]:
        ext_dir = self._resolve_extension_dir(identifier)
        dir_name = ext_dir.name if ext_dir else identifier
        return (
            self.extensions.get(identifier)
            or self.extensions.get(dir_name)
            or self.isolated_processes.get(identifier)
            or self.isolated_processes.get(dir_name)
        )

    def get_extension_telemetry(self, identifier: str) -> Dict[str, Any]:
        info = self.get_extension(identifier)
        if not info or not isinstance(info, dict) or not info.get("pid"):
            return {}

        try:
            proc = psutil.Process(info["pid"])
            return {
                "pid": info["pid"],
                "cpu_percent": round(proc.cpu_percent(interval=None), 1),
                "memory_mb": round(proc.memory_info().rss / (1024 * 1024), 1),
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return {"pid": info["pid"], "cpu_percent": 0.0, "memory_mb": 0.0}

    def get_extension_logs(self, identifier: str) -> List[str]:
        ext_dir = self._resolve_extension_dir(identifier)
        target_id = ext_dir.name if ext_dir else identifier
        return self.logs.get(target_id, [])

    def clear_extension_logs(self, identifier: str):
        ext_dir = self._resolve_extension_dir(identifier)
        target_id = ext_dir.name if ext_dir else identifier
        self.logs.pop(target_id, None)
