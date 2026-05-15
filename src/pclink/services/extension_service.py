# src/pclink/services/extension_service.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
from typing import Any, Dict
from pathlib import Path

from ..core.config import config_manager
from ..core.extension_manager import ExtensionManager, DANGEROUS_PERMISSIONS

log = logging.getLogger(__name__)


class ExtensionService:
    """Service wrapper for ExtensionManager with additional business logic."""

    def __init__(self):
        self.manager = ExtensionManager()

    def _ensure_extensions_enabled(self):
        """Helper to enforce global extension enablement policy."""
        if not config_manager.get("allow_extensions", False):
            raise PermissionError("Extension system is globally disabled.")

    def _serialize_metadata(self, metadata: Any) -> Dict[str, Any]:
        """Safely serialize Pydantic models across v1/v2."""
        if hasattr(metadata, "model_dump"):
            return metadata.model_dump()
        return metadata.dict()

    def list_extensions(self) -> Dict[str, Any]:
        """
        Returns a snapshot of all discovered and loaded extensions.
        Strictly read-only; does not attempt to mutate or load state.
        """
        enabled_globally = config_manager.get("allow_extensions", False)
        discovered = self.manager.discover_extensions()
        all_exts = []

        for eid in discovered:
            try:
                meta = self.manager.get_manifest(eid)
                if not meta:
                    continue

                is_loaded = eid in self.manager.extensions
                ext = self.manager.get_extension(eid)

                # Use runtime metadata if loaded, fallback to manifest dictionary
                response_meta = self._serialize_metadata(ext.metadata) if ext else meta

                # Inject runtime state
                response_meta["id"] = eid
                response_meta["is_loaded"] = is_loaded

                # Security flags
                perms = response_meta.get("permissions", [])
                response_meta["has_dangerous_perms"] = any(
                    p in DANGEROUS_PERMISSIONS for p in perms
                )
                response_meta["user_approved"] = not response_meta.get(
                    "security_consent_needed", False
                )

                # Fallback: ensure dashboard_widgets is always present
                if "dashboard_widgets" not in response_meta:
                    response_meta["dashboard_widgets"] = []

                all_exts.append(response_meta)

            except Exception as e:
                log.error(f"Error processing extension '{eid}': {e}", exc_info=True)

        return {"extensions_enabled": enabled_globally, "extensions": all_exts}

    def install(self, zip_path: Path) -> bool:
        self._ensure_extensions_enabled()
        return self.manager.install_extension(zip_path)

    def uninstall(self, eid: str) -> bool:
        self._ensure_extensions_enabled()
        return self.manager.delete_extension(eid)

    def toggle(self, eid: str, enabled: bool) -> bool:
        self._ensure_extensions_enabled()
        return self.manager.toggle_extension(eid, enabled)


# Global instance
extension_service = ExtensionService()
