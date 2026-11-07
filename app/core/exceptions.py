"""Typed exceptions for Trakt-Letterboxd Sync."""

class SyncError(Exception):
    """Base exception for all sync service errors."""
    def __init__(self, message: str, status_code: int = 400, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class ProviderAuthError(SyncError):
    """Authentication or authorization failure with an external provider."""
    def __init__(self, message: str = "Provider authentication failed", details: dict | None = None):
        super().__init__(message, status_code=401, details=details)


class ProviderRateLimitError(SyncError):
    """Provider rate limit encountered."""
    def __init__(self, message: str = "Provider rate limit exceeded", retry_after: int | None = None, details: dict | None = None):
        details = details or {}
        if retry_after is not None:
            details["retry_after"] = retry_after
        super().__init__(message, status_code=429, details=details)
        self.retry_after = retry_after


class ProviderUnavailableError(SyncError):
    """External provider is temporarily down or timed out."""
    def __init__(self, message: str = "Provider unavailable", details: dict | None = None):
        super().__init__(message, status_code=503, details=details)


class MovieMatchError(SyncError):
    """Movie identity could not be resolved with sufficient confidence."""
    def __init__(self, message: str = "Unable to resolve movie identity", details: dict | None = None):
        super().__init__(message, status_code=422, details=details)


class SyncConflictError(SyncError):
    """Unresolvable conflicting changes detected between providers."""
    def __init__(self, message: str = "Sync conflict detected", details: dict | None = None):
        super().__init__(message, status_code=409, details=details)


class ImportFormatError(SyncError):
    """Malformed CSV data or unsupported import format."""
    def __init__(self, message: str = "Invalid import file format", details: dict | None = None):
        super().__init__(message, status_code=400, details=details)
