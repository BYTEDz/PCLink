# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import json
import logging
import os
import shutil
import tempfile
import threading
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Body, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from ...core.config import config_manager
from ...core.extension_base import DANGEROUS_PERMISSIONS, ExtensionMetadata
from ...core.extension_context import ExtensionContext
from ...core.extension_db import extension_db
from ...core.extension_manager import ExtensionManager
from ...core.utils import resource_path

log = logging.getLogger(__name__)

extension_manager = ExtensionManager()

mgmt_router = APIRouter(tags=["extension-management"])
runtime_router = APIRouter(tags=["extension-runtime"])

IMPLICIT_FRAMEWORK_FEATURES = {"theme", "theme.read"}


def _sanitize_permission_list(perms: List[Any]) -> List[str]:
    return [
        str(p).strip()
        for p in perms
        if str(p).strip().lower() not in IMPLICIT_FRAMEWORK_FEATURES
    ]


def _ensure_extensions_enabled() -> None:
    if not config_manager.get("allow_extensions", False):
        raise HTTPException(
            status_code=403, detail="Extension system is globally disabled."
        )


def _resolve_extension_path_and_manifest(
    extension_id: str,
) -> Tuple[Optional[Path], Optional[dict]]:
    clean_id = urllib.parse.unquote(extension_id)
    ext_dir = extension_manager._resolve_extension_dir(clean_id)
    if not ext_dir:
        ext_dir = (extension_manager.extensions_path / clean_id).resolve()
    manifest = extension_manager.get_manifest(clean_id)
    return ext_dir, manifest


@mgmt_router.get("")
@mgmt_router.get("/")
async def list_extensions():
    enabled_globally = config_manager.get("allow_extensions", False)
    discovered = extension_manager.discover_extensions()
    db_states = extension_db.get_all_states()
    all_exts = []

    for eid in discovered:
        try:
            meta = extension_manager.get_manifest(eid)
            if not meta:
                continue

            canonical_id = meta.get("id", eid)
            state = db_states.get(canonical_id) or {}

            is_active = extension_manager.is_extension_active(canonical_id)
            response_meta = meta.copy()
            response_meta["id"] = canonical_id
            response_meta["is_loaded"] = is_active

            response_meta["enabled"] = state.get("enabled", True)
            response_meta["quarantined"] = state.get("quarantined", False)
            response_meta["quarantine_reason"] = state.get("quarantine_reason")
            response_meta["crash_count"] = state.get("crash_count", 0)

            telemetry = extension_manager.get_extension_telemetry(canonical_id)
            response_meta["pid"] = telemetry.get("pid")
            response_meta["cpu_percent"] = telemetry.get("cpu_percent", 0.0)
            response_meta["memory_mb"] = telemetry.get("memory_mb", 0.0)

            declared_perms = _sanitize_permission_list(
                response_meta.get(
                    "declared_permissions", response_meta.get("permissions", [])
                )
            )
            granted_perms = _sanitize_permission_list(
                state.get("granted_permissions", response_meta.get("permissions", []))
            )

            response_meta["declared_permissions"] = declared_perms
            response_meta["permissions"] = granted_perms
            response_meta["has_dangerous_perms"] = any(
                p in DANGEROUS_PERMISSIONS for p in declared_perms
            )
            response_meta["user_approved"] = (
                not state.get("quarantined", False)
                and state.get("quarantine_reason") != "SECURITY_CONSENT_REQUIRED"
            )

            contributes = response_meta.get("contributes", {})
            response_meta["dashboard_widgets"] = contributes.get(
                "dashboard_widgets", []
            )
            response_meta["views"] = contributes.get("views", [])

            all_exts.append(response_meta)
        except Exception as e:
            log.error(f"Error processing extension '{eid}': {e}", exc_info=True)

    return {"extensions_enabled": enabled_globally, "extensions": all_exts}


@mgmt_router.post("/install")
async def install_extension(file: UploadFile = File(...)):
    _ensure_extensions_enabled()
    if not file.filename.lower().endswith(".pclink"):
        raise HTTPException(400, "Only .pclink extension packages are allowed")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pclink") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_p = Path(tmp.name)

    try:
        if extension_manager.install_extension(tmp_p):
            return {"status": "success"}
        raise HTTPException(400, "Installation failed")
    except PermissionError as e:
        raise HTTPException(403, str(e))
    finally:
        if tmp_p.exists():
            os.unlink(tmp_p)


