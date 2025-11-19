# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import logging
import os
import re
import socket
from pathlib import Path
from typing import List, Optional

from .exceptions import SecurityError

log = logging.getLogger(__name__)


class ValidationError(ValueError):
    """Custom exception for validation-specific errors."""

    pass


def validate_port(port: int) -> int:
    """Validates that a port number is within the valid user range."""
    if not 1024 <= port <= 65535:
        raise ValidationError(f"Port must be between 1024 and 65535, got {port}")
    return port


def validate_ip_address(ip: str) -> str:
    """Validates that a string is a valid IP address."""
    try:
        socket.inet_aton(ip)
        return ip
    except socket.error:
        raise ValidationError(f"Invalid IP address format: {ip}")


def validate_api_key(api_key: str) -> str:
    """
    Validates the API key. It must be a valid UUID.
    For backward compatibility, it handles and strips the legacy 'API_KEY=' prefix.
    """
    if not api_key:
        raise ValidationError("API key cannot be empty.")

    # Handle legacy format to provide a smooth upgrade path for existing users.
    if api_key.startswith("API_KEY="):
        api_key = api_key.split("=", 1)[1]

    # The application uses UUIDs for API keys. This regex enforces that format.
    # Format: 8-4-4-4-12 hex characters.
    uuid_pattern = re.compile(r"^[a-fA-F0-9]{8}-([a-fA-F0-9]{4}-){3}[a-fA-F0-9]{12}$")

    if not uuid_pattern.match(api_key):
        raise ValidationError(
            "API key is not a valid UUID. Expected: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
        )

    return api_key


def validate_file_path(path: str, must_exist: bool = False) -> Path:
    """Validates a file path for security and existence."""
    if not path or ".." in Path(path).parts:
        raise SecurityError(f"Potentially unsafe path provided: {path}")

    try:
        path_obj = Path(path).resolve()
        # After resolving, double-check it's within a known safe directory if needed,
        # but for now, rejecting '..' is a strong first step.

        if must_exist and not path_obj.exists():
            raise ValidationError(f"Required path does not exist: {path_obj}")

        return path_obj
    except Exception as e:
        raise ValidationError(f"Invalid path: {e}") from e


def validate_filename(filename: str) -> str:
    """Validates a filename for security to prevent traversal and invalid characters."""
    if not filename or not filename.strip():
        raise ValidationError("Filename cannot be empty.")

    # Disallow path separators to prevent directory traversal.
    if "/" in filename or "\\" in filename:
        raise ValidationError("Filename cannot contain path separators.")

    # Disallow other common problematic characters.
    if any(c in filename for c in r':*?"<>|'):
        raise ValidationError(f"Filename '{filename}' contains invalid characters.")

    if len(filename) > 255:
        raise ValidationError("Filename is too long (max 255 characters).")

    return filename


def sanitize_log_input(input_str: str, max_length: int = 256) -> str:
    """Sanitizes a string before logging to prevent log injection or corruption."""
    if not isinstance(input_str, str):
        input_str = str(input_str)

    # Replace newline characters and other control characters.
    sanitized = re.sub(r"[\n\r\t\x00-\x1f\x7f-\x9f]", " ", input_str)

    return sanitized[:max_length]
