# src/pclink/api_server/routers/ai.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 AZHAR ZOUHIR / BYTEDz

import asyncio
import logging
from typing import Optional
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse

from ...services.ai_service import ai_service
from .dependencies import verify_api_key

log = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["AI Engine"])


# ==========================================
# 1. System & Engine Diagnostics
# ==========================================


@router.get("/status", dependencies=[Depends(verify_api_key)])
async def get_ai_status():
    """Returns AI subsystem status, active engine, active model, and execution state."""
    return await ai_service.get_status()


@router.get("/config", dependencies=[Depends(verify_api_key)])
async def get_ai_config():
    """Returns the tunable AI runtime configuration."""
    return ai_service.get_config()


@router.post("/config", dependencies=[Depends(verify_api_key)])
async def update_ai_config(request: Request):
    """Updates context size, GPU offload, port, threads, or idle timeout."""
    body = await request.json()
    return await asyncio.to_thread(ai_service.update_config, body)


@router.get("/engine/versions", dependencies=[Depends(verify_api_key)])
async def list_engine_versions():
    """Lists installed llama.cpp builds and available GitHub releases."""
    installed = await ai_service.get_installed_engine_versions()
    releases = await ai_service.fetch_github_releases()
    return {
        "installed": installed,
        "releases": releases,
        "active_version": ai_service.get_active_engine_tag(),
    }


@router.post("/engine/select", dependencies=[Depends(verify_api_key)])
async def select_engine_version(request: Request):
    """Sets the active llama.cpp engine build."""
    body = await request.json()
    tag = body.get("tag")
    if not tag:
        raise HTTPException(status_code=400, detail="Tag is required")
    return ai_service.select_active_engine_version(tag)


@router.post("/engine/download", dependencies=[Depends(verify_api_key)])
async def download_engine_version(request: Request):
    """Initiates an asynchronous background download of a llama.cpp build with progress tracking."""
    body = await request.json()
    tag = body.get("tag")
    url = body.get("download_url")
    if not tag:
        raise HTTPException(status_code=400, detail="Tag is required")
    return await ai_service.start_engine_download(tag, download_url=url)


@router.get("/engine/download-progress", dependencies=[Depends(verify_api_key)])
async def get_engine_download_progress():
    """Queries current llama.cpp engine download progress, percentage, and extraction stage."""
    return ai_service.get_engine_download_progress()


@router.delete("/engine/versions/{tag}", dependencies=[Depends(verify_api_key)])
async def delete_engine_version(tag: str):
    """Deletes a cached engine build."""
    return await asyncio.to_thread(ai_service.delete_engine_version, tag)


# ==========================================
# 2. Model Management (GGUF Library & Hugging Face Explorer)
# ==========================================


@router.get("/models/catalog", dependencies=[Depends(verify_api_key)])
async def get_models_catalog():
    """Returns curated GGUF models along with installed status and custom models."""
    return await ai_service.get_models_catalog()


@router.get("/models/hf/search", dependencies=[Depends(verify_api_key)])
async def search_hf_models(
    q: Optional[str] = Query(None),
    limit: int = Query(25, ge=1, le=50),
    sort: str = Query("downloads"),
):
    """Searches Hugging Face for GGUF repositories.

    ``sort`` accepts downloads, likes, or lastModified. Results are cached
    server-side for a few minutes to avoid hammering the Hugging Face API.
    """
    return await ai_service.search_huggingface_models(query=q, limit=limit, sort=sort)


@router.get("/models/hf/files", dependencies=[Depends(verify_api_key)])
async def get_hf_model_files(model_id: str = Query(...)):
    """Inspects available GGUF quantizations for a specific Hugging Face repository."""
    return await ai_service.get_huggingface_model_files(model_id=model_id)


@router.post("/models/open-folder", dependencies=[Depends(verify_api_key)])
async def open_models_folder():
    """Opens the local models directory in the host PC's native file manager."""
    return await ai_service.open_models_directory()