@mgmt_router.post("/install/url")
async def install_extension_from_url(url: str = Query(...)):
    _ensure_extensions_enabled()
    if not url.startswith("http"):
        raise HTTPException(400, "Invalid URL")

    task_id = f"url-{abs(hash(url))}"
    extension_manager.install_states[task_id] = {
        "status": "downloading",
        "progress": 0,
        "error": None,
    }

    def download_and_install():
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pclink") as tmp:
            tmp_p = Path(tmp.name)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "PCLink-Server"})
            with urllib.request.urlopen(req, timeout=30) as response:
                content_length = response.headers.get("content-length")
                total_bytes = int(content_length) if content_length else None
                downloaded = 0

                with open(tmp_p, "wb") as out_file:
                    while True:
                        chunk = response.read(8192)
                        if not chunk:
                            break
                        out_file.write(chunk)
                        downloaded += len(chunk)
                        if total_bytes:
                            percent = int((downloaded / total_bytes) * 100)
                            extension_manager.install_states[task_id] = {
                                "status": "downloading",
                                "progress": min(percent, 99),
                                "error": None,
                            }

            if not extension_manager.install_extension(tmp_p, task_id=task_id):
                extension_manager.install_states[task_id] = {
                    "status": "failed",
                    "progress": 0,
                    "error": "Install failed",
                }
        except Exception as e:
            extension_manager.install_states[task_id] = {
                "status": "failed",
                "progress": 0,
                "error": str(e),
            }
        finally:
            if tmp_p.exists():
                try:
                    os.unlink(tmp_p)
                except OSError:
                    pass

    threading.Thread(target=download_and_install, name=f"downloader-{task_id}").start()
    return {"status": "success", "task_id": task_id}


@mgmt_router.delete("/{extension_id}")
async def delete_extension(extension_id: str):
    _ensure_extensions_enabled()
    clean_id = urllib.parse.unquote(extension_id)
    try:
        if extension_manager.delete_extension(clean_id):
            return {"status": "success"}
        raise HTTPException(500, "Delete failed")
    except PermissionError as e:
        raise HTTPException(403, str(e))


@mgmt_router.post("/{extension_id}/toggle")
async def toggle_extension(extension_id: str, enabled: bool):
    _ensure_extensions_enabled()
    clean_id = urllib.parse.unquote(extension_id)
    try:
        if extension_manager.toggle_extension(clean_id, enabled):
            return {"status": "success"}
        raise HTTPException(500, "Toggle failed")
    except PermissionError as e:
        raise HTTPException(403, str(e))


@mgmt_router.post("/{extension_id}/approve")
async def approve_extension_consent(
    extension_id: str, data: Optional[Dict[str, Any]] = Body(None)
):
    _ensure_extensions_enabled()
    clean_id = urllib.parse.unquote(extension_id)
    selected_perms = data.get("permissions") if data else None

    if extension_manager.approve_extension(
        clean_id, tailored_permissions=selected_perms
    ):
        state = extension_db.get_state(clean_id) or {}
        return {
            "status": "success",
            "approved": True,
            "permissions": state.get("granted_permissions", []),
        }

    raise HTTPException(500, "Failed to approve extension")


@mgmt_router.post("/{extension_id}/permissions")
async def update_granular_permissions(
    extension_id: str, data: Dict[str, Any] = Body(...)
):
    _ensure_extensions_enabled()
    clean_id = urllib.parse.unquote(extension_id)
    new_perms = data.get("permissions")
    if new_perms is None or not isinstance(new_perms, list):
        raise HTTPException(400, "A valid list of permissions is required")

    manifest_data = extension_manager.get_manifest(clean_id) or {}
    declared = set(
        manifest_data.get("declared_permissions", manifest_data.get("permissions", []))
    )

    sanitized_perms = [
        str(p).strip()
        for p in new_perms
        if (str(p).strip() in declared or not declared)
        and str(p).strip().lower() not in IMPLICIT_FRAMEWORK_FEATURES
    ]

    extension_db.set_granted_permissions(clean_id, sanitized_perms)

    if extension_manager.is_extension_active(clean_id):
        extension_manager.unload_extension(clean_id)
        extension_manager.load_extension(clean_id)

    return {
        "status": "success",
        "permissions": sanitized_perms,
        "declared_permissions": list(declared),
    }


@mgmt_router.get("/{extension_id}/logs")
async def get_logs(extension_id: str):
    clean_id = urllib.parse.unquote(extension_id)
    return {
        "id": clean_id,
        "logs": extension_manager.get_extension_logs(clean_id),
    }


