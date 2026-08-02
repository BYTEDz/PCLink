# src/pclink/core/extension_base.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import gettext
import logging
from abc import ABC
from pathlib import Path
from typing import Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

_ = gettext.gettext


class ExtensionWidgetModel(BaseModel):
    id: str
    display_name: str
    ui_entry: str
    width: int = 1
    height: int = 1
    refresh_ms: int = 0


class UICapabilities(BaseModel):
    allow_fullscreen: bool = False
    allow_touchpad_overlay: bool = False
    allow_keyboard: bool = False
    allow_mouse: bool = False
    allow_rotate: bool = False
    prevent_sleep: bool = False
    orientation: Optional[str] = "auto"


class ExtensionMetadata(BaseModel):
    name: str
    display_name: str
    version: str
    description: str
    author: str
    pclink_version: str
    entry_point: Optional[str] = None
    ui_entry: Optional[str] = None
    permissions: List[str] = []
    enabled: bool = True
    supported_platforms: List[str] = ["windows", "linux", "darwin"]
    supported_architectures: List[str] = ["x86_64", "amd64", "arm64", "aarch64"]
    supported_distros: List[str] = []
    icon: Optional[str] = None
    theme_aware_icon: bool = False
    category: str = "Utility"
    min_server_version: str = "1.0.0"
    ui_capabilities: UICapabilities = UICapabilities()
    dashboard_widgets: List[ExtensionWidgetModel] = []
    requirements_file: Optional[str] = None
    isolated_process: bool = True  # Full process isolation enabled by default


class ExtensionBase(ABC):
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
        self._venv_path: Optional[Path] = None

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
        if (
            self.metadata.name not in manager.extensions
            and self.metadata.name not in manager.isolated_processes
        ):
            raise HTTPException(
                status_code=410,
                detail=_("Extension '{name}' has been unloaded.").format(
                    name=self.metadata.name
                ),
            )

        if not self.metadata.enabled:
            raise HTTPException(
                status_code=403,
                detail=_("Extension '{name}' is currently disabled.").format(
                    name=self.metadata.name
                ),
            )

    def initialize(self) -> Union[bool, "CoroutineType"]:
        """Called when the extension is enabled. Optional for extensions."""
        return True

    def cleanup(self) -> Union[None, "CoroutineType"]:
        """Called when the extension is disabled or removed. Optional for extensions."""
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

    @property
    def venv_path(self) -> Optional[Path]:
        """Returns the path to the extension's virtual environment, if created."""
        return self._venv_path

    @property
    def has_venv(self) -> bool:
        """Returns True if this extension has a virtual environment."""
        return self._venv_path is not None and self._venv_path.exists()


class StaticExtension(ExtensionBase):
    """Extension type for HTML/JS/CSS-only extensions with no Python backend logic."""

    def initialize(self) -> bool:
        return True

    def cleanup(self) -> None:
        pass


CoroutineType = "Coroutine"
