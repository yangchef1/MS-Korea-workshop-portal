"""
Validation-specific exception classes.

Use these exceptions for input validation errors that occur before
any business logic or external service calls.
"""
from .base import ValidationError


class CSVParsingError(ValidationError):
    """Failed to parse CSV file"""
    
    def __init__(self, message: str = "CSV parsing failed", row: int = None):
        super().__init__(message, "csv_file")
        self.code = "CSV_PARSING_ERROR"
        if row is not None:
            self.details["row"] = row


class MissingFieldError(ValidationError):
    """Required field is missing"""
    
    def __init__(self, message: str = "Required field missing", field: str = None):
        super().__init__(message, field)
        self.code = "MISSING_FIELD"


class InvalidFormatError(ValidationError):
    """Field has invalid format"""
    
    def __init__(self, message: str = "Invalid format", field: str = None, expected_format: str = None):
        super().__init__(message, field)
        self.code = "INVALID_FORMAT"
        if expected_format:
            self.details["expected_format"] = expected_format


class InvalidDateRangeError(ValidationError):
    """Date range is invalid"""
    
    def __init__(self, message: str = "Invalid date range"):
        super().__init__(message, "date_range")
        self.code = "INVALID_DATE_RANGE"


class FileTooLargeError(ValidationError):
    """File exceeds maximum size limit"""
    
    def __init__(self, message: str = "File too large", max_size: int = None):
        super().__init__(message, "file")
        self.code = "FILE_TOO_LARGE"
        if max_size:
            self.details["max_size_bytes"] = max_size


class UnsupportedFileTypeError(ValidationError):
    """File type is not supported"""
    
    def __init__(self, message: str = "Unsupported file type", allowed_types: list = None):
        super().__init__(message, "file")
        self.code = "UNSUPPORTED_FILE_TYPE"
        if allowed_types:
            self.details["allowed_types"] = allowed_types


class InvalidSubscriptionError(ValidationError):
    """Subscription ID is not in the allowed list."""

    def __init__(self, message: str = "Invalid subscription ID", subscription_id: str = None):
        super().__init__(message, "subscription_id")
        self.code = "INVALID_SUBSCRIPTION"
        if subscription_id:
            self.details["subscription_id"] = subscription_id
