import logging
import asyncio
import anyio
import requests
import xml.etree.ElementTree as ET
from urllib.parse import unquote
from typing import Optional, Tuple
from fastapi import APIRouter, Request, Response, HTTPException
from fastapi.responses import StreamingResponse
from ..core.device_manager import device_manager

log = logging.getLogger(__name__)
router = APIRouter()

def get_active_phone_details(target_device_id: Optional[str] = None) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Finds the IP, ID, and API Key of the target device or first approved device."""
    try:
        devices = device_manager.get_all_devices()
        for d in devices:
            # attribute access
            dev_id = getattr(d, 'device_id', None) or getattr(d, 'id', None)
            
            # Filter by target ID if provided
            if target_device_id and dev_id != target_device_id:
                continue
                
            if d.is_approved and d.current_ip:
                api_key = getattr(d, 'api_key', None)
                if dev_id:
                     return d.current_ip, dev_id, api_key
        return None, None, None
    except Exception as e:
        log.error(f"Error getting phone details: {e}")
        return None, None, None

@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PROPFIND", "OPTIONS", "MKCOL", "MOVE", "COPY"])
async def proxy_webdav(request: Request, path: str):
    """Proxies WebDAV requests to the phone's WebDAV server."""
    target_device_id = request.query_params.get("device_id")
    phone_ip, device_id, api_key = get_active_phone_details(target_device_id)
    
    if not phone_ip:
        log.warning("Proxy failed: No active phone connected")
        raise HTTPException(status_code=404, detail="No active phone connected")
        
    # Handle the .browse magic path for JSON listing compatibility
    is_browse = False
    actual_path = path
    method = request.method
    
    if path.startswith(".browse"):
        is_browse = True
        actual_path = path[7:] # Remove ".browse" prefix
        if not actual_path.startswith("/"):
            actual_path = "/" + actual_path
        method = "PROPFIND"

    url = f"http://{phone_ip}:38081/{actual_path.lstrip('/')}"
    log.info(f"Proxying WebDAV: {method} {url} (DeviceID={device_id})")
    
    # Proper WebDAV Auth: Basic Auth using (pclink / device_id)
    auth = ("pclink", device_id)
    
    # Clean up headers to avoid conflicts
    excluded_request_headers = {"host", "content-length", "authorization", "connection"}
    headers = {k: v for k, v in request.headers.items() if k.lower() not in excluded_request_headers}

    if is_browse:
        headers["Depth"] = request.headers.get("Depth", "1")

    if api_key:
        headers["x-pclink-token"] = api_key
    
    # Get body if exists
    body = await request.body()
    
    try:
        max_retries = 3
        current_timeout = 60.0 if method == "PUT" else 20.0
        
        # Function to be run in a threadpool to avoid blocking the event loop
        def make_request():
            return requests.request(
                method=method,
                url=url,
                headers=headers,
                data=body,
                params={k: v for k, v in request.query_params.items() if k != "device_id"},
                auth=auth,
                stream=True,
                timeout=current_timeout
            )

        resp = None
        for attempt in range(max_retries):
            try:
                # Run the synchronous request in a worker thread
                resp = await anyio.to_thread.run_sync(make_request)
                break 
            except (requests.ConnectionError, requests.Timeout) as e:
                log.warning(f"WebDAV proxy attempt {attempt + 1} failed ({e})")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1.0) # Non-blocking sleep
                    continue
                raise
        
        if resp is None:
            raise HTTPException(status_code=502, detail="No response received from phone")

        # Handle JSON translation for browsing
        if is_browse and resp.status_code == 207:
            try:
                items = []
                # Simple XML parsing for WebDAV response
                root = ET.fromstring(resp.content)
                ns = {'D': 'DAV:'}
                
                for response in root.findall('D:response', ns):
                    href_el = response.find('D:href', ns)
                    if href_el is None: continue
                    href = href_el.text
                    
                    prop = response.find('D:propstat/D:prop', ns)
                    if prop is None: continue
                    
                    displayname_el = prop.find('D:displayname', ns)
                    name = displayname_el.text if (displayname_el is not None and displayname_el.text) else href.rstrip('/').split('/')[-1]
                    
                    resourcetype = prop.find('D:resourcetype', ns)
                    is_dir = resourcetype is not None and resourcetype.find('D:collection', ns) is not None
                    
                    size_el = prop.find('D:getcontentlength', ns)
                    size = int(size_el.text) if size_el is not None else 0
                    
                    modified_el = prop.find('D:getlastmodified', ns)
                    modified = modified_el.text if modified_el is not None else ""
                    
                    # Store clean path
                    clean_path = unquote(href)
                    
                    items.append({
                        "name": unquote(name),
                        "path": clean_path,
                        "isDir": is_dir,
                        "size": size,
                        "modified": modified
                    })
                
                # Filter out the parent directory itself from results and sort
                # In WebDAV Depth:1 returns the resource itself too
                normalized_actual = actual_path.rstrip('/')
                if not normalized_actual: normalized_actual = "/"
                
                final_items = [it for it in items if unquote(it["path"]).rstrip('/') != normalized_actual]
                
                return {"items": final_items, "path": actual_path}
            except Exception as e:
                log.error(f"Failed to parse WebDAV XML: {e}")
                # Don't fail the whole request if parsing fails, just fallback to raw response
        
        # Exclude hop-by-hop headers from response
        excluded_response_headers = {"content-encoding", "content-length", "transfer-encoding", "connection"}
        resp_headers = {k: v for k, v in resp.headers.items() if k.lower() not in excluded_response_headers}
        
        # Log non-success status for debugging
        if resp.status_code >= 400:
            log.warning(f"Phone responded with error {resp.status_code}: {resp.text[:200]}")

        # StreamingResponse ONLY for GET (file downloads) to maintain efficiency
        if method == "GET" and resp.status_code < 400:
             def generate():
                 try:
                     for chunk in resp.iter_content(chunk_size=8192):
                         yield chunk
                 finally:
                     resp.close()
             return StreamingResponse(generate(), status_code=resp.status_code, headers=resp_headers)
             
        # For other methods, return full content directly
        try:
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                headers=resp_headers
            )
        finally:
            resp.close()

    except HTTPException:
        raise
    except requests.RequestException as e:
        log.error(f"Failed to proxy WebDAV request to {url}: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to communicate with phone. Error: {str(e)}")
    except Exception as e:
        log.error(f"Unexpected error in proxy_webdav: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")

