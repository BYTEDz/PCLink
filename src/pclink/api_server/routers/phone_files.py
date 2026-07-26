# src/pclink/api_server/routers/phone_files.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import logging
import xml.etree.ElementTree as ET
from typing import Optional, Tuple
from urllib.parse import unquote

import anyio
import requests
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from ...core.device_manager import device_manager

log = logging.getLogger(__name__)
router = APIRouter()


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

    url = f"http://{phone_ip}:38081/{actual_path.lstrip('/')}"
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
