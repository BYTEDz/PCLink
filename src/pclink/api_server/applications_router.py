import logging
import os
import platform
import subprocess
import sys
from typing import List, Optional
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

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
                            icon_path=None
                        )
            except Exception as e:
                log.debug(f"Could not resolve shortcut '{lnk_path}': {e}")
                continue

    return sorted(list(apps.values()), key=lambda x: x.name)


@router.get("", response_model=List[Application], summary="Get all discovered and custom applications")
async def get_applications(force_refresh: bool = False):
    global APP_CACHE, CACHE_TIMESTAMP
    if force_refresh or not APP_CACHE or time.time() - CACHE_TIMESTAMP > CACHE_DURATION_SECONDS:
        log.info("Refreshing application cache...")
        system = platform.system()
        discovered_apps = []
        if system == "Windows":
            discovered_apps = _discover_apps_from_start_menu()
        APP_CACHE = [app.model_dump() for app in discovered_apps]
        CACHE_TIMESTAMP = time.time()
    return APP_CACHE

@router.post("/launch", summary="Launch an application")
async def launch_application(payload: AppLaunchPayload):
    if not payload.command:
        raise HTTPException(status_code=400, detail="Command cannot be empty.")
    try:
        flags = 0
        if sys.platform == "win32":
            flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
        subprocess.Popen(f'"{payload.command}"', shell=True, creationflags=flags)
        return {"status": "success", "message": f"Launch command sent for '{os.path.basename(payload.command)}'."}
    except Exception as e:
        log.error(f"Failed to launch application with command '{payload.command}': {e}")
        raise HTTPException(status_code=500, detail=f"Failed to launch application: {e}")