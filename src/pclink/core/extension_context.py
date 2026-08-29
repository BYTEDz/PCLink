# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import json
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from .extension_base import ExtensionMetadata

log = logging.getLogger(__name__)

PERMISSION_ALIASES: Dict[str, set] = {
    "media.read": {"media", "media.read"},
    "media.control": {"media", "media.control"},
    "input.inject": {"input", "input.inject"},
    "power.control": {"power", "power.control", "system"},
    "system.exec": {"system", "system.exec"},
    "fs.read": {"fs.read", "filesystem.read", "files_read", "fs.all"},
    "fs.write": {"fs.write", "filesystem.write", "files_write", "fs.all"},
    "storage.local": {"storage", "storage.local"},
    "notifications": {"notifications", "notification"},
}


class PermissionDeniedError(PermissionError):
    pass


class ExtensionAPI:
    def __init__(self, metadata: ExtensionMetadata, ipc_conn: Any = None):
        self.metadata = metadata
        self.ipc_conn = ipc_conn

    def _check_permission(self, permission: str) -> None:
        granted_set = set(self.metadata.permissions)
        accepted_aliases = PERMISSION_ALIASES.get(permission, {permission})

        if (
            not granted_set.intersection(accepted_aliases)
            and "fs.all" not in granted_set
        ):
            raise PermissionDeniedError(
                f"Permission denied: capability '{permission}' is not granted to extension '{self.metadata.id}'."
            )

    def _call_ipc(self, api_name: str, method: str, kwargs: Dict[str, Any]) -> Any:
        if not self.ipc_conn:
            return None
        try:
            self.ipc_conn.send(
                {
                    "type": "CONTEXT_CALL",
                    "api": api_name,
                    "method": method,
                    "kwargs": kwargs,
                }
            )
            response = self.ipc_conn.recv()
            if response.get("status") == "error":
                raise RuntimeError(response.get("error", "IPC Call Failed"))
            return response.get("result")
        except Exception as e:
            log.error(f"IPC context call failed ({api_name}.{method}): {e}")
            return None


