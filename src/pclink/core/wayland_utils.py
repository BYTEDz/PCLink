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
    if os.name == 'nt' or os.name == 'ce':
        return False

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
    # Use a location that is accessible even if the service has PrivateTmp=true
    # such as the user's cache directory.
    cache_dir = Path.home() / ".cache" / "pclink"
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        # 1. Try GNOME-specific DBus API (Fastest and works inside services)
        if shutil.which("gdbus"):
            tmp_path = str(cache_dir / f"gnome_ss_{os.getpid()}.png")
            # This API is usually non-interactive on modern GNOME if the service is allowed
            result = subprocess.run([
                "gdbus", "call", "--session",
                "--dest", "org.gnome.Shell.Screenshot",
                "--object-path", "/org/gnome/Shell/Screenshot",
                "--method", "org.gnome.Shell.Screenshot.Screenshot",
                "true", "false", tmp_path
            ], capture_output=True, timeout=10)
            
            if result.returncode == 0 and Path(tmp_path).exists():
                with open(tmp_path, "rb") as f:
                    data = f.read()
                os.unlink(tmp_path)
                return data

        # 2. Try using grim (wlroots-based)
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
            tmp_path = str(cache_dir / f"spectacle_{os.getpid()}.png")
            
            result = subprocess.run(
                ["spectacle", "-b", "-n", "-o", tmp_path],
                capture_output=True,
                timeout=30
            )
            
            if result.returncode == 0 and Path(tmp_path).exists():
                with open(tmp_path, "rb") as f:
                    data = f.read()
                os.unlink(tmp_path)
                return data
        
        # Log failure reason if all methods fail
        log.warning("No Wayland screenshot tool succeeded.")
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
def setup_uinput_permissions() -> str:
    """
    Generate a command or script to fix uinput permissions for Wayland.
    Returns the command that needs to be run with sudo.
    """
    user = os.environ.get("USER") or os.environ.get("LOGNAME")
    if not user:
        return "echo 'Could not detect current user. Run: sudo groupadd -f input && sudo gpasswd -a $USER input'"

    rule = 'KERNEL=="uinput", MODE="0660", GROUP="input", OPTIONS+="static_node=uinput"'
    rule_file = "/etc/udev/rules.d/99-uinput.rules"
    
    # We return a single command that the user can copy-paste and run with sudo
    cmd = (
        f'sudo groupadd -f input && '
        f'sudo gpasswd -a {user} input && '
        f'echo \'{rule}\' | sudo tee {rule_file} && '
        f'sudo udevadm control --reload-rules && sudo udevadm trigger && '
        f'sudo modprobe uinput'
    )
    return cmd


def check_uinput_access() -> bool:
    """Check if the current user has write access to /dev/uinput."""
    return os.access("/dev/uinput", os.W_OK)
