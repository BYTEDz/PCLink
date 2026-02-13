import logging
import asyncio
import anyio
import requests
from typing import Optional, Tuple
from fastapi import APIRouter, Request, Response, HTTPException
from fastapi.responses import StreamingResponse
from ..core.device_manager import device_manager

log = logging.getLogger(__name__)
router = APIRouter()

def get_active_phone_details() -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Finds the IP, ID, and API Key of the first approved device."""
    try:
        devices = device_manager.get_all_devices()
        for d in devices:
            if d.is_approved and d.current_ip:
                # Use robust attribute access
                dev_id = getattr(d, 'device_id', None) or getattr(d, 'id', None)
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
    phone_ip, device_id, api_key = get_active_phone_details()
    
    if not phone_ip:
        log.warning("Proxy failed: No active phone connected")
        raise HTTPException(status_code=404, detail="No active phone connected")
        
    url = f"http://{phone_ip}:38081/{path}"
    method = request.method
    log.info(f"Proxying WebDAV: {method} {url} (DeviceID={device_id})")
    
    # Proper WebDAV Auth: Basic Auth using (pclink / device_id)
    auth = ("pclink", device_id)
    
    # Clean up headers to avoid conflicts
    excluded_request_headers = {"host", "content-length", "authorization", "connection"}
    headers = {k: v for k, v in request.headers.items() if k.lower() not in excluded_request_headers}

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
                params=request.query_params,
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
                if attempt < max_retries - 1:
                    log.warning(f"WebDAV proxy attempt {attempt + 1} failed ({e})")
                    
                    # Try to wake up WebDAV service on the phone via WebSocket
                    if attempt == 0:
                        try:
                            mobile_manager = request.app.state.mobile_manager
                            if mobile_manager:
                                log.info(f"Attempting to wake up WebDAV on device {device_id}...")
                                await mobile_manager.send_to_device(device_id, {
                                    "type": "webdav_control",
                                    "data": {"action": "start"}
                                })
                                # Give it slightly more time to start up
                                await asyncio.sleep(2.0)
                                continue
                        except Exception as wake_err:
                            log.warning(f"Failed to send wakeup signal: {wake_err}")
                            
                    await asyncio.sleep(1.0) # Non-blocking sleep
                    continue
                raise
        
        if not resp:
            raise HTTPException(status_code=502, detail="Failed to receive response from phone")

        # Exclude hop-by-hop headers from response
        excluded_response_headers = {"content-encoding", "content-length", "transfer-encoding", "connection"}
        resp_headers = {k: v for k, v in resp.headers.items() if k.lower() not in excluded_response_headers}
        
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

    except requests.RequestException as e:
        log.error(f"Failed to proxy WebDAV request to {url}: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to communicate with phone. Error: {str(e)}")
    except Exception as e:
        log.error(f"Unexpected error in proxy_webdav: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")
