# src/pclink/api_server/routers/phone_files.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import logging
import os
import posixpath
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from typing import List, Optional, Tuple
from urllib.parse import quote, unquote

import anyio
import requests
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from starlette.background import BackgroundTask

from ...core.device_manager import device_manager

log = logging.getLogger(__name__)
router = APIRouter()

_MAX_ZIP_ENTRIES = 5000
_MAX_ZIP_SOURCES = 500


def _webdav_url(phone_ip: str, path: str) -> str:
    return f"http://{phone_ip}:38081/{quote(path.lstrip('/'), safe='/')}"


def get_active_phone_details(
    target_device_id: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Finds the IP, ID, and API Key of the target device or the first active ONLINE approved device.
    """
    try:
        from ..ws_manager import mobile_manager

        devices = device_manager.get_all_devices()
        approved = [d for d in devices if d.is_approved and d.current_ip]

        # 1. Target device explicitly requested
        if target_device_id:
            for d in approved:
                dev_id = getattr(d, "device_id", None) or getattr(d, "id", None)
                if dev_id == target_device_id:
                    return d.current_ip, dev_id, getattr(d, "api_key", None)

        # 2. Prioritize devices currently connected online via WebSocket
        for d in approved:
            dev_id = getattr(d, "device_id", None) or getattr(d, "id", None)
            if dev_id and dev_id in mobile_manager.device_connections:
                return d.current_ip, dev_id, getattr(d, "api_key", None)

        # 3. Fallback to first approved device if none are active
        if approved:
            d = approved[0]
            dev_id = getattr(d, "device_id", None) or getattr(d, "id", None)
            return d.current_ip, dev_id, getattr(d, "api_key", None)

        return None, None, None
    except Exception as e:
        log.error(f"Error getting phone details: {e}")
        return None, None, None


def _webdav_auth(device_id: Optional[str]) -> Tuple[str, str]:
    return ("pclink", device_id or "")


def _webdav_headers(api_key: Optional[str], depth: Optional[str] = None) -> dict:
    headers = {}
    if api_key:
        headers["x-pclink-token"] = api_key
    if depth:
        headers["Depth"] = depth
    return headers


def _clean_phone_path(path: str) -> str:
    """Normalize a WebDAV path and reject traversal attempts."""
    path = path.strip()
    if not path.startswith("/"):
        path = "/" + path
    parts = [part for part in path.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise HTTPException(status_code=400, detail="Invalid file path")
    return "/" + "/".join(parts)


def _safe_archive_name(name: str) -> str:
    """Strip traversal components from a name before using it inside a zip."""
    parts = [
        part
        for part in str(name).replace("\\", "/").split("/")
        if part not in ("", ".", "..")
    ]
    return "/".join(parts)


def _phone_propfind(
    phone_ip: str,
    device_id: Optional[str],
    api_key: Optional[str],
    path: str,
) -> List[dict]:
    """Return the direct children of a WebDAV collection."""
    url = _webdav_url(phone_ip, path)
    try:
        resp = requests.request(
            "PROPFIND",
            url,
            headers=_webdav_headers(api_key, "1"),
            auth=_webdav_auth(device_id),
            timeout=20,
        )
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502, detail=f"Could not reach phone storage: {exc}"
        )

    if resp.status_code != 207:
        raise HTTPException(
            status_code=502,
            detail=f"Phone storage returned HTTP {resp.status_code}",
        )

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as exc:
        raise HTTPException(status_code=502, detail=f"Invalid WebDAV response: {exc}")

    ns = {"D": "DAV:"}
    normalized_dir = path.rstrip("/") or "/"
    items: List[dict] = []

    for response in root.findall("D:response", ns):
        href_el = response.find("D:href", ns)
        prop = response.find("D:propstat/D:prop", ns)
        if href_el is None or prop is None:
            continue

        href = unquote(href_el.text or "")
        displayname_el = prop.find("D:displayname", ns)
        name = (
            displayname_el.text
            if displayname_el is not None and displayname_el.text
            else href.rstrip("/").split("/")[-1]
        )
        resourcetype = prop.find("D:resourcetype", ns)
        is_dir = (
            resourcetype is not None
            and resourcetype.find("D:collection", ns) is not None
        )

        clean_path = href
        if not clean_path.endswith("/") and is_dir:
            clean_path += "/"
        if (clean_path.rstrip("/") or "/") == normalized_dir:
            continue

        items.append(
            {
                "name": unquote(name),
                "path": clean_path if is_dir else clean_path.rstrip("/"),
                "isDir": is_dir,
            }
        )

    return items


def _build_zip_from_phone(
    phone_ip: str,
    device_id: Optional[str],
    api_key: Optional[str],
    selected_paths: List[str],
) -> Tuple[str, int]:
    """Download the selected WebDAV resources and package them into a zip file."""
    target = tempfile.NamedTemporaryFile(
        prefix="pclink-phone-", suffix=".zip", delete=False
    )
    target.close()

    auth = _webdav_auth(device_id)
    count = 0
    used_names = set()

    try:
        with zipfile.ZipFile(
            target.name, "w", zipfile.ZIP_DEFLATED, allowZip64=True
        ) as archive:

            def unique_name(name: str) -> str:
                candidate = name or "file"
                if candidate not in used_names:
                    used_names.add(candidate)
                    return candidate
                base, ext = posixpath.splitext(candidate)
                index = 2
                while f"{base} ({index}){ext}" in used_names:
                    index += 1
                candidate = f"{base} ({index}){ext}"
                used_names.add(candidate)
                return candidate

            def add_file(path: str, arcname: str) -> None:
                nonlocal count
                if count >= _MAX_ZIP_ENTRIES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Too many files to archive (limit {_MAX_ZIP_ENTRIES})",
                    )
                url = _webdav_url(phone_ip, path)
                try:
                    resp = requests.get(
                        url,
                        headers=_webdav_headers(api_key),
                        auth=auth,
                        stream=True,
                        timeout=60,
                    )
                except requests.RequestException as exc:
                    raise HTTPException(
                        status_code=502, detail=f"Could not download {path}: {exc}"
                    )

                with resp:
                    if resp.status_code >= 400:
                        raise HTTPException(
                            status_code=502,
                            detail=(
                                f"Phone storage returned HTTP {resp.status_code} "
                                f"for {path}"
                            ),
                        )
                    with archive.open(unique_name(arcname), "w") as dest:
                        for chunk in resp.iter_content(chunk_size=65536):
                            if chunk:
                                dest.write(chunk)
                count += 1

            def add_directory(path: str, arc_prefix: str) -> None:
                nonlocal count
                children = _phone_propfind(phone_ip, device_id, api_key, path)
                if not children and arc_prefix:
                    archive.writestr(arc_prefix, b"")
                    count += 1
                    return
                for item in children:
                    safe_child = _safe_archive_name(item["name"])
                    if not safe_child:
                        continue
                    archive_path = posixpath.join(arc_prefix, safe_child)
                    if item["isDir"]:
                        add_directory(item["path"], archive_path + "/")
                    else:
                        add_file(item["path"], archive_path)

            for selected in selected_paths[:_MAX_ZIP_SOURCES]:
                clean = _clean_phone_path(selected)
                base_name = (
                    _safe_archive_name(posixpath.basename(clean.rstrip("/")))
                    or "phone-files"
                )
                # The browser marks collections with a trailing slash.
                is_dir = selected.rstrip().endswith("/")

                if is_dir:
                    add_directory(clean + "/", base_name + "/")
                else:
                    add_file(clean, base_name)

        return target.name, count
    except Exception:
        try:
            os.unlink(target.name)
        except OSError:
            pass
        raise


def _remove_file(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


@router.api_route("/.zip-download", methods=["GET", "POST"])
async def download_phone_zip(request: Request):
    """Proxy a multi-file selection from the phone and return it as one zip."""
    device_id: Optional[str] = None
    name: Optional[str] = None
    paths: List[str] = []

    if request.method == "POST":
        try:
            form = await request.form()
            paths = [str(value) for value in form.getlist("paths")]
            device_id = str(form.get("device_id") or "") or None
            name = str(form.get("name") or "") or None
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid form data: {exc}")
    else:
        paths = request.query_params.getlist("paths")
        device_id = request.query_params.get("device_id")
        name = request.query_params.get("name")

    if not paths:
        raise HTTPException(status_code=400, detail="No files were selected")
    if len(paths) > _MAX_ZIP_SOURCES:
        raise HTTPException(
            status_code=413,
            detail=f"Too many selected items (limit {_MAX_ZIP_SOURCES})",
        )

    phone_ip, resolved_device_id, api_key = get_active_phone_details(device_id)
    if not phone_ip:
        raise HTTPException(status_code=404, detail="No active phone connected")

    safe_name = re.sub(r"[^\w.\- ]+", "_", (name or "phone-files").strip())
    safe_name = (safe_name or "phone-files").strip(". ") or "phone-files"
    if not safe_name.lower().endswith(".zip"):
        safe_name += ".zip"

    try:
        zip_path, file_count = await anyio.to_thread.run_sync(
            _build_zip_from_phone,
            phone_ip,
            resolved_device_id,
            api_key,
            paths,
        )
    except HTTPException:
        raise
    except Exception as exc:
        log.error(f"Failed to build phone zip: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to build archive")

    if file_count == 0:
        _remove_file(zip_path)
        raise HTTPException(
            status_code=404, detail="No downloadable files found in the selection"
        )

    log.info(
        f"Streaming zip archive with {file_count} file(s) from device {resolved_device_id}"
    )
    return FileResponse(
        zip_path,
        filename=safe_name,
        media_type="application/zip",
        background=BackgroundTask(_remove_file, zip_path),
    )


@router.api_route(
    "/{path:path}",
    methods=[
        "GET",
        "POST",
        "PUT",
        "DELETE",
        "PROPFIND",
        "OPTIONS",
        "MKCOL",
        "MOVE",
        "COPY",
    ],
)
async def proxy_webdav(request: Request, path: str):
    """Proxies WebDAV requests to the phone's WebDAV server."""
    target_device_id = request.query_params.get("device_id")
    phone_ip, device_id, api_key = get_active_phone_details(target_device_id)

    if not phone_ip:
        log.warning("Proxy failed: No active phone connected")
        raise HTTPException(status_code=404, detail="No active phone connected")

    is_browse = False
    actual_path = path
    method = request.method

    if path.startswith(".browse"):
        is_browse = True
        actual_path = path[7:]
        if not actual_path.startswith("/"):
            actual_path = "/" + actual_path
        method = "PROPFIND"

    url = _webdav_url(phone_ip, actual_path)
    log.info(f"Proxying WebDAV: {method} {url} (DeviceID={device_id})")

    auth = ("pclink", device_id)

    excluded_request_headers = {"host", "content-length", "authorization", "connection"}
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in excluded_request_headers
    }

    if is_browse:
        headers["Depth"] = request.headers.get("Depth", "1")

    if api_key:
        headers["x-pclink-token"] = api_key

    if method in ("MOVE", "COPY"):
        destination = headers.pop("destination", None)
        if destination and destination.startswith("/"):
            headers["Destination"] = f"http://{phone_ip}:38081{destination}"
        headers["Overwrite"] = headers.pop("overwrite", "F")

    body = await request.body()

    try:
        max_retries = 3
        current_timeout = 60.0 if method == "PUT" else 20.0

        def make_request():
            return requests.request(
                method=method,
                url=url,
                headers=headers,
                data=body,
                params={
                    k: v for k, v in request.query_params.items() if k != "device_id"
                },
                auth=auth,
                stream=True,
                timeout=current_timeout,
            )

        resp = None
        for attempt in range(max_retries):
            try:
                resp = await anyio.to_thread.run_sync(make_request)
                break
            except (requests.ConnectionError, requests.Timeout) as e:
                log.warning(f"WebDAV proxy attempt {attempt + 1} failed ({e})")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1.0)
                    continue
                raise

        if resp is None:
            raise HTTPException(
                status_code=502, detail="No response received from phone"
            )

        if is_browse and resp.status_code == 207:
            try:
                items = []
                root = ET.fromstring(resp.content)
                ns = {"D": "DAV:"}

                for response in root.findall("D:response", ns):
                    href_el = response.find("D:href", ns)
                    if href_el is None:
                        continue
                    href = href_el.text

                    prop = response.find("D:propstat/D:prop", ns)
                    if prop is None:
                        continue

                    displayname_el = prop.find("D:displayname", ns)
                    name = (
                        displayname_el.text
                        if (displayname_el is not None and displayname_el.text)
                        else href.rstrip("/").split("/")[-1]
                    )

                    resourcetype = prop.find("D:resourcetype", ns)
                    is_dir = (
                        resourcetype is not None
                        and resourcetype.find("D:collection", ns) is not None
                    )

                    size_el = prop.find("D:getcontentlength", ns)
                    size = int(size_el.text) if size_el is not None else 0

                    modified_el = prop.find("D:getlastmodified", ns)
                    modified = modified_el.text if modified_el is not None else ""

                    clean_path = unquote(href)

                    items.append(
                        {
                            "name": unquote(name),
                            "path": clean_path,
                            "isDir": is_dir,
                            "size": size,
                            "modified": modified,
                        }
                    )

                normalized_actual = actual_path.rstrip("/")
                if not normalized_actual:
                    normalized_actual = "/"

                final_items = [
                    it
                    for it in items
                    if unquote(it["path"]).rstrip("/") != normalized_actual
                ]

                return {"items": final_items, "path": actual_path}
            except Exception as e:
                log.error(f"Failed to parse WebDAV XML: {e}")

        excluded_response_headers = {
            "content-encoding",
            "content-length",
            "transfer-encoding",
            "connection",
        }
        resp_headers = {
            k: v
            for k, v in resp.headers.items()
            if k.lower() not in excluded_response_headers
        }

        if resp.status_code >= 400:
            log.warning(
                f"Phone responded with error {resp.status_code}: {resp.text[:200]}"
            )

        if method == "GET" and resp.status_code < 400:

            def generate():
                try:
                    for chunk in resp.iter_content(chunk_size=8192):
                        yield chunk
                finally:
                    resp.close()

            return StreamingResponse(
                generate(), status_code=resp.status_code, headers=resp_headers
            )

        try:
            return Response(
                content=resp.content, status_code=resp.status_code, headers=resp_headers
            )
        finally:
            resp.close()

    except HTTPException:
        raise
    except requests.RequestException as e:
        log.error(f"Failed to proxy WebDAV request to {url}: {e}")
        raise HTTPException(
            status_code=502, detail=f"Failed to communicate with phone: {str(e)}"
        )
    except Exception as e:
        log.error(f"Unexpected error in proxy_webdav: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")
