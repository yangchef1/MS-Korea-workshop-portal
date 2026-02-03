"""
Base exception classes for the application.

All custom exceptions should inherit from AppError to ensure consistent
error handling across the application via the global exception handler.
"""
from typing import Optional


class AppError(Exception):
    """
    Base exception for all application errors.
    
    Attributes:
        message: Human-readable error message
        code: Machine-readable error code for client handling
        status_code: HTTP status code to return
        details: Additional error details (optional)
    """
    
    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        status_code: int = 500,
        details: Optional[dict] = None
    ):
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)

    def to_dict(self) -> dict:
        """Convert exception to dictionary for JSON response"""
        result = {
            "error": self.code,
            "message": self.message,
        }
        if self.details:
            result["details"] = self.details
        return result


class AuthenticationError(AppError):
    """Authentication failed - invalid or missing credentials (401)"""
    
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, "AUTHENTICATION_ERROR", 401)


class AuthorizationError(AppError):
    """Authorization failed - insufficient permissions (403)"""
    
    def __init__(self, message: str = "Permission denied"):
        super().__init__(message, "AUTHORIZATION_ERROR", 403)


class NotFoundError(AppError):
    """Requested resource was not found (404)"""
    
    def __init__(self, message: str = "Resource not found", resource_type: str = None):
        details = {"resource_type": resource_type} if resource_type else {}
        super().__init__(message, "NOT_FOUND", 404, details)


class ConflictError(AppError):
    """Resource conflict - already exists or state conflict (409)"""
    
    def __init__(self, message: str = "Resource conflict"):
        super().__init__(message, "CONFLICT", 409)


class ValidationError(AppError):
    """Input validation failed (400)"""
    
    def __init__(self, message: str = "Validation failed", field: str = None):
        details = {"field": field} if field else {}
        super().__init__(message, "VALIDATION_ERROR", 400, details)


class InvalidInputError(ValidationError):
    """Invalid input data provided (400)"""
    
    def __init__(self, message: str = "Invalid input", field: str = None):
        super().__init__(message, field)
        self.code = "INVALID_INPUT"


class ServiceError(AppError):
    """External service error (502)"""
    
    def __init__(self, message: str = "Service error", service_name: str = None):
        details = {"service": service_name} if service_name else {}
        super().__init__(message, "SERVICE_ERROR", 502, details)


class ServiceUnavailableError(AppError):
    """Service temporarily unavailable (503)"""
    
    def __init__(self, message: str = "Service temporarily unavailable"):
        super().__init__(message, "SERVICE_UNAVAILABLE", 503)
