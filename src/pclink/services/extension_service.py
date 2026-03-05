# src/pclink/services/extension_service.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
import yaml
from pathlib import Path
from typing import List, Dict, Optional
from ..core.extension_manager import ExtensionManager
from ..core.config import config_manager

log = logging.getLogger(__name__)

class ExtensionService:
    """Service wrapper for ExtensionManager with additional business logic."""

    def __init__(self):
        self.manager = ExtensionManager()

    def list_extensions(self) -> Dict:
        enabled_globally = config_manager.get("allow_extensions", False)
        
        # SELF-HEALING: If we have zero loaded exts but files on disk, try discovery again
        # This handles 'fresh boot' cases where startup load might have been too early
        try:
            if not self.manager.extensions and self.manager.extensions_path.exists() and any(self.manager.extensions_path.iterdir()):
                 self.manager.discover_extensions()
        except: pass

        discovered = self.manager.discover_extensions()
        all_exts = []

        for eid in discovered:
            manifest_p = self.manager.extensions_path / eid / "extension.yaml"
            try:
                with open(manifest_p, 'r', encoding='utf-8') as f:
                    meta = yaml.safe_load(f)
                
                ext = self.manager.get_extension(eid)
                if ext:
                    all_exts.append(ext.metadata.dict())
                    continue

                if enabled_globally and meta.get('enabled', True):
                    if self.manager.load_extension(eid):
                        ext = self.manager.get_extension(eid)
                        if ext:
                            all_exts.append(ext.metadata.dict())
                            continue
                        else:
                            log.warning(f"Extension '{eid}' loaded but not found in registry")
                    else:
                        log.warning(f"Extension '{eid}' failed to load")
                
                # Fallback: ensure dashboard_widgets is always present in raw meta
                if 'dashboard_widgets' not in meta:
                    meta['dashboard_widgets'] = []
                # Use manifest state for 'enabled' to keep UI in sync with user intent
                meta['enabled'] = meta.get('enabled', True)
                all_exts.append(meta)
            except Exception as e:
                log.error(f"Error processing extension '{eid}': {e}")
                continue
        
        return {"extensions_enabled": enabled_globally, "extensions": all_exts}

    def install(self, zip_path: Path) -> bool:
        if not config_manager.get("allow_extensions", False):
            raise PermissionError("Extension system disabled")
        return self.manager.install_extension(zip_path)

    def uninstall(self, eid: str) -> bool:
        if not config_manager.get("allow_extensions", False):
            raise PermissionError("Extension system disabled")
        return self.manager.delete_extension(eid)

    def toggle(self, eid: str, enabled: bool) -> bool:
        if not config_manager.get("allow_extensions", False):
            raise PermissionError("Extension system disabled")
        return self.manager.toggle_extension(eid, enabled)

# Global instance
extension_service = ExtensionService()
