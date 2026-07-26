# src/pclink/core/extension_runner.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

"""
Isolated Extension Process Worker.
Executes extension initialization, lifecycle tasks, and route handlers in
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
    Traps exceptions, serves route execution requests via IPC, and prevents host crashes.
    """
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
                    "error": f"Entry file missing: {module_path.name}",
                }
            )
            return

        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if not spec or not spec.loader:
            ipc_conn.send({"status": "error", "error": "Failed to create module spec"})
            return

        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)

        cls = getattr(mod, class_name, None)
        if not cls:
            ipc_conn.send(
                {
                    "status": "error",
                    "error": f"Class '{class_name}' not found in {module_path.name}",
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

        # 4. Extract registered routes from extension APIRouter
        route_handlers: Dict[tuple, Any] = {}
        router = instance.get_routes()
        for r in router.routes:
            methods = getattr(r, "methods", {"GET"})
            path = getattr(r, "path", "/")
            for m in methods:
                route_handlers[(m.upper(), path)] = r.endpoint

        # 5. Initialize extension
        init_res = instance.initialize()
        if asyncio.iscoroutine(init_res):
            init_res = asyncio.run(init_res)

        if init_res is False:
            ipc_conn.send(
                {
                    "status": "error",
                    "error": f"Extension '{extension_id}' initialize() returned False",
                }
            )
            return

        # Signal successful initialization to host process
        ipc_conn.send({"status": "ready", "pid": os.getpid()})

        # 6. Enter IPC Command & HTTP Route Dispatcher Loop
        while True:
            if not ipc_conn.poll(0.1):
                continue

            cmd = ipc_conn.recv()
            cmd_type = cmd.get("type")

            if cmd_type == "PING":
                ipc_conn.send({"status": "pong", "pid": os.getpid()})

            elif cmd_type == "HTTP_REQUEST":
                req_id = cmd.get("req_id")
                method = cmd.get("method", "GET").upper()
                subpath = cmd.get("subpath", "/")
                if not subpath.startswith("/"):
                    subpath = "/" + subpath

                body_data = cmd.get("body")

                # Match route handler
                handler = route_handlers.get((method, subpath)) or route_handlers.get(
                    ("ANY", subpath)
                )

                if handler:
                    try:
                        sig = inspect.signature(handler)
                        if len(sig.parameters) > 0 and body_data is not None:
                            res = handler(body_data)
                        else:
                            res = handler()

                        if asyncio.iscoroutine(res):
                            res = asyncio.run(res)

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
                            "error": f"Route '{method} {subpath}' not found in worker process",
                        }
                    )

            elif cmd_type == "CLEANUP":
                try:
                    clean_res = instance.cleanup()
                    if asyncio.iscoroutine(clean_res):
                        asyncio.run(clean_res)
                    ipc_conn.send({"status": "cleaned"})
                except Exception as e:
                    ipc_conn.send({"status": "error", "error": str(e)})
                break

            elif cmd_type == "SHUTDOWN":
                break

    except Exception as e:
        tb = traceback.format_exc()
        log.error(f"Isolated process crash in extension '{extension_id}': {e}\n{tb}")
        try:
            ipc_conn.send({"status": "crash", "error": str(e), "traceback": tb})
        except Exception:
            pass
