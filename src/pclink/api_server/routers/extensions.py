# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import gettext
import json
import logging
import os
import shutil
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Body, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from ...core.config import config_manager
from ...core.extension_base import DANGEROUS_PERMISSIONS, ExtensionMetadata
from ...core.extension_context import ExtensionContext
from ...core.extension_manager import ExtensionManager
from ...core.utils import resource_path

log = logging.getLogger(__name__)
_ = gettext.gettext

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


def _ensure_extensions_enabled():
    if not config_manager.get("allow_extensions", False):
        raise HTTPException(
            status_code=403, detail=_("Extension system is globally disabled.")
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
    all_exts = []

    for eid in discovered:
        try:
            meta = extension_manager.get_manifest(eid)
            if not meta:
                continue

            canonical_id = meta.get("id", eid)
            is_loaded = (canonical_id in extension_manager.extensions) or (
                canonical_id in extension_manager.isolated_processes
            )
            response_meta = meta.copy()
            response_meta["id"] = canonical_id
            response_meta["is_loaded"] = is_loaded

            telemetry = extension_manager.get_extension_telemetry(canonical_id)
            response_meta["pid"] = telemetry.get("pid")
            response_meta["cpu_percent"] = telemetry.get("cpu_percent", 0.0)
            response_meta["memory_mb"] = telemetry.get("memory_mb", 0.0)

            raw_perms = response_meta.get("permissions", [])
            clean_perms = _sanitize_permission_list(raw_perms)
            response_meta["permissions"] = clean_perms

            declared = response_meta.get("declared_permissions")
            if declared:
                response_meta["declared_permissions"] = _sanitize_permission_list(
                    declared
                )
            else:
                response_meta["declared_permissions"] = clean_perms

            response_meta["has_dangerous_perms"] = any(
                p in DANGEROUS_PERMISSIONS for p in clean_perms
            )
            response_meta["user_approved"] = not response_meta.get(
                "security_consent_needed", False
            )

            contributes = response_meta.get("contributes", {})
            response_meta["dashboard_widgets"] = contributes.get(
                "dashboard_widgets", []
            )

            all_exts.append(response_meta)
        except Exception as e:
            log.error(f"Error processing extension '{eid}': {e}", exc_info=True)

    return {"extensions_enabled": enabled_globally, "extensions": all_exts}


@mgmt_router.post("/install")
async def install_extension(file: UploadFile = File(...)):
    _ensure_extensions_enabled()
    if not file.filename.endswith(".zip"):
        raise HTTPException(400, _("Only .zip allowed"))

    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_p = Path(tmp.name)

    try:
        if extension_manager.install_extension(tmp_p):
            return {"status": "success"}
        raise HTTPException(400, _("Install failed"))
    except PermissionError as e:
        raise HTTPException(403, str(e))
    finally:
        if tmp_p.exists():
            os.unlink(tmp_p)


@mgmt_router.post("/install/url")
async def install_extension_from_url(url: str = Query(...)):
    _ensure_extensions_enabled()
    if not url.startswith("http"):
        raise HTTPException(400, _("Invalid URL"))

    import threading

    task_id = f"url-{abs(hash(url))}"
    extension_manager.install_states[task_id] = {
        "status": "downloading",
        "progress": 0,
        "error": None,
    }

    def download_and_install():
        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
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
                    "error": _("Install failed"),
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
        raise HTTPException(500, _("Delete failed"))
    except PermissionError as e:
        raise HTTPException(403, str(e))


@mgmt_router.post("/{extension_id}/toggle")
async def toggle_extension(extension_id: str, enabled: bool):
    _ensure_extensions_enabled()
    clean_id = urllib.parse.unquote(extension_id)
    try:
        if extension_manager.toggle_extension(clean_id, enabled):
            return {"status": "success"}
        raise HTTPException(500, _("Toggle failed"))
    except PermissionError as e:
        raise HTTPException(403, str(e))


@mgmt_router.post("/{extension_id}/approve")
async def approve_extension_consent(
    extension_id: str, data: Optional[Dict[str, Any]] = Body(None)
):
    """Grants consent and activates a quarantined extension with optional tailored capabilities."""
    _ensure_extensions_enabled()
    clean_id = urllib.parse.unquote(extension_id)
    ext_dir = extension_manager._resolve_extension_dir(clean_id)
    if not ext_dir:
        raise HTTPException(404, f"Extension '{clean_id}' not found")

    manifest_file = ext_dir / "manifest.json"
    try:
        manifest_data = extension_manager.get_manifest(clean_id) or {}
        declared = manifest_data.get(
            "declared_permissions", manifest_data.get("permissions", [])
        )

        # Allow tailored permissions on approval
        selected_perms = data.get("permissions") if data else None
        if selected_perms is not None and isinstance(selected_perms, list):
            manifest_data["permissions"] = [
                str(p).strip()
                for p in selected_perms
                if str(p).strip() in declared or not declared
            ]
        else:
            manifest_data["permissions"] = list(declared)

        manifest_data["enabled"] = True
        manifest_data["security_consent_needed"] = False

        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2)

        extension_manager._metadata_cache.pop(ext_dir.name, None)
        extension_manager.load_extension(clean_id)

        return {
            "status": "success",
            "approved": True,
            "permissions": manifest_data["permissions"],
        }
    except Exception as e:
        log.error(f"Failed to approve extension '{clean_id}': {e}")
        raise HTTPException(500, str(e))


