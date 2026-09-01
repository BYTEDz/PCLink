# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

"""
Supervised Extension Process Worker.
Executes extension initialization, lifecycle tasks, route handlers, and event dispatching in
a dedicated, isolated subprocess with bidirectional IPC communication.
"""

import asyncio
import gettext
import importlib.util
import inspect
import logging
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Dict

from .extension_base import ExtensionMetadata, StaticExtension
from .extension_context import ExtensionContext

_ = gettext.gettext


class WorkerIpcLogHandler(logging.Handler):
    """Captures child worker logging output and transmits records across the IPC pipe to the host."""

    def __init__(self, ipc_conn):
        super().__init__()
        self.ipc_conn = ipc_conn

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self.ipc_conn.send(
                {
                    "type": "LOG",
                    "message": msg,
                    "level": record.levelname,
                }
            )
        except Exception:
            pass


def run_extension_process(
    extension_id: str,
    extension_path_str: str,
    manifest_data: Dict[str, Any],
    config_data: Dict[str, Any],
    ipc_conn,
):
    if sys.platform == "win32":
        try:
            import pythoncom

            pythoncom.CoInitialize()
        except Exception:
            pass

    # Configure worker logger to pipe entries back to host server
    root_worker_logger = logging.getLogger()
    root_worker_logger.setLevel(logging.INFO)
    ipc_handler = WorkerIpcLogHandler(ipc_conn)
    ipc_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S"
        )
    )
    root_worker_logger.addHandler(ipc_handler)

    try:
        ext_path = Path(extension_path_str)
        metadata = ExtensionMetadata(**manifest_data)
        context = ExtensionContext(metadata, ipc_conn=ipc_conn)

        if str(ext_path) not in sys.path:
            sys.path.insert(0, str(ext_path))

        entry_point = metadata.backend.entry_point
        module_name = f"pclink_ext_{extension_id.replace('-', '_')}"
        instance = None

        if entry_point:
            if ":" in entry_point:
                file_part, class_name = entry_point.split(":", 1)
            else:
                file_part, class_name = entry_point, "Extension"

            module_path = ext_path / file_part
            if not module_path.suffix:
                module_path = module_path.with_suffix(".py")

            if not module_path.exists():
                ipc_conn.send(
                    {
                        "status": "error",
                        "error": _("Entry file missing: {}").format(module_path.name),
                    }
                )
                return

            spec = importlib.util.spec_from_file_location(module_name, module_path)
            if not spec or not spec.loader:
                ipc_conn.send(
                    {"status": "error", "error": "Failed to create module spec"}
                )
                return

            mod = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = mod
            spec.loader.exec_module(mod)

            cls = getattr(mod, class_name, None)
            if not cls:
                ipc_conn.send(
                    {
                        "status": "error",
                        "error": _("Class '{}' not found in {}").format(
                            class_name, module_path.name
                        ),
                    }
                )
                return

            instance = cls(
                metadata=metadata,
                extension_path=ext_path,
                config=config_data,
                context=context,
            )
        else:
            instance = StaticExtension(
                metadata=metadata,
                extension_path=ext_path,
                config=config_data,
                context=context,
            )

        get_routes_fn = getattr(instance, "get_routes", None)
        router = (
            get_routes_fn()
            if callable(get_routes_fn)
            else getattr(instance, "router", None)
        )

        init_fn = getattr(instance, "initialize", None)
        if callable(init_fn):
            init_res = init_fn()
            if asyncio.iscoroutine(init_res):
                init_res = asyncio.run(init_res)

            if init_res is False:
                ipc_conn.send(
                    {
                        "status": "error",
                        "error": _("Extension '{}' initialize() returned False").format(
                            extension_id
                        ),
                    }
                )
                return

        ipc_conn.send({"status": "ready", "pid": os.getpid()})

        cleaned_up = False
        try:
            while True:
                try:
                    if not ipc_conn.poll(0.1):
                        continue
                except KeyboardInterrupt:
                    break

                cmd = ipc_conn.recv()
                cmd_type = cmd.get("type")

                if cmd_type == "PING":
                    ipc_conn.send({"status": "pong", "pid": os.getpid()})

                elif cmd_type == "EVENT_DISPATCH":
                    event_name = cmd.get("event")
                    event_data = cmd.get("data", {})
                    listeners = getattr(context, "_event_listeners", {}).get(
                        event_name, []
                    )

                    for handler in listeners:
                        try:
                            if inspect.iscoroutinefunction(handler):
                                asyncio.run(handler(event_data))
                            else:
                                handler(event_data)
                        except Exception as e:
                            logging.getLogger(
                                f"pclink.extensions.{extension_id}"
                            ).error(f"Event handler error for '{event_name}': {e}")

                elif cmd_type == "HTTP_REQUEST":
                    req_id = cmd.get("req_id")
                    method = cmd.get("method", "GET").upper()
                    subpath = "/" + cmd.get("subpath", "/").lstrip("/")
                    body_data = cmd.get("body")

                    matched_handler = None
                    path_params = {}

                    if router:
                        for r in router.routes:
                            route_methods = getattr(r, "methods", {"GET"})
                            if method in route_methods or "ANY" in route_methods:
                                if hasattr(r, "path_regex"):
                                    match = r.path_regex.match(subpath)
                                    if match:
                                        matched_handler = r.endpoint
                                        path_params = match.groupdict()
                                        break
                                elif getattr(r, "path", None) == subpath:
                                    matched_handler = r.endpoint
                                    break

                    if matched_handler:
                        try:
                            sig = inspect.signature(matched_handler)
                            kwargs = {}
                            for param_name in sig.parameters:
                                if param_name in path_params:
                                    kwargs[param_name] = path_params[param_name]

                            if body_data is not None:
                                for param_name, param in sig.parameters.items():
                                    if param_name not in kwargs:
                                        if (
                                            isinstance(body_data, dict)
                                            and param_name in body_data
                                        ):
                                            kwargs[param_name] = body_data[param_name]
                                        elif len(sig.parameters) == 1:
                                            kwargs[param_name] = body_data

                            if inspect.iscoroutinefunction(matched_handler):
                                res = asyncio.run(matched_handler(**kwargs))
                            else:
                                res = matched_handler(**kwargs)

                            ipc_conn.send(
                                {
                                    "type": "HTTP_RESPONSE",
                                    "req_id": req_id,
                                    "status_code": 200,
                                    "content": res,
                                }
                            )
                        except Exception as e:
                            ipc_conn.send(
                                {
                                    "type": "HTTP_RESPONSE",
                                    "req_id": req_id,
                                    "status_code": 500,
                                    "error": str(e),
                                }
                            )
                    else:
                        ipc_conn.send(
                            {
                                "type": "HTTP_RESPONSE",
                                "req_id": req_id,
                                "status_code": 404,
                                "error": f"Route '{method} {subpath}' not found",
                            }
                        )

                elif cmd_type == "CLEANUP":
                    try:
                        cleanup_fn = getattr(instance, "cleanup", None)
                        if callable(cleanup_fn):
                            clean_res = cleanup_fn()
                            if asyncio.iscoroutine(clean_res):
                                asyncio.run(clean_res)
                        cleaned_up = True
                        ipc_conn.send({"status": "cleaned"})
                    except Exception as e:
                        ipc_conn.send({"status": "error", "error": str(e)})
                    break

        except KeyboardInterrupt:
            pass

        if not cleaned_up:
            try:
                cleanup_fn = getattr(instance, "cleanup", None)
                if callable(cleanup_fn):
                    clean_res = cleanup_fn()
                    if asyncio.iscoroutine(clean_res):
                        asyncio.run(clean_res)
            except Exception:
                pass

    except Exception as e:
        tb = traceback.format_exc()
        try:
            ipc_conn.send({"status": "crash", "error": str(e), "traceback": tb})
        except Exception:
            pass
