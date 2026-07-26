# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

import gettext
import logging
import re
import socket
from pathlib import Path

from .exceptions import SecurityError, ValidationError

log = logging.getLogger(__name__)
_ = gettext.gettext


def validate_port(port: int) -> int:
    """Ensure port is within the ephemeral/user range."""
    if not 1024 <= port <= 65535:
        raise ValidationError(
            _("Port must be between 1024 and 65535, got {port}").format(port=port)
        )
    return port


def validate_ip_address(ip: str) -> str:
    """Ensure string is a valid IPv4 address."""
    try:
        socket.inet_aton(ip)
        return ip
    except socket.error:
        raise ValidationError(_("Invalid IP address format: {ip}").format(ip=ip))


def validate_api_key(api_key: str) -> str:
    """
    Validates the API key. It must be a valid UUID.
    """
    if not api_key:
        raise ValidationError(_("API key cannot be empty."))

    uuid_pattern = re.compile(r"^[a-fA-F0-9]{8}-([a-fA-F0-9]{4}-){3}[a-fA-F0-9]{12}$")

    if not uuid_pattern.match(api_key):
        raise ValidationError(
            _(
                "API key is not a valid UUID. Expected: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
            )
        )

    return api_key


def validate_file_path(path: str, must_exist: bool = False) -> Path:
    """Security guard for path traversal and existence."""
    if not path or ".." in Path(path).parts:
        raise SecurityError(
            _("Potentially unsafe path provided: {path}").format(path=path)
        )

    try:
        path_obj = Path(path).resolve()

        if must_exist and not path_obj.exists():
            raise ValidationError(
                _("Required path does not exist: {path_obj}").format(path_obj=path_obj)
            )

        return path_obj
    except Exception as e:
        raise ValidationError(_("Invalid path: {error}").format(error=e)) from e


def validate_filename(filename: str) -> str:
    """Validates a filename for security to prevent traversal and invalid characters."""
    if not filename or not filename.strip():
        raise ValidationError(_("Filename cannot be empty."))

    if "/" in filename or "\\" in filename:
        raise ValidationError(_("Filename cannot contain path separators."))

    if any(c in filename for c in r':*?"<>|'):
        raise ValidationError(
            _("Filename '{filename}' contains invalid characters.").format(
                filename=filename
            )
        )

    if len(filename) > 255:
        raise ValidationError(_("Filename is too long (max 255 characters)."))

    return filename


def sanitize_log_input(input_str: str, max_length: int = 256) -> str:
    """Scrub untrusted strings for log safety."""
    if not isinstance(input_str, str):
        input_str = str(input_str)

    sanitized = re.sub(r"[\n\r\t\x00-\x1f\x7f-\x9f]", " ", input_str)

    return sanitized[:max_length]
