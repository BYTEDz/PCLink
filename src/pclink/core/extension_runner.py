# src/pclink/core/extension_runner.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

"""
Isolated Extension Process Worker.
Executes extension initialization, lifecycle tasks, route handlers, and event dispatching in
a dedicated, supervised subprocess with IPC HTTP route dispatching.
"""

import asyncio
import importlib.util
import inspect
import logging
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Dict

from .extension_base import ExtensionMetadata
from .extension_context import ExtensionContext

log = logging.getLogger("pclink.extension_worker")


def run_extension_process(
    extension_id: str,
    extension_path_str: str,
    manifest_data: Dict[str, Any],
    config_data: Dict[str, Any],
    ipc_conn,
):
    """
    Entry point for the isolated extension subprocess.
    Traps exceptions, serves route execution requests via IPC, dispatches system events, and prevents host crashes.
    """
    import gettext

    _ = gettext.gettext

    if sys.platform == "win32":
        try:
            import pythoncom

            pythoncom.CoInitialize()
        except Exception:
            pass

    try:
        ext_path = Path(extension_path_str)
        metadata = ExtensionMetadata(**manifest_data)
        context = ExtensionContext(metadata, ipc_conn=ipc_conn)

        # 1. Add extension directory to python path
        if str(ext_path) not in sys.path:
            sys.path.insert(0, str(ext_path))

        # 2. Dynamic import of entry point module
        entry_point = metadata.entry_point
        module_name = f"pclink_isolated_ext_{extension_id}"

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
                    {"status": "error", "error": _("Failed to create module spec")}
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

            # 3. Inspect __init__ signature for legacy compatibility
            params = inspect.signature(cls.__init__).parameters
            supports_context = "context" in params or any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
            )

            if supports_context:
                instance = cls(
                    metadata=metadata,
                    extension_path=ext_path,
                    config=config_data,
                    context=context,
                )
            else:
                instance = cls(
                    metadata=metadata,
                    extension_path=ext_path,
                    config=config_data,
                )
                instance.context = context
        else:
            # Fallback if entry_point is omitted
            from .extension_base import StaticExtension

            instance = StaticExtension(
                metadata=metadata,
                extension_path=ext_path,
                config=config_data,
                context=context,
            )

        # 4. Get router instance safely
        get_routes_fn = getattr(instance, "get_routes", None)
        if callable(get_routes_fn):
            router = get_routes_fn()
        else:
            router = getattr(instance, "router", None)

        from fastapi import APIRouter

        if not router:
            router = APIRouter()

        # 5. Initialize extension safely (optional lifecycle hook)
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

        # Signal successful initialization to host process
        ipc_conn.send({"status": "ready", "pid": os.getpid()})

        # 6. Enter IPC Command, Event Dispatch & HTTP Route Dispatcher Loop
        cleaned_up = False
        try:
            while True:
                try:
                    if not ipc_conn.poll(0.1):
                        continue
                except KeyboardInterrupt:
                    log.info(
                        _("Extension '{}' received interrupt signal").format(
                            extension_id
                        )
                    )
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
                            log.error(
                                f"Error executing event handler for '{event_name}' in extension '{extension_id}': {e}"
                            )

                elif cmd_type == "HTTP_REQUEST":
                    req_id = cmd.get("req_id")
                    method = cmd.get("method", "GET").upper()
                    subpath = cmd.get("subpath", "/")
                    if not subpath.startswith("/"):
                        subpath = "/" + subpath

                    body_data = cmd.get("body")

                    matched_handler = None
                    path_params = {}

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
                            log.error(
                                _("Error executing route '{} {}': {}").format(
                                    method, subpath, e
                                ),
                                exc_info=True,
                            )
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
                                "error": _(
                                    "Route '{} {}' not found in worker process"
                                ).format(method, subpath),
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

                elif cmd_type == "SHUTDOWN":
                    break

        except KeyboardInterrupt:
            log.info(_("Extension '{}' shutdown by signal").format(extension_id))

        if not cleaned_up:
            try:
                cleanup_fn = getattr(instance, "cleanup", None)
                if callable(cleanup_fn):
                    clean_res = cleanup_fn()
                    if asyncio.iscoroutine(clean_res):
                        asyncio.run(clean_res)
            except Exception as e:
                log.error(
                    _("Cleanup error in extension '{}': {}").format(extension_id, e)
                )

    except Exception as e:
        tb = traceback.format_exc()
        log.error(
            _("Isolated process crash in extension '{}': {}\n{}").format(
                extension_id, e, tb
            )
        )
        try:
            ipc_conn.send({"status": "crash", "error": str(e), "traceback": tb})
        except Exception:
            pass
