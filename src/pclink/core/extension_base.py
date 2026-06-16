# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel


class ExtensionWidgetModel(BaseModel):
    id: str
    display_name: str
    ui_entry: str  # Path to the widget HTML file
    width: int = 1  # 1: normal, 2: wide
    height: int = 1  # 1: normal, 2: tall
    refresh_ms: int = 0  # 0 means handled by widget JS


class UICapabilities(BaseModel):
    allow_fullscreen: bool = False
    allow_touchpad_overlay: bool = False
    allow_keyboard: bool = False
    allow_mouse: bool = False
    allow_rotate: bool = False
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
    supported_distros: List[str] = []  # Optional: e.g. ["arch", "ubuntu"]
    icon: Optional[str] = None
    theme_aware_icon: bool = False
    category: str = "Utility"
    min_server_version: str = "1.0.0"
    ui_capabilities: UICapabilities = UICapabilities()
    dashboard_widgets: List[ExtensionWidgetModel] = []
    # Venv support: path to requirements.txt relative to extension root
    requirements_file: Optional[str] = None


class ExtensionBase(ABC):
    # Class-level flag to detect async implementations
    _is_async: bool = False

    def __init__(
        self,
        metadata: ExtensionMetadata,
        extension_path: Path,
        config: Dict,
        context=None,
    ):
        self.metadata = metadata
        self.extension_path = extension_path
        self.config = config
        self.context = context
        self.router = APIRouter(dependencies=[Depends(self._verify_active)])
        self.logger = logging.getLogger(f"pclink.extensions.{metadata.name}")
        # Store venv path once created
        self._venv_path: Optional[Path] = None

        # Detect async implementation
        self._check_async()

    def _check_async(self):
        """Detect if subclass implements async initialize/cleanup."""
        init_method = getattr(type(self), "initialize", None)
        cleanup_method = getattr(type(self), "cleanup", None)

        import inspect

        if init_method and inspect.iscoroutinefunction(init_method):
            ExtensionBase._is_async = True
        elif cleanup_method and inspect.iscoroutinefunction(cleanup_method):
            ExtensionBase._is_async = True

    async def _verify_active(self):
        """Internal dependency to prevent requests hitting unloaded extensions."""
        from pclink.core.extension_manager import ExtensionManager

        manager = ExtensionManager()
        if self.metadata.name not in manager.extensions:
            raise HTTPException(
                status_code=410,
                detail=f"Extension '{self.metadata.name}' has been unloaded.",
            )

        if not self.metadata.enabled:
            raise HTTPException(
                status_code=403,
                detail=f"Extension '{self.metadata.name}' is currently disabled.",
            )

    @abstractmethod
    def initialize(self) -> Union[bool, "CoroutineType"]:
        """Called when the extension is enabled. Can be sync or async."""

    @abstractmethod
    def cleanup(self) -> Union[None, "CoroutineType"]:
        """Called when the extension is disabled or removed. Can be sync or async."""

    def get_routes(self) -> APIRouter:
        """Returns the APIRouter for the extension."""
        return self.router

    def get_static_path(self) -> Path:
        """Returns the path to the extension's static files."""
        return self.extension_path / "static"

    def get_templates_path(self) -> Path:
        """Returns the path to the extension's templates."""
        return self.extension_path / "templates"

    @property
    def venv_path(self) -> Optional[Path]:
        """Returns the path to the extension's virtual environment, if created."""
        return self._venv_path

    @property
    def has_venv(self) -> bool:
        """Returns True if this extension has a virtual environment."""
        return self._venv_path is not None and self._venv_path.exists()


# Type hint for coroutine (forward reference to avoid import issues)
CoroutineType = "Coroutine"
