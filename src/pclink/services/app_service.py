# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import configparser
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

try:
    import winshell

    WINSHELL_AVAILABLE = True
except ImportError:
    WINSHELL_AVAILABLE = False


class AppService:
    """Logic for application discovery, icon resolution, and launching."""

    def __init__(self):
        self._cache = {"apps": [], "timestamp": 0}
        self._cache_ttl = 86400  # 24 hours

    async def get_applications(self, force_refresh: bool = False) -> List[Dict]:
        now = time.time()
        if (
            not force_refresh
            and self._cache["apps"]
            and (now - self._cache["timestamp"] < self._cache_ttl)
        ):
            return self._cache["apps"]

        apps = []
        # Run synchronous and heavy directory scanning operations in a thread pool to avoid blocking the event loop
        if sys.platform == "win32":
            apps = await asyncio.to_thread(self._discover_win32)
        elif sys.platform.startswith("linux"):
            apps = await asyncio.to_thread(self._discover_linux)

        self._cache = {"apps": apps, "timestamp": now}
        return apps

    def _discover_win32(self) -> List[Dict]:
        if not WINSHELL_AVAILABLE:
            return []
        apps = {}
        paths = [
            Path(winshell.folder("common_programs")),
            Path(winshell.folder("programs")),
        ]
        for p in paths:
            for lnk in p.glob("**/*.lnk"):
                try:
                    target = winshell.shortcut(str(lnk)).path
                    if (
                        target
                        and target.lower().endswith(".exe")
                        and os.path.exists(target)
                    ):
                        if lnk.stem not in apps:
                            apps[lnk.stem] = {
                                "name": lnk.stem,
                                "command": target,
                                "icon_path": target,
                                "is_custom": False,
                            }
                except Exception:
                    continue
        return sorted(list(apps.values()), key=lambda x: x["name"])

    def _discover_linux(self) -> List[Dict]:
        apps = {}
        paths = [
            Path("/usr/share/applications"),
            Path.home() / ".local/share/applications",
        ]
        for p in paths:
            if not p.is_dir():
                continue
            for desktop in p.glob("**/*.desktop"):
                try:
                    cfg = configparser.ConfigParser(interpolation=None)
                    cfg.read(str(desktop), encoding="utf-8")
                    if "Desktop Entry" in cfg:
                        entry = cfg["Desktop Entry"]
                        if entry.getboolean("NoDisplay", False):
                            continue
                        if entry.get("Type", "Application") != "Application":
                            continue

                        name = entry.get("Name")
                        cmd = entry.get("Exec")
                        if name and cmd:
                            # Clean execution field codes according to Desktop Entry Specification
                            clean_cmd = (
                                re.sub(r"\s*%[a-zA-Z]", "", cmd).strip().strip('"')
                            )
                            icon = entry.get("Icon")
                            resolved_icon = self.find_linux_icon(icon) if icon else None
                            if name not in apps:
                                apps[name] = {
                                    "name": name,
                                    "command": clean_cmd,
                                    "icon_path": resolved_icon or icon,
                                    "is_custom": False,
                                }
                except Exception:
                    continue
        return sorted(list(apps.values()), key=lambda x: x["name"])

    def find_linux_icon(self, name: str) -> Optional[str]:
        if not name:
            return None
        if Path(name).is_absolute() and Path(name).exists():
            return name

        # Common directories where app icons are located
        search_bases = [
            Path("/usr/share/pixmaps"),
            Path("/usr/share/icons/hicolor/scalable/apps"),
            Path("/usr/share/icons/hicolor/48x48/apps"),
            Path("/usr/share/icons/hicolor/512x512/apps"),
            Path("/usr/share/icons/hicolor/256x256/apps"),
            Path("/usr/share/icons/hicolor/128x128/apps"),
            Path.home() / ".local/share/icons",
            Path("/usr/share/icons"),
        ]

        extensions = [".png", ".svg", ".xpm"]

        # Pass 1: Direct path lookup (extremely fast, avoids heavy disk crawling)
        for base in search_bases:
            if not base.is_dir():
                continue
            for ext in extensions:
                candidate = base / f"{name}{ext}"
                if candidate.exists():
                    return str(candidate)

        # Pass 2: Fallback to targeted shallow searches if direct lookup is missed
        for base in search_bases:
            if not base.is_dir():
                continue

            # Prevent rglob over huge parent directories directly
            if str(base) in (
                "/usr/share/icons",
                str(Path.home() / ".local/share/icons"),
            ):
                for ext in extensions:
                    matches = list(base.glob(f"*/apps/{name}{ext}")) or list(
                        base.glob(f"hicolor/*/apps/{name}{ext}")
                    )
                    if matches:
                        return str(matches[0])
            else:
                for ext in extensions:
                    matches = list(base.rglob(f"**/{name}{ext}"))
                    if matches:
                        return str(matches[0])

        return None

    async def launch(self, command: str):
        def _run():
            flags = 0
            kwargs = {
                "shell": True,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "stdin": subprocess.DEVNULL,
            }
            if sys.platform == "win32":
                flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
                kwargs["creationflags"] = flags
                command_run = command if command.startswith('"') else f'"{command}"'
            else:
                kwargs["start_new_session"] = True
                command_run = command

            subprocess.Popen(command_run, **kwargs)

        await asyncio.to_thread(_run)


# Global instance
app_service = AppService()
