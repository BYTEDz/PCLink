# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional
from fastapi import APIRouter
from pydantic import BaseModel

class ExtensionWidgetModel(BaseModel):
    id: str
    display_name: str
    ui_entry: str  # Path to the widget HTML file
    width: int = 1 # 1: normal, 2: wide
    height: int = 1 # 1: normal, 2: tall
    refresh_ms: int = 0 # 0 means handled by widget JS

class UICapabilities(BaseModel):
    allow_fullscreen: bool = False
    allow_touchpad_overlay: bool = False
    allow_keyboard: bool = False
    prevent_sleep: bool = False
    orientation: Optional[str] = "auto"  # auto, follow_system, landscape, portrait

class ExtensionMetadata(BaseModel):
    name: str
    display_name: str
    version: str
    description: str
    author: str
    pclink_version: str
    entry_point: str
    ui_entry: Optional[str] = None
    permissions: List[str] = []
    enabled: bool = True
    supported_platforms: List[str] = ["windows", "linux", "darwin"]
    supported_architectures: List[str] = ["x86_64", "amd64", "arm64", "aarch64"]
    supported_distros: List[str] = [] # Optional: e.g. ["arch", "ubuntu"]
    icon: Optional[str] = None
    theme_aware_icon: bool = False
    category: str = "Utility"
    min_server_version: str = "1.0.0"
    ui_capabilities: UICapabilities = UICapabilities()
    dashboard_widgets: List[ExtensionWidgetModel] = []

class ExtensionBase(ABC):
    def __init__(self, metadata: ExtensionMetadata, extension_path: Path, config: Dict, context=None):
        self.metadata = metadata
        self.extension_path = extension_path
        self.config = config
        self.context = context
        self.router = APIRouter()
        self.logger = logging.getLogger(f"pclink.extensions.{metadata.name}")

    @abstractmethod
    def initialize(self) -> bool:
        """Called when the extension is enabled."""
        pass

    @abstractmethod
    def cleanup(self):
        """Called when the extension is disabled or removed."""
        pass

    def get_routes(self) -> APIRouter:
        """Returns the APIRouter for the extension."""
        return self.router

    def get_static_path(self) -> Path:
        """Returns the path to the extension's static files."""
        return self.extension_path / "static"

    def get_templates_path(self) -> Path:
        """Returns the path to the extension's templates."""
        return self.extension_path / "templates"
