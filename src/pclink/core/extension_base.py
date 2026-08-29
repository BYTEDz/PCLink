# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import gettext
import logging
from abc import ABC
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

_ = gettext.gettext

KNOWN_PERMISSIONS = {
    "system.exec",
    "fs.read",
    "fs.write",
    "fs.all",
    "net.fetch",
    "storage.local",
    "input.inject",
    "media.control",
    "media.read",
    "power.control",
    "notifications",
}

DANGEROUS_PERMISSIONS = {
    "system.exec",
    "fs.write",
    "fs.all",
    "input.inject",
    "power.control",
}


class ExtensionType(str, Enum):
    WEB = "web"
    PROCESS = "process"


class NativeCardControl(BaseModel):
    type: Literal["button", "toggle", "slider"]
    label: str
    action: str
    param_key: Optional[str] = None


class NativeCardLayout(BaseModel):
    icon: Optional[str] = "package"
    primary_text: str = ""
    status_badge: Optional[str] = None
    progress: Optional[float] = None
    controls: List[NativeCardControl] = Field(default_factory=list)


class ExtensionWidgetModel(BaseModel):
    id: str
    title: str
    type: Literal["native_card", "webview"] = "webview"
    size: Dict[str, int] = Field(default_factory=lambda: {"w": 1, "h": 1})
    entry_point: Optional[str] = None
    refresh_ms: int = 0
    layout: Optional[NativeCardLayout] = None


class ExtensionView(BaseModel):
    id: str
    title: str
    icon: Optional[str] = "grid"
    entry_point: str
    target: Literal["main_tab", "side_panel", "modal"] = "main_tab"


class MacroActionParameter(BaseModel):
    name: str
    type: Literal["string", "number", "boolean", "select"] = "string"
    required: bool = True
    default_value: Optional[Any] = None
    options: List[Dict[str, str]] = Field(default_factory=list)


class MacroActionContribution(BaseModel):
    id: str
    name: str
    description: Optional[str] = ""
    parameters: List[MacroActionParameter] = Field(default_factory=list)


class ContributionPoints(BaseModel):
    views: List[ExtensionView] = Field(default_factory=list)
    dashboard_widgets: List[ExtensionWidgetModel] = Field(default_factory=list)
    macro_actions: List[MacroActionContribution] = Field(default_factory=list)


class ResourceLimits(BaseModel):
    max_memory_mb: int = 256
    max_cpu_percent: int = 50
    execution_timeout_sec: int = 30


class BackendConfig(BaseModel):
    runtime: Literal["none", "python", "binary", "node"] = "none"
    entry_point: Optional[str] = None
    isolated: bool = True
    requirements_file: Optional[str] = None
    resource_limits: ResourceLimits = Field(default_factory=ResourceLimits)


class UICapabilities(BaseModel):
    allow_fullscreen: bool = False
    allow_keyboard: bool = False
    allow_mouse: bool = False
    prevent_sleep: bool = False
    orientation: Optional[str] = "auto"


class ExtensionMetadata(BaseModel):
    manifest_version: Literal[2] = 2
    id: str
    name: str
    version: str
    description: str = ""
    author: str = ""
    pclink_version: Optional[str] = None
    icon: Optional[str] = None
    theme_aware_icon: bool = True
    category: str = "Utility"
    permissions: List[str] = Field(default_factory=list)
    declared_permissions: List[str] = Field(default_factory=list)
    supported_platforms: List[str] = Field(
        default_factory=lambda: ["windows", "linux", "darwin"]
    )
    supported_architectures: List[str] = Field(
        default_factory=lambda: ["x86_64", "amd64", "arm64", "aarch64"]
    )
    supported_distros: List[str] = Field(default_factory=list)
    ui_capabilities: UICapabilities = Field(default_factory=UICapabilities)
    contributes: ContributionPoints = Field(default_factory=ContributionPoints)
    backend: BackendConfig = Field(default_factory=BackendConfig)

    def model_post_init(self, __context: Any) -> None:
        if not self.declared_permissions:
            self.declared_permissions = list(self.permissions)


class ExtensionBase(ABC):
    def __init__(
        self,
        metadata: ExtensionMetadata,
        extension_path: Path,
        config: Dict[str, Any],
        context: Any = None,
    ):
        self.metadata = metadata
        self.extension_path = extension_path
        self.config = config
        self.context = context
        self.router = APIRouter(dependencies=[Depends(self._verify_active)])
        self.logger = logging.getLogger(f"pclink.extensions.{metadata.id}")
        self._venv_path: Optional[Path] = None

    async def _verify_active(self) -> None:
        from .extension_manager import ExtensionManager

        manager = ExtensionManager()
        if not manager.is_extension_active(self.metadata.id):
            raise HTTPException(
                status_code=410,
                detail=_("Extension '{name}' has been unloaded or is inactive.").format(
                    name=self.metadata.id
                ),
            )

    def initialize(self) -> Union[bool, Any]:
        return True

    def cleanup(self) -> Union[None, Any]:
        pass

    def get_routes(self) -> APIRouter:
        return self.router

    @property
    def venv_path(self) -> Optional[Path]:
        return self._venv_path

    @property
    def has_venv(self) -> bool:
        return self._venv_path is not None and self._venv_path.exists()


class StaticExtension(ExtensionBase):
    def initialize(self) -> bool:
        return True

    def cleanup(self) -> None:
        pass
