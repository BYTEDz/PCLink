# src/pclink/api_server/applications_router.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
import os
import platform
import subprocess
import sys
import time
import re
import configparser
from typing import List, Optional
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse

try:
    import winshell
    SHORTCUT_RESOLUTION_SUPPORTED = True
except ImportError:
    SHORTCUT_RESOLUTION_SUPPORTED = False

log = logging.getLogger(__name__)
router = APIRouter()

APP_CACHE: List[dict] = []
CACHE_TIMESTAMP: float = 0
CACHE_DURATION_SECONDS = 24 * 60 * 60

class Application(BaseModel):
    name: str = Field(..., description="The display name of the application.")
    command: str = Field(..., description="The command or path to execute the application.")
    icon_path: Optional[str] = Field(None, description="The path to the application's icon.")
    is_custom: bool = Field(False, description="Whether this is a user-added application.")

class AppLaunchPayload(BaseModel):
    command: str

def _discover_apps_from_start_menu() -> List[Application]:
    if not SHORTCUT_RESOLUTION_SUPPORTED:
        log.warning("Cannot discover apps from Start Menu: 'winshell' package not installed.")
        return []

    apps = {}
    start_menu_paths = [
        Path(winshell.folder("common_programs")),
        Path(winshell.folder("programs"))
    ]

    for path in start_menu_paths:
        for lnk_path in path.glob("**/*.lnk"):
            try:
                shortcut = winshell.shortcut(str(lnk_path))
                target_path = shortcut.path

                if target_path and target_path.lower().endswith('.exe') and os.path.exists(target_path):
                    app_name = lnk_path.stem
                    if app_name not in apps:
                        apps[app_name] = Application(
                            name=app_name,
                            command=target_path,
                            icon_path=target_path 
                        )
            except Exception as e:
                log.debug(f"Could not resolve shortcut '{lnk_path}': {e}")
                continue

    return sorted(list(apps.values()), key=lambda x: x.name)

def _discover_apps_linux() -> List[Application]:
    apps = {}
    search_paths = [
        Path("/usr/share/applications"),
        Path.home() / ".local/share/applications"
    ]
    log.info(f"Scanning for Linux applications in: {[str(p) for p in search_paths]}")

    for path in search_paths:
        if not path.is_dir():
            log.warning(f"Application directory not found, skipping: {path}")
            continue
        for desktop_file in path.glob("**/*.desktop"):
            try:
                config = configparser.ConfigParser(interpolation=None)
                config.read(str(desktop_file), encoding='utf-8')

                if 'Desktop Entry' in config:
                    entry = config['Desktop Entry']
                    if entry.getboolean('NoDisplay', False):
                        continue
                    if entry.get('Type', 'Application') != 'Application':
                        continue

                    name = entry.get('Name')
                    exec_command = entry.get('Exec')

                    if name and exec_command:
                        clean_command = re.sub(r'\s%[a-zA-Z]', '', exec_command).strip()
                        if clean_command.startswith('"') and clean_command.endswith('"'):
                            clean_command = clean_command[1:-1]
                        
                        icon = entry.get('Icon')

                        if name not in apps:
                            apps[name] = Application(
                                name=name,
                                command=clean_command,
                                icon_path=icon
                            )
            except Exception as e:
                log.debug(f"Could not parse desktop file '{desktop_file}': {e}")
                continue
    
    log.info(f"Found {len(apps)} Linux applications.")
    return sorted(list(apps.values()), key=lambda x: x.name)

def _find_icon_path(icon_name: str) -> Optional[str]:
    if not icon_name:
        return None
        
    if Path(icon_name).is_absolute() and Path(icon_name).exists():
        return icon_name

    search_paths = [
        "/usr/share/icons",
        str(Path.home() / ".local/share/icons"),
        "/usr/share/pixmaps"
    ]
    
    extensions = ['.svg', '.png']

    for base_path in search_paths:
        p = Path(base_path)
        if not p.is_dir():
            continue
        
        for ext in extensions:
            # Using rglob to recursively find the icon
            matches = list(p.rglob(f"**/{icon_name}{ext}"))
            if matches:
                # Return the first match found
                return str(matches[0])

    return None

@router.get("", response_model=List[Application], summary="Get all discovered and custom applications")
async def get_applications(force_refresh: bool = False):
    global APP_CACHE, CACHE_TIMESTAMP
    if force_refresh or not APP_CACHE or time.time() - CACHE_TIMESTAMP > CACHE_DURATION_SECONDS:
        log.info("Refreshing application cache...")
        system = platform.system()
        discovered_apps = []
        if system == "Windows":
            log.info("Discovering applications for Windows...")
            discovered_apps = _discover_apps_from_start_menu()
        elif system == "Linux":
            log.info("Discovering applications for Linux...")
            discovered_apps = _discover_apps_linux()
        else:
            log.warning(f"Application discovery not supported on this platform: {system}")
        
        APP_CACHE = [app.model_dump() for app in discovered_apps]
        CACHE_TIMESTAMP = time.time()
    return APP_CACHE

@router.post("/launch", summary="Launch an application")
async def launch_application(payload: AppLaunchPayload):
    if not payload.command:
        raise HTTPException(status_code=400, detail="Command cannot be empty.")
    try:
        flags = 0
        use_shell = True
        if sys.platform == "win32":
            flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
            command_to_run = f'"{payload.command}"'
        else:
            command_to_run = payload.command

        subprocess.Popen(command_to_run, shell=use_shell, creationflags=flags)
        return {"status": "success", "message": f"Launch command sent for '{os.path.basename(payload.command)}'."}
    except Exception as e:
        log.error(f"Failed to launch application with command '{payload.command}': {e}")
        raise HTTPException(status_code=500, detail=f"Failed to launch application: {e}")

@router.get("/icon", summary="Get an application icon file")
async def get_application_icon(path: str):
    if not path:
        raise HTTPException(status_code=400, detail="Icon path/name cannot be empty.")
    
    # Basic security check to prevent path traversal
    if ".." in path:
        raise HTTPException(status_code=400, detail="Invalid icon path.")
    
    system = platform.system()
    if system == "Windows":
        # On Windows, the path is expected to be a direct path to an executable
        # This part of the logic might need a dedicated icon extractor library in the future,
        # but for now we assume the client handles it or it's not implemented.
        log.warning(f"Icon retrieval for Windows by path is not fully implemented: {path}")
        raise HTTPException(status_code=501, detail="Icon retrieval for Windows not implemented.")

    elif system == "Linux":
        icon_path = _find_icon_path(path)
        if icon_path:
            return FileResponse(icon_path)

    log.warning(f"Icon not found for name/path: {path}")
    raise HTTPException(status_code=404, detail=f"Icon '{path}' not found.")