@mgmt_router.delete("/{extension_id}/logs")
async def clear_logs(extension_id: str):
    clean_id = urllib.parse.unquote(extension_id)
    extension_manager.clear_extension_logs(clean_id)
    return {"status": "success"}


@runtime_router.get("/sdk/pclink-sdk.js")
async def get_pclink_sdk():
    sdk_path = resource_path("src/pclink/web_ui/static/pclink-sdk.js")
    if not sdk_path.exists():
        raise HTTPException(404, "SDK file missing")
    return FileResponse(sdk_path, media_type="application/javascript")


@runtime_router.get("/{extension_id}/ui")
async def get_ui(
    extension_id: str,
    view_id: Optional[str] = None,
    token: Optional[str] = Query(None),
):
    ext_dir, manifest = _resolve_extension_path_and_manifest(extension_id)
    if not manifest or not ext_dir:
        raise HTTPException(404, "Extension manifest not found")

    ui_entry = "index.html"
    contributes = manifest.get("contributes", {})
    views = contributes.get("views", [])

    if view_id and views:
        target_view = next((v for v in views if v.get("id") == view_id), None)
        if target_view and target_view.get("entry_point"):
            ui_entry = target_view["entry_point"]
    elif views and views[0].get("entry_point"):
        ui_entry = views[0]["entry_point"]
    elif manifest.get("ui_entry"):
        ui_entry = manifest.get("ui_entry")

    ui_p = (ext_dir / ui_entry).resolve()
    if not ui_p.is_relative_to(ext_dir.resolve()) or not ui_p.exists():
        raise HTTPException(404, "UI entry file missing")

    res = FileResponse(ui_p, media_type="text/html")
    res.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    if token:
        res.set_cookie(
            "pclink_device_token",
            token,
            max_age=86400,
            httponly=False,
            samesite="lax",
            path="/",
        )
    return res


@runtime_router.get("/{extension_id}/widget/{widget_id}")
async def get_widget_ui(
    extension_id: str,
    widget_id: str,
    token: Optional[str] = Query(None),
):
    ext_dir, manifest = _resolve_extension_path_and_manifest(extension_id)
    if not manifest or not ext_dir:
        raise HTTPException(404, "Extension not found")

    contributes = manifest.get("contributes", {})
    widgets = contributes.get("dashboard_widgets", [])
    widget = next((w for w in widgets if w.get("id") == widget_id), None)

    candidate_files = []
    if widget:
        if widget.get("entry_point"):
            candidate_files.append(widget["entry_point"])
        if widget.get("ui_entry"):
            candidate_files.append(widget["ui_entry"])

    candidate_files.extend(["templates/widget.html", "widget.html"])

    views = contributes.get("views", [])
    if views and views[0].get("entry_point"):
        candidate_files.append(views[0]["entry_point"])
    candidate_files.extend(["templates/index.html", "index.html"])

    resolved_path = None
    for rel_path in candidate_files:
        candidate = (ext_dir / rel_path).resolve()
        if candidate.is_relative_to(ext_dir.resolve()) and candidate.is_file():
            resolved_path = candidate
            break

    if not resolved_path:
        raise HTTPException(
            404, f"Widget view '{widget_id}' could not be resolved on disk"
        )

    res = FileResponse(resolved_path, media_type="text/html")
    res.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    if token:
        res.set_cookie(
            "pclink_device_token",
            token,
            max_age=86400,
            httponly=False,
            samesite="lax",
            path="/",
        )
    return res


@runtime_router.get("/{extension_id}/icon")
@mgmt_router.get("/{extension_id}/icon")
async def get_icon(extension_id: str):
    ext_dir, manifest = _resolve_extension_path_and_manifest(extension_id)
    icon_rel = manifest.get("icon") if manifest else None
    if not icon_rel:
        raise HTTPException(404, "No icon specified in extension manifest")

    icon_p = (ext_dir / icon_rel).resolve()
    if not icon_p.is_relative_to(ext_dir.resolve()) or not icon_p.exists():
        raise HTTPException(404, "Icon file not found")

    return FileResponse(icon_p)


