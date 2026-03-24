# src/pclink/core/exceptions.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

"""Custom exceptions for PCLink application"""


class PCLinkError(Exception):
    """Base exception for PCLink application"""


class ServerError(PCLinkError):
    """Server-related errors"""


class ConfigurationError(PCLinkError):
    """Configuration-related errors"""


class SecurityError(PCLinkError):
    """Security-related errors"""


class FileOperationError(PCLinkError):
    """File operation errors"""


class NetworkError(PCLinkError):
    """Network-related errors"""
