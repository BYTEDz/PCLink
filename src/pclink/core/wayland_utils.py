# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz
"""
Wayland compatibility utilities for screenshot and clipboard.

This module provides Wayland-compatible implementations using:
- xdg-desktop-portal for screenshots (D-Bus)
- wl-clipboard utilities for clipboard operations
"""

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


def is_wayland() -> bool:
    """
    Detect if the current session is running under Wayland.
    
    Returns:
        True if running under Wayland, False otherwise.
    """
    # Check XDG_SESSION_TYPE first (most reliable)
    session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session_type == "wayland":
        return True
    if session_type == "x11":
        return False
    
    # Fallback: check for Wayland display
    if os.environ.get("WAYLAND_DISPLAY"):
        return True
    
    return False


def screenshot_portal() -> Optional[bytes]:
    """
    Take a screenshot using xdg-desktop-portal (Wayland-compatible).
    
    This uses the Portal Screenshot API via D-Bus. The user may be prompted
    to confirm the screenshot (standard Wayland security behavior).
    
    Returns:
        PNG image bytes if successful, None otherwise.
    """
    try:
        # Try using gnome-screenshot first (simpler, widely available)
        if shutil.which("gnome-screenshot"):
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
            
            result = subprocess.run(
                ["gnome-screenshot", "-f", tmp_path],
                capture_output=True,
                timeout=10
            )
            
            if result.returncode == 0 and Path(tmp_path).exists():
                with open(tmp_path, "rb") as f:
                    data = f.read()
                os.unlink(tmp_path)
                return data
            
            # Clean up on failure
            if Path(tmp_path).exists():
                os.unlink(tmp_path)
        
        # Fallback: try grim (wlroots-based compositors)
        if shutil.which("grim"):
            result = subprocess.run(
                ["grim", "-"],
                capture_output=True,
                timeout=10
            )
            if result.returncode == 0:
                return result.stdout
        
        # Fallback: try spectacle (KDE)
        if shutil.which("spectacle"):
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
            
            result = subprocess.run(
                ["spectacle", "-b", "-n", "-o", tmp_path],
                capture_output=True,
                timeout=10
            )
            
            if result.returncode == 0 and Path(tmp_path).exists():
                with open(tmp_path, "rb") as f:
                    data = f.read()
                os.unlink(tmp_path)
                return data
        
        log.warning("No Wayland screenshot tool found (tried gnome-screenshot, grim, spectacle)")
        return None
        
    except subprocess.TimeoutExpired:
        log.error("Screenshot command timed out")
        return None
    except Exception as e:
        log.error(f"Portal screenshot failed: {e}")
        return None


def clipboard_get_wayland() -> Optional[str]:
    """
    Get clipboard text using wl-paste (Wayland-compatible).
    
    Returns:
        Clipboard text if successful, None otherwise.
    """
    if not shutil.which("wl-paste"):
        log.warning("wl-paste not found. Install wl-clipboard package.")
        return None
    
    try:
        result = subprocess.run(
            ["wl-paste", "--no-newline"],
            capture_output=True,
            text=True,
            timeout=15  # Increased timeout for slow Wayland clipboard
        )
        if result.returncode == 0:
            return result.stdout
        return None
    except subprocess.TimeoutExpired:
        log.error("wl-paste timed out")
        return None
    except Exception as e:
        log.error(f"wl-paste failed: {e}")
        return None


def clipboard_set_wayland(text: str) -> bool:
    """
    Set clipboard text using wl-copy (Wayland-compatible).
    
    Args:
        text: The text to copy to clipboard.
        
    Returns:
        True if successful, False otherwise.
    """
    if not shutil.which("wl-copy"):
        log.warning("wl-copy not found. Install wl-clipboard package.")
        return False
    
    try:
        result = subprocess.run(
            ["wl-copy"],
            input=text,
            text=True,
            timeout=15  # Increased timeout for slow Wayland clipboard
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        log.error("wl-copy timed out")
        return False
    except Exception as e:
        log.error(f"wl-copy failed: {e}")
        return False
