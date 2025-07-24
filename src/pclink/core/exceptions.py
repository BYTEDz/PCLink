"""Custom exceptions for PCLink application"""


class PCLinkError(Exception):
    """Base exception for PCLink application"""

    pass


class ServerError(PCLinkError):
    """Server-related errors"""

    pass


class ConfigurationError(PCLinkError):
    """Configuration-related errors"""

    pass


class SecurityError(PCLinkError):
    """Security-related errors"""

    pass


class FileOperationError(PCLinkError):
    """File operation errors"""

    pass


class NetworkError(PCLinkError):
    """Network-related errors"""

    pass