@runtime_router.post("/{extension_id}/broker/{domain}/{method}")
async def broker_rpc_gateway(
    extension_id: str, domain: str, method: str, request: Request
):
    clean_id = urllib.parse.unquote(extension_id)
    manifest_data = extension_manager.get_manifest(clean_id)
    if not manifest_data:
        raise HTTPException(404, f"Extension '{clean_id}' not found")

    state = extension_db.get_state(clean_id) or {}
    effective_permissions = state.get(
        "granted_permissions", manifest_data.get("permissions", [])
    )

    metadata_dict = manifest_data.copy()
    metadata_dict["permissions"] = effective_permissions

    metadata = ExtensionMetadata(**metadata_dict)
    context = ExtensionContext(metadata)

    try:
        body = await request.json()
    except Exception:
        body = {}

    body_summary = json.dumps(body) if body else ""
    log_msg = f"[EXTENSION BROKER: {clean_id}] -> {domain}.{method}({body_summary})"
    log.info(log_msg)
    extension_manager.record_extension_log(
        clean_id, f"Broker request: {domain}.{method} {body_summary}".strip()
    )

    try:
        if domain == "event":
            context.publish_event(method, body)
            return {"success": True, "event": method}
        elif domain == "system" and method == "exec":
            return context.exec.run(
                command=body.get("command", ""),
                timeout=body.get("timeout", 15),
                cwd=body.get("cwd"),
            )
        elif domain == "fs":
            if method == "readText":
                return {"content": context.fs.read_text(body.get("path", ""))}
            elif method == "writeText":
                return {
                    "success": context.fs.write_text(
                        body.get("path", ""), body.get("content", "")
                    )
                }
            elif method == "listDir":
                return {"items": context.fs.list_dir(body.get("path", "."))}
        elif domain == "fetch" and method == "request":
            return context.fetch.request(
                url=body.get("url", ""),
                method=body.get("method", "GET"),
                headers=body.get("headers"),
                body=body.get("body"),
                timeout=body.get("timeout", 10),
            )
        elif domain == "storage":
            if method == "get":
                return {
                    "value": context.storage.get(
                        body.get("key", ""), body.get("default")
                    )
                }
            elif method == "set":
                return {
                    "success": context.storage.set(
                        body.get("key", ""), body.get("value")
                    )
                }
        elif domain == "input":
            if method == "mouseMove":
                context.input.mouse_move(body.get("dx", 0), body.get("dy", 0))
            elif method == "mouseClick":
                context.input.mouse_click(
                    body.get("button", "left"), body.get("clicks", 1)
                )
            elif method == "pressKey":
                context.input.keyboard_press_key(
                    body.get("keyStr", ""), body.get("modifiers", [])
                )
            return {"success": True}
        elif domain == "media":
            if method == "getState":
                return await context.media.get_state()
            elif method == "command":
                action = body.get("action", "")
                await context.media.command(action)
                return {"success": True, "action": action}
        elif domain == "power" and method == "execute":
            await context.power.execute(body.get("action", ""))
            return {"success": True}
        elif domain == "notifications" and method == "show":
            return {
                "success": context.notification.show(
                    body.get("title", ""),
                    body.get("message", ""),
                    body.get("type", "info"),
                )
            }

        raise HTTPException(400, f"Unsupported broker method '{domain}.{method}'")

    except PermissionError as e:
        log.warning(f"Broker permission denied for '{clean_id}': {e}")
        extension_manager.record_extension_log(
            clean_id, f"Permission denied for {domain}.{method}: {e}", level="WARNING"
        )
        raise HTTPException(403, str(e))
    except Exception as e:
        log.error(
            f"Broker execution failed for '{clean_id}' ({domain}.{method}): {e}",
            exc_info=True,
        )
        extension_manager.record_extension_log(
            clean_id, f"Error in {domain}.{method}: {e}", level="ERROR"
        )
        raise HTTPException(500, str(e))


@runtime_router.api_route(
    "/{extension_id}/{subpath:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
)
async def proxy_isolated_extension_http(
    extension_id: str, subpath: str, request: Request
):
    clean_id = urllib.parse.unquote(extension_id)
    ext_dir = extension_manager._resolve_extension_dir(clean_id)
    target_id = ext_dir.name if ext_dir else clean_id

    if not extension_manager.is_extension_active(target_id):
        raise HTTPException(
            status_code=404,
            detail=f"Extension '{clean_id}' is not active",
        )

    body = None
    try:
        body = await request.json()
    except Exception:
        pass

    subpath_clean = "/" + subpath.lstrip("/")
    extension_manager.record_extension_log(
        target_id, f"HTTP {request.method} {subpath_clean}"
    )

    res = extension_manager.dispatch_ipc_http_request(
        extension_id=target_id,
        method=request.method,
        subpath=subpath_clean,
        body=body,
    )

    if not res:
        raise HTTPException(
            status_code=502, detail="Isolated extension process did not respond"
        )

    status_code = res.get("status_code", 200)
    content = res.get("content") or {"error": res.get("error")}
    return JSONResponse(content=content, status_code=status_code)
