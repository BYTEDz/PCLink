# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

from fastapi import APIRouter, HTTPException, UploadFile, File, Request, Query
from fastapi.responses import FileResponse
import shutil
import tempfile
import os
from pathlib import Path
from typing import List, Dict
from pclink.core.extension_manager import ExtensionManager

# Management Router (for listing/installing)
mgmt_router = APIRouter(tags=["extension-management"])

# Runtime Router (for serving UI/Static)
runtime_router = APIRouter(tags=["extension-runtime"])

extension_manager = ExtensionManager()

@mgmt_router.get("")
async def list_extensions():
    """Returns a list of all discovered extensions (enabled or disabled)."""
    from pclink.core.config import config_manager
    
    extensions_enabled = config_manager.get("allow_extensions", False)
    all_extensions = []
    
    # First, get names of all folders with a manifest
    discovered_ids = extension_manager.discover_extensions()
    
    for extension_id in discovered_ids:
        manifest_path = extension_manager.extensions_path / extension_id / "extension.yaml"
        try:
            import yaml
            with open(manifest_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            # If loaded, sync metadata in memory if it changed
            extension = extension_manager.get_extension(extension_id)
            if extension:
                try:
                    from pclink.core.extension_base import ExtensionMetadata
                    extension.metadata = ExtensionMetadata(**config)
                except:
                    pass
                all_extensions.append(extension.metadata.dict())
                continue

            # Hot-loading: If it's enabled in manifest but not in memory, try to load it
            if extensions_enabled and config.get('enabled', True):
                if extension_manager.load_extension(extension_id):
                    # Successful load, use the loaded metadata
                    loaded_ext = extension_manager.get_extension(extension_id)
                    if loaded_ext:
                        all_extensions.append(loaded_ext.metadata.dict())
                        continue

            # Ensure the enabled flag is present if still not loaded
            if 'enabled' not in config:
                config['enabled'] = True
            # If loading failed or it's genuinely disabled, add it as disabled
            config['enabled'] = False if not extension_manager.get_extension(extension_id) else config.get('enabled', True)
            all_extensions.append(config)
        except:
            continue
    
    # Return dict with status and extensions list for backward compatibility
    # Old clients will get the list at root, new clients can check extensions_enabled
    return {
        "extensions_enabled": extensions_enabled,
        "extensions": all_extensions
    }

@mgmt_router.post("/install")
async def install_extension(file: UploadFile = File(...)):
    """Uploads and installs a new extension bundle (.zip)."""
    from pclink.core.config import config_manager
    if not config_manager.get("allow_extensions", False):
        raise HTTPException(status_code=403, detail="Extension system is disabled globally. Enable it in settings to install extensions.")

    if not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip files are allowed")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        success = extension_manager.install_extension(tmp_path)
        if success:
            return {"status": "success", "message": "Extension installed successfully"}
        else:
            raise HTTPException(status_code=400, detail="Extension verification or installation failed")
    finally:
        if tmp_path.exists():
            os.unlink(tmp_path)

@mgmt_router.delete("/{extension_id}")
async def delete_extension(extension_id: str):
    """Deletes an extension."""
    from pclink.core.config import config_manager
    if not config_manager.get("allow_extensions", False):
        raise HTTPException(status_code=403, detail="Extension system is disabled globally. Enable it in settings to delete extensions.")

    if extension_manager.delete_extension(extension_id):
        return {"status": "success", "message": f"Extension {extension_id} deleted"}
    else:
        raise HTTPException(status_code=500, detail=f"Failed to delete extension {extension_id}")

@mgmt_router.post("/{extension_id}/toggle")
async def toggle_extension(extension_id: str, enabled: bool):
    """Enables or disables an extension."""
    from pclink.core.config import config_manager
    if not config_manager.get("allow_extensions", False):
        raise HTTPException(status_code=403, detail="Extension system is disabled globally. Enable it in settings to toggle extensions.")

    if extension_manager.toggle_extension(extension_id, enabled):
        return {"status": "success", "message": f"Extension {extension_id} {'enabled' if enabled else 'disabled'}"}
    else:
        raise HTTPException(status_code=500, detail=f"Failed to toggle extension {extension_id}")

@mgmt_router.get("/{extension_id}/logs")
async def get_extension_logs(extension_id: str):
    """Returns the captured logs for a specific extension."""
    logs = extension_manager.get_extension_logs(extension_id)
    return {"id": extension_id, "logs": logs}

@mgmt_router.delete("/{extension_id}/logs")
async def clear_extension_logs(extension_id: str):
    """Clears the captured logs for a specific extension."""
    extension_manager.clear_extension_logs(extension_id)
    return {"status": "success", "message": "Logs cleared"}

@runtime_router.get("/{extension_id}/ui")
async def get_extension_ui(extension_id: str, token: str = Query(None)):
    """Serves the extension's main UI (index.html)."""
    extension = extension_manager.get_extension(extension_id)
    if not extension:
        # Check if it exists but is disabled
        extension_dir = extension_manager.extensions_path / extension_id
        if (extension_dir / "extension.yaml").exists():
            raise HTTPException(status_code=403, detail="Extension is disabled")
        raise HTTPException(status_code=404, detail="Extension not found")
        
    if not extension.metadata.ui_entry:
        raise HTTPException(status_code=404, detail="Extension UI not found")
    
    ui_path = extension.extension_path / extension.metadata.ui_entry
    if not ui_path.exists():
        raise HTTPException(status_code=404, detail=f"UI file {extension.metadata.ui_entry} missing")
        
    response = FileResponse(ui_path)
    if token:
        # Set a session cookie for the device to allow subsequent asset/API requests
        response.set_cookie(
            key="pclink_device_token", 
            value=token, 
            max_age=3600, 
            httponly=True, 
            samesite="lax",
            path="/"
        )
    return response

@runtime_router.get("/{extension_id}/icon")
async def get_extension_icon(extension_id: str):
    """Serves the extension's icon if specified."""
    extension = extension_manager.get_extension(extension_id)
    if not extension or not extension.metadata.icon:
        raise HTTPException(status_code=404, detail="Icon not specified")
        
    icon_path = (extension.extension_path / extension.metadata.icon).resolve()
    
    # Security: Ensure icon is within extension dir
    if not str(icon_path).startswith(str(extension.extension_path.resolve())):
        raise HTTPException(status_code=403, detail="Forbidden")

    if not icon_path.exists() or not icon_path.is_file():
        raise HTTPException(status_code=404, detail="Icon file not found")
        
    return FileResponse(icon_path)

@runtime_router.get("/{extension_id}/static/{file_path:path}")
async def get_extension_static(extension_id: str, file_path: str):
    """Serves static files for a specific extension."""
    if not extension_manager._is_safe_name(extension_id):
        raise HTTPException(status_code=400, detail="Invalid extension ID")

    extension = extension_manager.get_extension(extension_id)
    if not extension:
        raise HTTPException(status_code=404, detail="Extension not found")
        
    base_static = extension.get_static_path().resolve()
    target_file = (base_static / file_path).resolve()
    
    # Security: Ensure target is within base_static
    if not str(target_file).startswith(str(base_static)):
        raise HTTPException(status_code=403, detail="Forbidden")

    if not target_file.exists() or not target_file.is_file():
        raise HTTPException(status_code=404, detail="Static file not found")
        
    return FileResponse(target_file)

def mount_extension_routes(app, dependencies=None):
    """
    Mounts individual extension routers to the main application.
    """
    for extension_id, extension in extension_manager.extensions.items():
        # Mount under /extensions/{extension_id} (New standard)
        app.include_router(
            extension.get_routes(),
            prefix=f"/extensions/{extension_id}",
            tags=[f"extension-{extension_id}"],
            dependencies=dependencies
        )