class ExecAPI(ExtensionAPI):
    def run(
        self,
        command: Union[str, List[str]],
        timeout: int = 15,
        cwd: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._check_permission("system.exec")
        if self.ipc_conn:
            return self._call_ipc(
                "exec", "run", {"command": command, "timeout": timeout, "cwd": cwd}
            )

        kwargs: Dict[str, Any] = {
            "shell": isinstance(command, str),
            "capture_output": True,
            "text": True,
            "timeout": timeout,
            "cwd": cwd,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        try:
            res = subprocess.run(command, **kwargs)
            return {
                "exit_code": res.returncode,
                "stdout": res.stdout,
                "stderr": res.stderr,
            }
        except subprocess.TimeoutExpired:
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Command timed out after {timeout} seconds",
            }
        except Exception as e:
            return {"exit_code": -1, "stdout": "", "stderr": str(e)}


class FsAPI(ExtensionAPI):
    def _get_base_path(self) -> Path:
        from . import constants

        path = constants.APP_DATA_PATH / "extension_data" / self.metadata.id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _resolve_safe_path(self, relative_path: str) -> Path:
        base = self._get_base_path().resolve()
        target = (base / relative_path).resolve()
        if "fs.all" not in self.metadata.permissions and not target.is_relative_to(
            base
        ):
            raise PermissionDeniedError(
                f"File access outside allowed scope is forbidden: {relative_path}"
            )
        return target

    def read_text(self, path: str) -> str:
        self._check_permission("fs.read")
        target = self._resolve_safe_path(path)
        return target.read_text(encoding="utf-8")

    def write_text(self, path: str, content: str) -> bool:
        self._check_permission("fs.write")
        target = self._resolve_safe_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return True

    def list_dir(self, path: str = ".") -> List[Dict[str, Any]]:
        self._check_permission("fs.read")
        target = self._resolve_safe_path(path)
        if not target.is_dir():
            return []
        items = []
        for entry in os.scandir(target):
            items.append(
                {
                    "name": entry.name,
                    "is_dir": entry.is_dir(),
                    "size": entry.stat().st_size if not entry.is_dir() else 0,
                    "modified_at": entry.stat().st_mtime,
                }
            )
        return items


class FetchAPI(ExtensionAPI):
    def request(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        body: Optional[Any] = None,
        timeout: int = 10,
    ) -> Dict[str, Any]:
        self._check_permission("net.fetch")
        if self.ipc_conn:
            return self._call_ipc(
                "fetch",
                "request",
                {
                    "url": url,
                    "method": method,
                    "headers": headers,
                    "body": body,
                    "timeout": timeout,
                },
            )

        import urllib.error
        import urllib.request

        req_headers = headers or {"User-Agent": f"PCLink-Extension/{self.metadata.id}"}
        data_bytes = None
        if body:
            if isinstance(body, (dict, list)):
                data_bytes = json.dumps(body).encode("utf-8")
                req_headers["Content-Type"] = "application/json"
            elif isinstance(body, str):
                data_bytes = body.encode("utf-8")

        req = urllib.request.Request(
            url, data=data_bytes, headers=req_headers, method=method.upper()
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content = resp.read().decode("utf-8", errors="ignore")
                return {
                    "status_code": resp.status,
                    "headers": dict(resp.headers),
                    "body": content,
                }
        except urllib.error.HTTPError as e:
            return {
                "status_code": e.code,
                "headers": dict(e.headers),
                "body": e.read().decode("utf-8", errors="ignore"),
            }
        except Exception as e:
            return {"status_code": 500, "headers": {}, "body": str(e)}


class StorageAPI(ExtensionAPI):
    _locks: Dict[str, threading.RLock] = {}
    _master_lock = threading.Lock()

    def _get_extension_lock(self) -> threading.RLock:
        with self._master_lock:
            if self.metadata.id not in self._locks:
                self._locks[self.metadata.id] = threading.RLock()
            return self._locks[self.metadata.id]

    def _get_store_path(self) -> Path:
        from . import constants

        p = constants.APP_DATA_PATH / "extension_data" / self.metadata.id / "kv.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def get(self, key: str, default: Any = None) -> Any:
        self._check_permission("storage.local")
        p = self._get_store_path()
        lock = self._get_extension_lock()
        with lock:
            if not p.exists():
                return default
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                return data.get(key, default)
            except Exception:
                return default

    def set(self, key: str, value: Any) -> bool:
        self._check_permission("storage.local")
        p = self._get_store_path()
        lock = self._get_extension_lock()
        with lock:
            data = {}
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    data = {}
            data[key] = value

            temp_path = p.with_suffix(".tmp")
            temp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            temp_path.replace(p)
            return True


class InputAPI(ExtensionAPI):
    def mouse_move(self, dx: int, dy: int) -> None:
        self._check_permission("input.inject")
        if self.ipc_conn:
            return self._call_ipc("input", "mouse_move", {"dx": dx, "dy": dy})
        from ..services.input_service import input_service

        input_service.mouse_move(dx, dy)

    def mouse_click(self, button: str = "left", clicks: int = 1) -> None:
        self._check_permission("input.inject")
        if self.ipc_conn:
            return self._call_ipc(
                "input", "mouse_click", {"button": button, "clicks": clicks}
            )
        from ..services.input_service import input_service

        input_service.mouse_click(button, clicks)

    def keyboard_press_key(
        self, key_str: str, modifiers: Optional[List[str]] = None
    ) -> None:
        self._check_permission("input.inject")
        if self.ipc_conn:
            return self._call_ipc(
                "input",
                "keyboard_press_key",
                {"key_str": key_str, "modifiers": modifiers or []},
            )
        from ..services.input_service import input_service

        input_service.keyboard_press_key(key_str, modifiers or [])


class MediaAPI(ExtensionAPI):
    async def get_state(self) -> Dict[str, Any]:
        self._check_permission("media.read")
        from ..services.media_service import media_service

        return await media_service.get_media_info()

    async def command(self, action: str) -> None:
        self._check_permission("media.control")
        from ..services.media_service import media_service

        await media_service.media_command(action)


class PowerAPI(ExtensionAPI):
    async def execute(self, action: str) -> None:
        self._check_permission("power.control")
        from ..services.system_service import system_service

        await system_service.power_command(action)


class NotificationAPI(ExtensionAPI):
    def show(self, title: str, message: str, type: str = "info") -> bool:
        if self.ipc_conn:
            return bool(
                self._call_ipc(
                    "notification",
                    "show",
                    {"title": title, "message": message, "type": type},
                )
            )
        try:
            from ..api_server.ws_manager import ui_manager

            asyncio.create_task(
                ui_manager.broadcast(
                    {
                        "type": "notification",
                        "data": {"title": title, "message": message, "type": type},
                    }
                )
            )
            return True
        except Exception as e:
            log.error(f"Failed to dispatch notification: {e}")
            return False


class ThemeAPI(ExtensionAPI):
    def get_theme(self) -> str:
        from ..core.config import config_manager

        return config_manager.get("theme", "dark")


class ExtensionContext:
    def __init__(self, metadata: ExtensionMetadata, ipc_conn: Any = None):
        from . import constants

        self.metadata = metadata
        self.ipc_conn = ipc_conn

        self.exec = ExecAPI(metadata, ipc_conn=ipc_conn)
        self.fs = FsAPI(metadata, ipc_conn=ipc_conn)
        self.fetch = FetchAPI(metadata, ipc_conn=ipc_conn)
        self.storage = StorageAPI(metadata, ipc_conn=ipc_conn)

        self.input = InputAPI(metadata, ipc_conn=ipc_conn)
        self.media = MediaAPI(metadata, ipc_conn=ipc_conn)
        self.power = PowerAPI(metadata, ipc_conn=ipc_conn)
        self.notification = NotificationAPI(metadata, ipc_conn=ipc_conn)
        self.theme = ThemeAPI(metadata, ipc_conn=ipc_conn)

        self._event_listeners: Dict[str, List[Callable]] = {}
        self._data_path = constants.APP_DATA_PATH / "extension_data" / metadata.id
        self._data_path.mkdir(parents=True, exist_ok=True)

    @property
    def data_path(self) -> Path:
        return self._data_path

    def notify(self, title: str, message: str, type: str = "info") -> bool:
        return self.notification.show(title, message, type)

    def on(self, event_name: str, handler: Callable) -> None:
        if event_name not in self._event_listeners:
            self._event_listeners[event_name] = []
        self._event_listeners[event_name].append(handler)

    def publish_event(
        self, event_name: str, data: Optional[Dict[str, Any]] = None
    ) -> None:
        if self.ipc_conn:
            try:
                self.ipc_conn.send(
                    {
                        "type": "CONTEXT_CALL",
                        "api": "context",
                        "method": "publish_event",
                        "kwargs": {"event_name": event_name, "data": data or {}},
                    }
                )
            except Exception as e:
                log.error(f"IPC publish event error: {e}")
            return

        from .extension_manager import ExtensionManager

        ExtensionManager().dispatch_event(event_name, data or {})
