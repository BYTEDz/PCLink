# src/pclink/core/update_checker.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import json
import logging
import threading
import time
from typing import Optional, Tuple
from urllib.parse import urljoin

import requests
from packaging import version

from .version import __version__

log = logging.getLogger(__name__)

class UpdateChecker:
    """Handles checking for application updates from GitHub releases."""
    
    def __init__(self, repo_owner: str = "BYTEDz", repo_name: str = "PCLink"):
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.github_api_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/releases/latest"
        self.current_version = __version__
        self._last_check_time = 0
        self._check_interval = 3600  # Check every hour
        self._latest_release_info = None
        
    def check_for_updates(self, timeout: int = 10) -> Optional[dict]:
        """
        Check GitHub for the latest release.
        
        Args:
            timeout: Request timeout in seconds
            
        Returns:
            dict with update info if newer version available, None otherwise
        """
        try:
            log.debug(f"Checking for updates from: {self.github_api_url}")
            
            headers = {
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": f"PCLink/{self.current_version}"
            }
            
            response = requests.get(
                self.github_api_url,
                headers=headers,
                timeout=timeout
            )
            response.raise_for_status()
            
            release_data = response.json()
            latest_version = release_data.get("tag_name", "").lstrip("v")
            
            if not latest_version:
                log.warning("No version tag found in latest release")
                return None
                
            # Compare versions
            if self._is_newer_version(latest_version, self.current_version):
                update_info = {
                    "version": latest_version,
                    "tag_name": release_data.get("tag_name"),
                    "name": release_data.get("name"),
                    "body": release_data.get("body", ""),
                    "html_url": release_data.get("html_url"),
                    "published_at": release_data.get("published_at"),
                    "assets": release_data.get("assets", [])
                }
                
                self._latest_release_info = update_info
                log.info(f"New version available: {latest_version} (current: {self.current_version})")
                return update_info
            else:
                log.debug(f"No updates available. Latest: {latest_version}, Current: {self.current_version}")
                return None
                
        except requests.exceptions.RequestException as e:
            log.warning(f"Failed to check for updates: {e}")
            return None
        except Exception as e:
            log.error(f"Unexpected error checking for updates: {e}")
            return None
    
    def _is_newer_version(self, latest: str, current: str) -> bool:
        """Compare version strings using semantic versioning."""
        try:
            return version.parse(latest) > version.parse(current)
        except Exception as e:
            log.warning(f"Error comparing versions '{latest}' vs '{current}': {e}")
            return False
    
    def should_check_for_updates(self) -> bool:
        """Check if enough time has passed since last update check."""
        current_time = time.time()
        return (current_time - self._last_check_time) >= self._check_interval
    
    def check_for_updates_async(self, callback=None):
        """
        Check for updates in a background thread.
        
        Args:
            callback: Function to call with update info (or None if no updates)
        """
        def _check():
            self._last_check_time = time.time()
            update_info = self.check_for_updates()
            if callback:
                callback(update_info)
        
        thread = threading.Thread(target=_check, daemon=True)
        thread.start()
    
    def get_download_url(self, asset_pattern: str = None) -> Optional[str]:
        """
        Get download URL for the latest release.
        
        Args:
            asset_pattern: Pattern to match asset name (e.g., ".exe", ".msi")
            
        Returns:
            Download URL or None if not found
        """
        if not self._latest_release_info:
            return None
            
        assets = self._latest_release_info.get("assets", [])
        
        if asset_pattern:
            # Find asset matching pattern
            for asset in assets:
                if asset_pattern.lower() in asset.get("name", "").lower():
                    return asset.get("browser_download_url")
        
        # Return first asset if no pattern specified
        if assets:
            return assets[0].get("browser_download_url")
            
        # Fallback to release page
        return self._latest_release_info.get("html_url")