@router.post("/models/import-local", dependencies=[Depends(verify_api_key)])
async def import_local_model(request: Request):
    """Imports an existing GGUF model from a local filesystem path via zero-copy symlink or copy."""
    body = await request.json()
    file_path = body.get("path")
    symlink = body.get("symlink", True)
    if not file_path:
        raise HTTPException(status_code=400, detail="Local file path is required")
    return await ai_service.import_local_model(file_path, symlink=symlink)


@router.post("/models/upload", dependencies=[Depends(verify_api_key)])
async def upload_model_file(file: UploadFile = File(...)):
    """Uploads a GGUF model file directly through the browser or drop zone."""
    filename = (file.filename or "").lower()
    if not filename.endswith(".gguf"):
        raise HTTPException(status_code=400, detail="Only .gguf files are supported")
    return await ai_service.save_uploaded_model(file)


@router.post("/models/download", dependencies=[Depends(verify_api_key)])
async def start_model_download(request: Request):
    """Initiates a background download of a GGUF model."""
    body = await request.json()
    model_id = body.get("model_id")
    custom_url = body.get("url")
    custom_name = body.get("filename")

    if not model_id and not custom_url:
        raise HTTPException(status_code=400, detail="Model ID or URL is required")

    return await ai_service.start_model_download(
        model_id=model_id,
        custom_url=custom_url,
        custom_name=custom_name,
    )


@router.get("/models/download-progress", dependencies=[Depends(verify_api_key)])
async def get_model_download_progress():
    """Queries current GGUF download progress and state."""
    return ai_service.get_download_progress()


@router.post("/models/download/cancel", dependencies=[Depends(verify_api_key)])
async def cancel_model_download():
    """Cancels any active GGUF model download."""
    return ai_service.cancel_model_download()


@router.post("/models/select", dependencies=[Depends(verify_api_key)])
async def select_active_model(request: Request):
    """Sets the active model and optionally starts or reloads the engine."""
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="A JSON object is required")
    filename = body.get("filename")
    start_engine = body.get("start_engine", True)
    if not isinstance(filename, str) or not filename:
        raise HTTPException(status_code=400, detail="Filename is required")
    if not isinstance(start_engine, bool):
        raise HTTPException(status_code=400, detail="start_engine must be a boolean")
    return await ai_service.select_active_model(filename, start_engine=start_engine)


@router.delete("/models/{filename}", dependencies=[Depends(verify_api_key)])
async def delete_model(filename: str):
    """Deletes an installed GGUF model file or symlink."""
    return await ai_service.delete_model(filename)


# ==========================================
# 3. Subprocess Control (llama-server)
# ==========================================


@router.post("/service/start", dependencies=[Depends(verify_api_key)])
async def start_ai_service():
    """Starts the llama-server process with the active GGUF model."""
    return await ai_service.start_server()


@router.post("/service/stop", dependencies=[Depends(verify_api_key)])
async def stop_ai_service():
    """Stops the llama-server process and frees PC RAM/VRAM."""
    return await ai_service.stop_server()


# ==========================================
# 4. OpenAI-Compatible Pass-Through
# ==========================================


@router.get("/v1/models", dependencies=[Depends(verify_api_key)])
async def openai_list_models():
    """OpenAI-compatible model discovery for pclink client apps."""
    return ai_service.list_openai_models()


@router.post("/v1/chat/completions", dependencies=[Depends(verify_api_key)])
async def openai_chat_completions(request: Request):
    """
    OpenAI-compatible chat completions proxy.
    Directs requests from Flutter or Web UI directly to local llama-server,
    starting the process on-demand if idle.
    Requires authentication via session cookie or Authorization Bearer token.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="A JSON body is required.")

    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="A JSON object is required.")
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise HTTPException(
            status_code=400, detail="'messages' must be a non-empty array."
        )

    stream = bool(body.get("stream", False))

    await ai_service.ensure_running()

    if stream:
        # Open the upstream stream before constructing StreamingResponse so
        # llama-server errors become real HTTP responses (and keep their
        # actionable JSON detail) instead of a bare 500 mid-stream.
        stream_body = await ai_service.proxy_stream_chat(body)

        return StreamingResponse(
            stream_body,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        result = await ai_service.proxy_sync_chat(body)
        return result
