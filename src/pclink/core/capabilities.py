# src/pclink/core/capabilities.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 AZHAR ZOUHIR / BYTEDz

import sys
from typing import List
from .config import config_manager

PROTOCOL_VERSION = 2


def resolve_server_capabilities() -> List[str]:
    """
    Returns a simple list of feature tags currently active and supported
    by this host machine and configuration.
    """
    caps: List[str] = [
        "input",
        "smart_clipboard",
        "power_control",
        "macros",
        "wake_on_lan",
    ]

    services = config_manager.get("services", {})

    # File browser
    if services.get("files_read", True):
        caps.append("file_browser")

    # Cloud WAN Remote Access & E2EE
    if config_manager.get("enable_remote_access", True):
        caps.append("remote_access")
        caps.append("e2ee_wan")

    # Terminal gate
    if services.get("terminal", False) and config_manager.get(
        "allow_terminal_access", False
    ):
        caps.append("terminal")

    # Extensions gate
    if services.get("extensions", True) and config_manager.get(
        "allow_extensions", False
    ):
        caps.append("extensions")

    # Desktop streaming (supported OS)
    if sys.platform in ("win32", "linux", "darwin") and services.get(
        "desktop_streaming", True
    ):
        caps.append("desktop_streaming")

    return caps
