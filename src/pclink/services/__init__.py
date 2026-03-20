# src/pclink/services/__init__.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

from .app_service import app_service
from .discovery_service import DiscoveryService
from .extension_service import extension_service
from .file_service import file_service
from .input_service import input_service
from .macro_service import macro_service
from .media_service import media_service
from .process_service import process_service
from .system_service import system_service
from .terminal_service import terminal_service
from .transfer_service import transfer_service
from .utility_service import utility_service

__all__ = [
    "system_service",
    "media_service",
    "input_service",
    "process_service",
    "utility_service",
    "file_service",
    "app_service",
    "extension_service",
    "macro_service",
    "terminal_service",
    "DiscoveryService",
    "transfer_service",
]
