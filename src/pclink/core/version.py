# src/pclink/core/version.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz


__version__ = "3.1.0"
__app_name__ = "PCLink"

class VersionInfo:
    def __init__(self, version_str):
        self.version = version_str
        self.copyright = "Copyright © 2025 Azhar Zouhir / BYTEDz"
        self.description = "Remote PC Control Server"
        self.license_info = "GNU Affero General Public License v3 or later"
        self.license = "GNU Affero General Public License v3 or later"  # Alias for license_info
        self.company = "BYTEDz"
        self.product_name = "PCLink"
        self.author = "Azhar Zouhir / BYTEDz"
        self.url = "https://github.com/BYTEDz/PCLink"

    @property
    def simple_version(self):
        """Returns the base version (e.g., '0.8.0') without any pre-release tags."""
        return self.version.split("-")[0]

    def get_windows_version_info(self):
        """
        Returns a dictionary with version parts formatted for Windows resources.
        Converts '0.8.0-hotfix2' into a valid '0.8.0.0' format.
        """
        ver_parts = self.simple_version.split('.') + ['0'] * (4 - len(self.simple_version.split('.')))
        file_version = ".".join(ver_parts[:4])
        
        return {
            "file_version": file_version,
            "product_version": file_version,
            "company_name": self.company,
            "file_description": self.description,
            "product_name": self.product_name,
            "copyright": self.copyright,
        }

version_info = VersionInfo(__version__)