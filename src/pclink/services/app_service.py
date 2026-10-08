# src/pclink/services/app_service.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import asyncio
import configparser
import hashlib
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from ..core.constants import get_app_data_path

log = logging.getLogger(__name__)


class AppService:
    """Logic for application discovery, icon resolution, and launching."""

    def __init__(self):
        self._cache = {"apps": [], "timestamp": 0}
        self._cache_ttl = 86400  # 24 hours
        self._icon_cache: Dict[str, Optional[str]] = {}
        try:
            self._icon_disk_cache_dir = (
                get_app_data_path("pclink") / "cache" / "app_icons"
            )
            self._icon_disk_cache_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            self._icon_disk_cache_dir = Path.home() / ".cache" / "pclink" / "app_icons"
            self._icon_disk_cache_dir.mkdir(parents=True, exist_ok=True)

    async def get_applications(self, force_refresh: bool = False) -> List[Dict]:
        now = time.time()
        if (
            not force_refresh
            and self._cache["apps"]
            and (now - self._cache["timestamp"] < self._cache_ttl)
        ):
            return self._cache["apps"]

        apps = []
        if sys.platform == "win32":
            apps = await asyncio.to_thread(self._discover_win32)
        elif sys.platform.startswith("linux"):
            apps = await self._discover_linux_async()

        log.debug(f"[AppService] Discovery complete: found {len(apps)} apps")
        self._cache = {"apps": apps, "timestamp": now}
        return apps

    def _discover_win32(self) -> List[Dict]:
        apps = {}
        try:
            import win32com.client  # type: ignore

            shell = win32com.client.Dispatch("WScript.Shell")
            paths = [
                Path(shell.SpecialFolders("AllUsersPrograms")),
                Path(shell.SpecialFolders("Programs")),
            ]
            for p in paths:
                if not p.exists():
                    continue
                for lnk in p.glob("**/*.lnk"):
                    try:
                        shortcut = shell.CreateShortcut(str(lnk))
                        target = shortcut.TargetPath
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
        except Exception as e:
            log.debug(f"[AppService] Win32 shortcut discovery failed: {e}")

        return sorted(list(apps.values()), key=lambda x: x["name"])

    def _parse_desktop_file(self, desktop_file: Path) -> Optional[Dict]:
        """Parses a single .desktop file and pre-resolves its icon with exact file extension."""
        try:
            cfg = configparser.ConfigParser(interpolation=None)
            cfg.read(str(desktop_file), encoding="utf-8")
            if "Desktop Entry" in cfg:
                entry = cfg["Desktop Entry"]
                if entry.getboolean("NoDisplay", False):
                    return None
                if entry.get("Type", "Application") != "Application":
                    return None

                name = entry.get("Name")
                cmd = entry.get("Exec")
                if name and cmd:
                    clean_cmd = re.sub(r"\s*%[a-zA-Z]", "", cmd).strip().strip('"')
                    raw_icon = entry.get("Icon")
                    resolved_icon = self.find_linux_icon(raw_icon) if raw_icon else None

                    return {
                        "name": name,
                        "command": clean_cmd,
                        "icon_path": resolved_icon or raw_icon or "",
                        "is_custom": False,
                    }
        except Exception as e:
            log.debug(f"[AppService] Failed parsing {desktop_file}: {e}")
        return None

    async def _discover_linux_async(self) -> List[Dict]:
        paths = [
            Path("/usr/share/applications"),
            Path.home() / ".local/share/applications",
            Path("/var/lib/flatpak/exports/share/applications"),
            Path.home() / ".local/share/flatpak/exports/share/applications",
            Path("/var/lib/snapd/desktop/applications"),
        ]
        desktop_files = []
        for p in paths:
            if p.is_dir():
                try:
                    desktop_files.extend(list(p.glob("**/*.desktop")))
                except Exception:
                    pass

        if not desktop_files:
            return []

        tasks = [
            asyncio.to_thread(self._parse_desktop_file, df) for df in desktop_files
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        apps = {}
        for res in results:
            if isinstance(res, dict) and res.get("name"):
                name = res["name"]
                if name not in apps:
                    apps[name] = res

        return sorted(list(apps.values()), key=lambda x: x["name"])

    def find_linux_icon(self, raw_name: str) -> Optional[str]:
        if not raw_name:
            return None
        if raw_name in self._icon_cache:
            return self._icon_cache[raw_name]

        # 1. Absolute direct path check
        if Path(raw_name).is_absolute() and Path(raw_name).exists():
            self._icon_cache[raw_name] = raw_name
            return raw_name

        clean = re.sub(r"\.(png|svg|xpm|ico)$", "", raw_name.strip())

        # Generate candidate names (handling KDE reverse-domain prefixes)
        candidates = [clean]
        if clean.startswith("org.kde."):
            short = clean.replace("org.kde.", "")
            candidates.append(short)
            if short == "dolphin":
                candidates.append("system-file-manager")
            elif short == "konsole":
                candidates.append("utilities-terminal")
            elif short == "systemsettings":
                candidates.append("preferences-system")
        elif "." in clean:
            candidates.append(clean.split(".")[-1])
        else:
            candidates.append(f"org.kde.{clean}")

        # Search bases covering KDE Plasma (Breeze / Breeze-Dark), Hicolor, GNOME, Pixmaps, Flatpak & Snap
        search_roots = [
            Path("/usr/share/icons/breeze/apps/48"),
            Path("/usr/share/icons/breeze/apps/scalable"),
            Path("/usr/share/icons/breeze/apps/32"),
            Path("/usr/share/icons/breeze/apps/64"),
            Path("/usr/share/icons/breeze/preferences/32"),
            Path("/usr/share/icons/breeze/preferences/48"),
            Path("/usr/share/icons/breeze-dark/apps/48"),
            Path("/usr/share/icons/breeze-dark/apps/scalable"),
            Path("/usr/share/icons/breeze-dark/apps/32"),
            Path("/usr/share/icons/breeze-dark/preferences/32"),
            Path("/usr/share/icons/hicolor/scalable/apps"),
            Path("/usr/share/icons/hicolor/48x48/apps"),
            Path("/usr/share/icons/hicolor/128x128/apps"),
            Path("/usr/share/icons/hicolor/256x256/apps"),
            Path("/usr/share/icons/hicolor/512x512/apps"),
            Path("/usr/share/icons/hicolor/64x64/apps"),
            Path("/usr/share/icons/hicolor/32x32/apps"),
            Path("/usr/share/pixmaps"),
            Path.home() / ".local/share/icons/hicolor/scalable/apps",
            Path.home() / ".local/share/icons/hicolor/48x48/apps",
            Path.home() / ".local/share/icons/breeze/apps/48",
            Path.home() / ".local/share/icons/breeze/apps/scalable",
            Path("/var/lib/flatpak/exports/share/icons/hicolor/scalable/apps"),
            Path("/var/lib/flatpak/exports/share/icons/hicolor/128x128/apps"),
            Path.home()
            / ".local/share/flatpak/exports/share/icons/hicolor/scalable/apps",
            Path.home()
            / ".local/share/flatpak/exports/share/icons/hicolor/128x128/apps",
            Path("/var/lib/snapd/desktop/icons"),
        ]

        extensions = [".svg", ".png", ".xpm"]

        for root in search_roots:
            if not root.is_dir():
                continue
            for cand in candidates:
                for ext in extensions:
                    candidate_file = root / f"{cand}{ext}"
                    if candidate_file.exists():
                        resolved = str(candidate_file)
                        self._icon_cache[raw_name] = resolved
                        return resolved

        # Fallback: single-level glob in known theme directories
        theme_names = ["breeze", "breeze-dark", "Papirus", "Adwaita"]
        for theme in theme_names:
            theme_dir = Path("/usr/share/icons") / theme
            if not theme_dir.is_dir():
                continue
            for cand in candidates:
                for ext in extensions:
                    matches = list(theme_dir.glob(f"*/{cand}{ext}")) or list(
                        theme_dir.glob(f"*/*/{cand}{ext}")
                    )
                    if matches:
                        resolved = str(matches[0])
                        self._icon_cache[raw_name] = resolved
                        return resolved

        self._icon_cache[raw_name] = None
        return None

    def find_windows_icon(self, target_path: str) -> Optional[str]:
        if not target_path or not os.path.exists(target_path):
            return None

        if target_path.lower().endswith(".ico"):
            return target_path

        try:
            mtime = os.path.getmtime(target_path)
        except OSError:
            mtime = 0
        cache_key = hashlib.md5(f"{target_path}_{mtime}".encode("utf-8")).hexdigest()
        cached_png = self._icon_disk_cache_dir / f"{cache_key}.png"
        if cached_png.exists() and cached_png.stat().st_size > 0:
            return str(cached_png)

        try:
            import win32gui  # type: ignore
            import win32ui  # type: ignore
            from PIL import Image

            large, _ = win32gui.ExtractIconEx(target_path, 0)
            if large:
                hicon = large[0]
                try:
                    hdc = win32ui.CreateDCFromHandle(win32gui.GetDC(0))
                    hbmp = win32ui.CreateBitmap()
                    hbmp.CreateCompatibleBitmap(hdc, 48, 48)
                    hdc_mem = hdc.CreateCompatibleDC()
                    hdc_mem.SelectObject(hbmp)
                    win32gui.DrawIconEx(
                        hdc_mem.GetHandleOutput(),
                        0,
                        0,
                        hicon,
                        48,
                        48,
                        0,
                        None,
                        0x0003,
                    )
                    bmpinfo = hbmp.GetInfo()
                    bmpstr = hbmp.GetBitmapBits(True)
                    img = Image.frombuffer(
                        "RGBA",
                        (bmpinfo["bmWidth"], bmpinfo["bmHeight"]),
                        bmpstr,
                        "raw",
                        "BGRA",
                        0,
                        1,
                    )
                    self._icon_disk_cache_dir.mkdir(parents=True, exist_ok=True)
                    img.save(str(cached_png), format="PNG")
                    return str(cached_png)
                finally:
                    win32gui.DestroyIcon(hicon)
                    hdc_mem.DeleteDC()
                    hdc.DeleteDC()
        except Exception as e:
            log.debug(
                f"[AppService] Failed extracting Win32 icon for '{target_path}': {e}"
            )

        return None

    async def resolve_icon(self, icon_identifier: str) -> Optional[str]:
        if not icon_identifier:
            return None
        if sys.platform == "win32":
            return await asyncio.to_thread(self.find_windows_icon, icon_identifier)
        elif sys.platform.startswith("linux"):
            return await asyncio.to_thread(self.find_linux_icon, icon_identifier)
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