@mgmt_router.post("/{extension_id}/permissions")
async def update_granular_permissions(
    extension_id: str, data: Dict[str, Any] = Body(...)
):
    _ensure_extensions_enabled()
    clean_id = urllib.parse.unquote(extension_id)
    ext_dir = extension_manager._resolve_extension_dir(clean_id)
    if not ext_dir:
        raise HTTPException(404, f"Extension '{clean_id}' not found")

    new_perms = data.get("permissions")
    if new_perms is None or not isinstance(new_perms, list):
        raise HTTPException(400, "A valid list of permissions is required")

    manifest_file = ext_dir / "manifest.json"
    try:
        manifest_data = extension_manager.get_manifest(clean_id) or {}
        declared = set(
            manifest_data.get(
                "declared_permissions", manifest_data.get("permissions", [])
            )
        )

        sanitized_perms = [
            str(p).strip()
            for p in new_perms
            if (str(p).strip() in declared or not declared)
            and str(p).strip().lower() not in IMPLICIT_FRAMEWORK_FEATURES
        ]
        manifest_data["permissions"] = sanitized_perms

        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2)

        extension_manager._metadata_cache.pop(ext_dir.name, None)

        is_active = (
            extension_manager.get_extension(clean_id) is not None
            or clean_id in extension_manager.isolated_processes
        )
        if is_active:
            extension_manager.unload_extension(clean_id)
            extension_manager.load_extension(clean_id)

        return {
            "status": "success",
            "permissions": manifest_data["permissions"],
            "declared_permissions": list(declared),
        }
    except Exception as e:
        log.error(f"Failed to update permissions for '{clean_id}': {e}")
        raise HTTPException(500, str(e))


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
        raise HTTPException(404, _("SDK file missing"))
    return FileResponse(sdk_path, media_type="application/javascript")


@runtime_router.get("/{extension_id}/ui")
async def get_ui(
    extension_id: str,
    view_id: Optional[str] = None,
    token: Optional[str] = Query(None),
):
    ext_dir, manifest = _resolve_extension_path_and_manifest(extension_id)
    if not manifest or not ext_dir:
        raise HTTPException(404, _("Extension manifest not found"))

    ui_entry = "index.html"
    contributes = manifest.get("contributes", {})
    views = contributes.get("views", [])

    if view_id and views:
        target_view = next((v for v in views if v.get("id") == view_id), None)
        if target_view and target_view.get("entry_point"):
            ui_entry = target_view["entry_point"]
    elif views and views[0].get("entry_point"):
        ui_entry = views[0]["entry_point"]

    ui_p = (ext_dir / ui_entry).resolve()
    if not ui_p.is_relative_to(ext_dir.resolve()) or not ui_p.exists():
        raise HTTPException(404, _("UI entry file missing"))

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
        raise HTTPException(404, _("Extension not found"))

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
        raise HTTPException(404, _("No icon specified in extension manifest"))

    icon_p = (ext_dir / icon_rel).resolve()
    if not icon_p.is_relative_to(ext_dir.resolve()) or not icon_p.exists():
        raise HTTPException(404, _("Icon file not found"))

    return FileResponse(icon_p)


@runtime_router.post("/{extension_id}/broker/{domain}/{method}")
async def broker_rpc_gateway(
    extension_id: str, domain: str, method: str, request: Request
):
    clean_id = urllib.parse.unquote(extension_id)
    manifest_data = extension_manager.get_manifest(clean_id)
    if not manifest_data:
        log.error(f"[BROKER] Extension '{clean_id}' not found")
        raise HTTPException(404, f"Extension '{clean_id}' not found")

    metadata = ExtensionMetadata(**manifest_data)
    context = ExtensionContext(metadata)

    try:
        body = await request.json()
    except Exception:
        body = {}

    log.info(f"[BROKER] Executing {domain}.{method} for '{clean_id}' | Body: {body}")

    try:
        if domain == "system" and method == "exec":
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
        log.warning(f"[BROKER] Permission denied for '{clean_id}': {e}")
        raise HTTPException(403, str(e))
    except Exception as e:
        log.error(
            f"[BROKER] Execution failed for '{clean_id}' ({domain}.{method}): {e}",
            exc_info=True,
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

    if (
        target_id not in extension_manager.isolated_processes
        and clean_id not in extension_manager.isolated_processes
    ):
        raise HTTPException(
            status_code=404,
            detail=_("Extension '{extension_id}' not active").format(
                extension_id=clean_id
            ),
        )

    body = None
    try:
        body = await request.json()
    except Exception:
        pass

    subpath_clean = "/" + subpath.lstrip("/")
    res = extension_manager.dispatch_ipc_http_request(
        extension_id=target_id,
        method=request.method,
        subpath=subpath_clean,
        body=body,
    )

    if not res:
        raise HTTPException(
            status_code=502, detail=_("Isolated extension process did not respond")
        )

    status_code = res.get("status_code", 200)
    content = res.get("content") or {"error": res.get("error")}
    return JSONResponse(content=content, status_code=status_code)
