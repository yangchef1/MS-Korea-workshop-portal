"""
Application exceptions module.

This module provides a centralized location for all custom exceptions.
Use these exceptions instead of raising HTTPException directly in service layers.

Usage:
    from app.exceptions import PolicyNotFoundError, ValidationError
    
    if not policy:
        raise PolicyNotFoundError(f"Policy {policy_id} not found")

Exception Hierarchy:
    AppError (base)
    ├── AuthenticationError (401)
    ├── AuthorizationError (403)
    ├── NotFoundError (404)
    ├── ConflictError (409)
    ├── ValidationError (400)
    │   ├── InvalidInputError
    │   ├── CSVParsingError
    │   ├── MissingFieldError
    │   ├── InvalidFormatError
    │   ├── InvalidDateRangeError
    │   ├── InvalidSubscriptionError
    │   ├── FileTooLargeError
    │   └── UnsupportedFileTypeError
    ├── ServiceError (502)
    │   └── AzureServiceError
    │       ├── AzureAuthenticationError (401)
    │       ├── PolicyServiceError
    │       │   ├── PolicyNotFoundError (404)
    │       │   ├── PolicyAssignmentError
    │       │   └── InvalidScopeError (400)
    │       ├── ResourceManagerError
    │       │   ├── ResourceGroupNotFoundError (404)
    │       │   ├── ResourceGroupCreationError
    │       │   ├── RoleAssignmentError
    │       │   └── DeploymentError
    │       ├── StorageServiceError
    │       │   ├── EntityNotFoundError (404)
    │       │   └── TableNotFoundError (404)
    │       ├── EntraIDServiceError (formerly AzureADServiceError)
    │       │   ├── EntraIDAuthorizationError (403)
    │       │   ├── UserCreationError
    │       │   ├── UserNotFoundError (404)
    │       │   └── UserDeletionError
    │       └── CostServiceError
    │           └── CostQueryError
    └── ServiceUnavailableError (503)
"""

from .base import (
    AppError,
    AuthenticationError,
    AuthorizationError,
    NotFoundError,
    ConflictError,
    ValidationError,
    InvalidInputError,
    ServiceError,
    ServiceUnavailableError,
)

from .azure import (
    AzureServiceError,
    AzureAuthenticationError,
    PolicyServiceError,
    PolicyNotFoundError,
    PolicyAssignmentError,
    InvalidScopeError,
    ResourceManagerError,
    ResourceGroupNotFoundError,
    ResourceGroupCreationError,
    RoleAssignmentError,
    DeploymentError,
    StorageServiceError,
    EntityNotFoundError,
    TableNotFoundError,
    EntraIDServiceError,
    EntraIDAuthorizationError,
    UserCreationError,
    UserNotFoundError,
    UserDeletionError,
    CostServiceError,
    CostQueryError,
)

from .validation import (
    CSVParsingError,
    MissingFieldError,
    InvalidFormatError,
    InvalidDateRangeError,
    FileTooLargeError,
    UnsupportedFileTypeError,
    InvalidSubscriptionError,
)

__all__ = [
    "AppError",
    "AuthenticationError",
    "AuthorizationError",
    "NotFoundError",
    "ConflictError",
    "ValidationError",
    "InvalidInputError",
    "ServiceError",
    "ServiceUnavailableError",
    "AzureServiceError",
    "AzureAuthenticationError",
    "PolicyServiceError",
    "PolicyNotFoundError",
    "PolicyAssignmentError",
    "InvalidScopeError",
    "ResourceManagerError",
    "ResourceGroupNotFoundError",
    "ResourceGroupCreationError",
    "RoleAssignmentError",
    "DeploymentError",
    "StorageServiceError",
    "EntityNotFoundError",
    "TableNotFoundError",
    "EntraIDServiceError",
    "EntraIDAuthorizationError",
    "UserCreationError",
    "UserNotFoundError",
    "UserDeletionError",
    "CostServiceError",
    "CostQueryError",
    "CSVParsingError",
    "MissingFieldError",
    "InvalidFormatError",
    "InvalidDateRangeError",
    "FileTooLargeError",
    "UnsupportedFileTypeError",
    "InvalidSubscriptionError",
]
