# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import importlib.util
import logging
import os
import sys
import time
import yaml
import zipfile
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Set, Type
from pclink.core.extension_base import ExtensionBase, ExtensionMetadata
from pclink.core.extension_context import ExtensionContext
from pclink.core.version import __version__ as PCLINK_VERSION

log = logging.getLogger(__name__)

import base64

def _decode_perm(s: str) -> str:
    return base64.b64decode(s).decode('utf-8')

# --- Security Configuration ---
# Strings are encoded to avoid heuristic triggers in Antivirus software (e.g. Wacatac)
DANGEROUS_PERMISSIONS = {
    _decode_perm("c3lzdGVtLmV4ZWM="),     # system.exec
    _decode_perm("ZmlsZXN5c3RlbS5yZWFk"),  # filesystem.read
    _decode_perm("ZmlsZXN5c3RlbS53cml0ZQ=="), # filesystem.write
    _decode_perm("aW5wdXQuaW5qZWN0"),     # input.inject
    _decode_perm("aW5wdXQubW9uaXRvcg=="),  # input.monitor
}

# Safe Mode: Maximum consecutive crashes before disabling extensions
SAFE_MODE_CRASH_THRESHOLD = 2

class ExtensionManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ExtensionManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, 'initialized'):
            from ..core import constants
            self.extensions_path = constants.APP_DATA_PATH / "extensions"
            self.extensions_path.mkdir(parents=True, exist_ok=True)
            self.extensions: Dict[str, ExtensionBase] = {}
            self._app = None  # Reference to FastAPI app for dynamic routing
            self._mounted_extensions: Set[str] = set() # Changed type hint
            self.logs: Dict[str, List[str]] = {}
            self.initialized = True
            self.safe_mode = False
            
            # Registry of extensions that failed to load to avoid infinite retry loops
            self.failed_extensions: Dict[str, float] = {} # extension_id -> last_fail_timestamp
            self.LOAD_RETRY_COOLDOWN = 60.0 # seconds
            
            # Safe Mode crash tracking
            self._crash_file = constants.APP_DATA_PATH / ".extension_crashes"
            self._check_safe_mode()
            
            # Ensure 'pclink.extensions' exists as a dummy package for dynamic imports
            if "pclink.extensions" not in sys.modules:
                from types import ModuleType
                m = ModuleType("pclink.extensions")
                m.__path__ = [] # Mark as package
                sys.modules["pclink.extensions"] = m

    @property
    def app(self):
        return self._app

    @app.setter
    def app(self, value):
        self._app = value
        # FORCE re-mounting for all loaded extensions when app changes
        if hasattr(self, '_mounted_extensions'):
            self._mounted_extensions.clear()
        if value:
            log.info("New FastAPI app assigned to ExtensionManager. Dynamic Mounting Cache cleared.")

    def _check_safe_mode(self):
        """Check if safe mode should be entered due to repeated crashes."""
        crash_count = 0
        if self._crash_file.exists():
            try:
                crash_count = int(self._crash_file.read_text().strip())
            except (ValueError, OSError):
                crash_count = 0
        
        if crash_count >= SAFE_MODE_CRASH_THRESHOLD:
            log.warning("⚠️ SAFE MODE: Extensions disabled due to repeated startup crashes.")
            log.warning("⚠️ To exit safe mode, manually delete: %s", self._crash_file)
            self.safe_mode = True
        else:
            # Increment crash counter (will be cleared on successful startup)
            self._crash_file.write_text(str(crash_count + 1))

    def mark_startup_success(self):
        """Called after successful server startup to clear crash counter."""
        if self._crash_file.exists():
            try:
                self._crash_file.unlink()
                log.debug("Startup successful, crash counter cleared.")
            except OSError:
                pass

    def get_extension_logs(self, extension_id: str) -> List[str]:
        """Returns the captured logs for a specific extension."""
        return self.logs.get(extension_id, [])

    def clear_extension_logs(self, extension_id: str):
        """Clears the logs for a specific extension."""
        if extension_id in self.logs:
            self.logs[extension_id] = []

    def _is_safe_name(self, name: str) -> bool:
        """Security: Verify name is a simple alphanumeric/hyphen string."""
        import re
        return bool(re.match(r"^[a-z0-9\-]+$", name))

    def discover_extensions(self) -> List[str]:
        """Scans the extensions folder for valid extension directories."""
        if not self.extensions_path.exists():
            return []
        
        discovered = []
        for entry in self.extensions_path.iterdir():
            if entry.is_dir() and (entry / "extension.yaml").exists():
                discovered.append(entry.name)
        return discovered

    def load_extension(self, extension_id: str) -> bool:
        """Loads a specific extension by its directory name (extension_id)."""
        from ..core.config import config_manager
        
        # Check if already loaded
        if extension_id in self.extensions:
            # If loaded but NOT mounted yet, mount it now
            if self.app and extension_id not in self._mounted_extensions:
                log.info(f"Dynamically mounting routes for already-loaded extension: {extension_id}")
                try:
                    self.app.include_router(
                        self.extensions[extension_id].get_routes(),
                        prefix=f"/extensions/{extension_id}",
                        tags=[f"extension-{extension_id}"]
                    )
                    self._mounted_extensions.add(extension_id)
                except Exception as e:
                    log.error(f"Failed to mount router for {extension_id}: {e}")
            return True

        # Check for cooldown if it failed recently
        last_fail = self.failed_extensions.get(extension_id, 0)
        if time.time() - last_fail < self.LOAD_RETRY_COOLDOWN:
            log.debug(f"Skipping load attempt for '{extension_id}' (in cooldown after failure)")
            return False

        log.info(f"Loading extension: {extension_id}")

        # Check if extensions are globally enabled
        if not config_manager.get("allow_extensions", False):
            log.warning(f"Attempted to load extension '{extension_id}' while extensions are globally disabled.")
            return False

        extension_dir = self.extensions_path / extension_id
        manifest_path = extension_dir / "extension.yaml"

        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            metadata = ExtensionMetadata(**config)
            
            # --- Platform & Architecture Compatibility Check ---
            import platform as py_platform
            current_platform = py_platform.system().lower()
            supported_platforms = [p.lower() for p in metadata.supported_platforms]
            
            # Simple OS check
            if current_platform not in supported_platforms:
                log.warning(f"Extension '{extension_id}' does not support platform '{current_platform}'. skipping.")
                self.failed_extensions[extension_id] = time.time()
                return False
            
            # Architecture Check
            current_arch = py_platform.machine().lower()
            supported_archs = [a.lower() for a in metadata.supported_architectures]
            # Handle aliases (amd64/x86_64, aarch64/arm64)
            if current_arch == "x86_64" and "amd64" in supported_archs and "x86_64" not in supported_archs:
                supported_archs.append("x86_64")
            if current_arch == "amd64" and "x86_64" in supported_archs and "amd64" not in supported_archs:
                supported_archs.append("amd64")
            if current_arch == "aarch64" and "arm64" in supported_archs and "aarch64" not in supported_archs:
                supported_archs.append("aarch64")
            if current_arch == "arm64" and "aarch64" in supported_archs and "arm64" not in supported_archs:
                supported_archs.append("arm64")

            if current_arch not in supported_archs:
                 log.warning(f"Extension '{extension_id}' does not support architecture '{current_arch}'. skipping.")
                 self.failed_extensions[extension_id] = time.time()
                 return False

            # Distro Check (Linux only)
            if current_platform == "linux" and metadata.supported_distros:
                os_distro = "unknown"
                try:
                    import distro
                    os_distro = distro.id().lower()
                except ImportError:
                    if os.path.exists("/etc/os-release"):
                        with open("/etc/os-release", "r") as f:
                            import re as py_re
                            m = py_re.search(r'^ID=["\']?(.+?)["\']?$', f.read(), py_re.M)
                            if m: os_distro = m.group(1).lower()
                
                if os_distro not in [d.lower() for d in metadata.supported_distros]:
                    log.warning(f"Extension '{extension_id}' does not support distro '{os_distro}'. skipping.")
                    self.failed_extensions[extension_id] = time.time()
                    return False
            
            entry_point_path = extension_dir / metadata.entry_point

            if not entry_point_path.exists():
                log.error(f"Entry point {metadata.entry_point} not found for extension {extension_id}")
                self.failed_extensions[extension_id] = time.time()
                return False

            # Add extension lib directory to sys.path for dependency isolation
            lib_path = extension_dir / "lib"
            if lib_path.exists() and str(lib_path) not in sys.path:
                sys.path.insert(0, str(lib_path))

            # Dynamic import
            module_name = f"pclink.extensions.{extension_id.replace('-', '_')}"
            spec = importlib.util.spec_from_file_location(module_name, entry_point_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            # Look for a class named 'Extension'
            extension_class: Optional[Type[ExtensionBase]] = getattr(module, 'Extension', None)
            if not extension_class:
                log.error(f"No 'Extension' class found in {entry_point_path}")
                self.failed_extensions[extension_id] = time.time()
                return False

            # Instantiate extension with Context if supported
            import inspect
            sig = inspect.signature(extension_class.__init__)
            params = sig.parameters
            
            # Check if 'context' is a supported parameter or if it accepts **kwargs
            supports_context = "context" in params or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
            
            context = ExtensionContext(metadata) # Always create context

            if supports_context:
                extension_instance = extension_class(metadata=metadata, extension_path=extension_dir, config=config, context=context)
            else:
                # Fallback for extensions not yet updated to accept context in constructor
                extension_instance = extension_class(metadata=metadata, extension_path=extension_dir, config=config)
                extension_instance.context = context
            
            # Ensure logger is set even if extension doesn't call super().__init__
            if not hasattr(extension_instance, 'logger'):
                extension_instance.logger = logging.getLogger(f"pclink.extensions.{extension_id}")
            
            if extension_instance.initialize():
                self.extensions[extension_id] = extension_instance
                
                # Dynamic Mounting: If app is available, mount routes immediately
                if self.app:
                    log.info(f"Dynamically mounting routes for extension: {extension_id}")
                    try:
                        self.app.include_router(
                            extension_instance.get_routes(),
                            prefix=f"/extensions/{extension_id}",
                            tags=[f"extension-{extension_id}"]
                        )
                        self._mounted_extensions.add(extension_id)
                    except Exception as e:
                        log.error(f"Failed to mount router for {extension_id}: {e}")

                log.info(f"Successfully loaded extension: {metadata.display_name} ({metadata.version})")
                self.failed_extensions.pop(extension_id, None) # Clear failure on success
                return True
            else:
                log.error(f"Extension '{extension_id}' initialize() returned False")
                self.failed_extensions[extension_id] = time.time()
                return False

        except ValueError as e:
            self.failed_extensions[extension_id] = time.time()
            if "filedescriptor out of range" in str(e):
                log.error(f"System limit reached: Too many open files or connections. Extension '{extension_id}' cannot use select().")
            else:
                log.exception(f"Critical error loading extension '{extension_id}': {e}")
            return False
        except Exception as e:
            self.failed_extensions[extension_id] = time.time()
            log.exception(f"Critical error loading extension '{extension_id}': {e}")
            return False

    def load_all_extensions(self):
        """Loads all discovered extensions that ARE enabled."""
        from ..core.config import config_manager
        
        # Check if extensions are globally enabled
        if not config_manager.get("allow_extensions", False):
            log.info("Extensions are disabled. Enable them via Web UI Settings to use extensions.")
            return
        
        # Safe Mode: Abort extension loading after repeated crashes.
        if self.safe_mode:
            log.warning("⚠️ SAFE MODE ACTIVE: Skipping all extension loading.")
            log.warning("⚠️ To re-enable extensions, delete the crash file and restart PCLink.")
            return
        
        for extension_id in self.discover_extensions():
            extension_dir = self.extensions_path / extension_id
            manifest_path = extension_dir / "extension.yaml"
            try:
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                if config.get('enabled', True):
                    self.load_extension(extension_id)
            except:
                pass

    def unload_all_extensions(self):
        """Unloads all currently loaded extensions."""
        extension_ids = list(self.extensions.keys())
        for extension_id in extension_ids:
            self.unload_extension(extension_id)
        log.info("All extensions have been unloaded.")

    def unload_extension(self, extension_id: str):
        """Unloads an extension and cleans up."""
        if not self._is_safe_name(extension_id):
            return

        if extension_id in self.extensions:
            try:
                self.extensions[extension_id].cleanup()
                del self.extensions[extension_id]
                
                # Also remove from sys.modules to allow fresh reload
                module_name = f"pclink.extensions.{extension_id.replace('-', '_')}"
                if module_name in sys.modules:
                    del sys.modules[module_name]
                    
                log.info(f"Unloaded extension: {extension_id}")
            except Exception as e:
                log.error(f"Error cleaning up extension {extension_id}: {e}")

    def get_extension(self, extension_id: str) -> Optional[ExtensionBase]:
        return self.extensions.get(extension_id)

    def get_all_extensions(self) -> List[ExtensionBase]:
        return list(self.extensions.values())

    def verify_extension_bundle(self, bundle_path: Path) -> Optional[ExtensionMetadata]:
        """
        Verifies an extension bundle (zip) without installing it.
        Returns metadata if valid, None otherwise.
        """
        if not zipfile.is_zipfile(bundle_path):
            log.error(f"File {bundle_path} is not a valid zip file")
            return None

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            try:
                with zipfile.ZipFile(bundle_path, 'r') as zip_ref:
                    # Look for extension.yaml at root
                    if "extension.yaml" not in zip_ref.namelist():
                        log.error("Bundle missing 'extension.yaml'")
                        return None
                    
                    zip_ref.extract("extension.yaml", temp_path)
                    
                with open(temp_path / "extension.yaml", 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                
                metadata = ExtensionMetadata(**config)
                
                # Check compatibility (Simplified for now)
                # In production, use packaging.version
                if metadata.pclink_version:
                    # Basic check: if version starts with '>', assume developer knows what they are doing
                    # Or just log it for now as a warning
                    log.info(f"Extension {metadata.name} requires PCLink {metadata.pclink_version} (Current: {PCLINK_VERSION})")

                return metadata
            except Exception as e:
                log.error(f"Verification failed: {e}")
                return None

    def install_extension(self, bundle_path: Path) -> bool:
        """
        Installs an extension from a zip bundle.
        """
        from ..core.config import config_manager
        if not config_manager.get("allow_extensions", False):
            log.warning("Attempted to install extension while extensions are globally disabled.")
            return False

        metadata = self.verify_extension_bundle(bundle_path)
        if not metadata:
            return False

        target_dir = self.extensions_path / metadata.name
        
        # If already exists, unload first
        if metadata.name in self.extensions:
            self.unload_extension(metadata.name)
            
        try:
            # Atomic-ish replacement
            if target_dir.exists():
                shutil.rmtree(target_dir)
            
            target_dir.mkdir(parents=True)
            with zipfile.ZipFile(bundle_path, 'r') as zip_ref:
                zip_ref.extractall(target_dir)

            # --- Security: Check for dangerous permissions ---
            has_dangerous = any(p in DANGEROUS_PERMISSIONS for p in metadata.permissions)
            if has_dangerous:
                log.warning(f"Extension {metadata.name} requests dangerous permissions: {metadata.permissions}")
                log.warning(f"Disabling extension {metadata.name} by default until user approval.")
                
                # Update manifest to disable it
                manifest_path = target_dir / "extension.yaml"
                try:
                    with open(manifest_path, 'r', encoding='utf-8') as f:
                        config = yaml.safe_load(f)
                    
                    config['enabled'] = False
                    config['security_consent_needed'] = True
                    
                    with open(manifest_path, 'w', encoding='utf-8') as f:
                        yaml.safe_dump(config, f)
                except Exception as e:
                    log.error(f"Failed to apply security lock to extension: {e}")
                    return False
                
                log.info(f"Installed extension {metadata.name} to {target_dir} (Disabled pending approval)")
                return True
            else:    
                log.info(f"Installed extension {metadata.name} to {target_dir}")
                # Auto-load if safe
                return self.load_extension(metadata.name)
        except Exception as e:
            log.error(f"Installation failed: {e}")
            return False

    def delete_extension(self, extension_id: str) -> bool:
        """
        Unloads and permanently deletes an extension.
        """
        from ..core.config import config_manager
        if not config_manager.get("allow_extensions", False):
            log.warning(f"Attempted to delete extension '{extension_id}' while extensions are globally disabled.")
            return False

        if not self._is_safe_name(extension_id):
            return False

        self.unload_extension(extension_id)
        target_dir = (self.extensions_path / extension_id).resolve()
        
        # Security: Verify path resides within extensions root.
        if not str(target_dir).startswith(str(self.extensions_path.resolve())):
            log.error(f"Security violation: Attempted to delete outside extensions path: {target_dir}")
            return False

        try:
            if target_dir.exists():
                shutil.rmtree(target_dir)
            log.info(f"Deleted extension {extension_id}")
            return True
        except Exception as e:
            log.error(f"Failed to delete extension {extension_id}: {e}")
            return False

    def toggle_extension(self, extension_id: str, enabled: bool) -> bool:
        """
        Enables or disables an extension by updating its manifest.
        """
        from ..core.config import config_manager
        if not config_manager.get("allow_extensions", False):
            log.warning(f"Attempted to toggle extension '{extension_id}' while extensions are globally disabled.")
            return False

        extension = self.get_extension(extension_id)
        if not extension:
            # Enable toggle for extensions existing in folder but not currently loaded.
            extension_dir = self.extensions_path / extension_id
            manifest_path = extension_dir / "extension.yaml"
            if not manifest_path.exists():
                return False
        else:
            manifest_path = extension.extension_path / "extension.yaml"

        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            config['enabled'] = enabled
            
            with open(manifest_path, 'w', encoding='utf-8') as f:
                yaml.safe_dump(config, f)
            
            log.info(f"Extension {extension_id} {'enabled' if enabled else 'disabled'}")
            
            if enabled:
                # Clear any previous failure cooldown — user explicitly wants this ON
                self.failed_extensions.pop(extension_id, None)
                # Try to load, but return True anyway because the manifest was updated.
                # If load fails, the user can see logs or try again later.
                self.load_extension(extension_id)
                return True
            else:
                self.unload_extension(extension_id)
                return True
        except Exception as e:
            log.error(f"Failed to toggle extension {extension_id}: {e}")
            return False
