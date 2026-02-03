"""
Azure-specific exception classes.

These exceptions wrap Azure SDK errors and provide consistent error handling
for all Azure service operations (Policy, Resource Manager, Storage, AD, Cost).
"""
from .base import (
    AppError,
    AuthenticationError,
    AuthorizationError,
    NotFoundError,
    ServiceError,
)


class AzureServiceError(ServiceError):
    """Base exception for all Azure service errors"""
    
    def __init__(self, message: str = "Azure service error", service_name: str = "Azure"):
        super().__init__(message, service_name)
        self.code = "AZURE_SERVICE_ERROR"


class AzureAuthenticationError(AzureServiceError, AuthenticationError):
    """
    Azure authentication failed.
    
    Typically occurs when:
    - Credentials are invalid or expired
    - Managed Identity is not configured
    - Service Principal lacks permissions
    """
    
    def __init__(self, message: str = "Azure authentication failed"):
        AppError.__init__(self, message, "AZURE_AUTH_ERROR", 401)


class PolicyServiceError(AzureServiceError):
    """Base exception for Policy service errors"""
    
    def __init__(self, message: str = "Policy service error"):
        super().__init__(message, "PolicyService")
        self.code = "POLICY_SERVICE_ERROR"


class PolicyNotFoundError(PolicyServiceError, NotFoundError):
    """Requested policy or policy assignment was not found"""
    
    def __init__(self, message: str = "Policy not found"):
        AppError.__init__(self, message, "POLICY_NOT_FOUND", 404, {"resource_type": "Policy"})


class PolicyAssignmentError(PolicyServiceError):
    """Failed to create, modify, or delete a policy assignment"""
    
    def __init__(self, message: str = "Policy assignment failed"):
        super().__init__(message)
        self.code = "POLICY_ASSIGNMENT_ERROR"


class InvalidScopeError(PolicyServiceError, ValidationError):
    """The provided Azure scope is invalid"""
    
    def __init__(self, message: str = "Invalid scope"):
        AppError.__init__(self, message, "INVALID_SCOPE", 400, {"field": "scope"})


class ResourceManagerError(AzureServiceError):
    """Base exception for Resource Manager errors"""
    
    def __init__(self, message: str = "Resource Manager error"):
        super().__init__(message, "ResourceManager")
        self.code = "RESOURCE_MANAGER_ERROR"


class ResourceGroupNotFoundError(ResourceManagerError, NotFoundError):
    """Resource group was not found"""
    
    def __init__(self, message: str = "Resource group not found", resource_group: str = None):
        AppError.__init__(
            self, message, "RESOURCE_GROUP_NOT_FOUND", 404,
            {"resource_type": "ResourceGroup", "resource_group": resource_group}
        )


class ResourceGroupCreationError(ResourceManagerError):
    """Failed to create resource group"""
    
    def __init__(self, message: str = "Failed to create resource group"):
        super().__init__(message)
        self.code = "RESOURCE_GROUP_CREATION_ERROR"


class RoleAssignmentError(ResourceManagerError):
    """Failed to assign RBAC role"""
    
    def __init__(self, message: str = "Role assignment failed"):
        super().__init__(message)
        self.code = "ROLE_ASSIGNMENT_ERROR"


class DeploymentError(ResourceManagerError):
    """ARM template deployment failed"""
    
    def __init__(self, message: str = "Deployment failed", deployment_name: str = None):
        super().__init__(message)
        self.code = "DEPLOYMENT_ERROR"
        if deployment_name:
            self.details["deployment_name"] = deployment_name


class StorageServiceError(AzureServiceError):
    """Base exception for Storage service errors"""
    
    def __init__(self, message: str = "Storage service error"):
        super().__init__(message, "StorageService")
        self.code = "STORAGE_SERVICE_ERROR"


class BlobNotFoundError(StorageServiceError, NotFoundError):
    """Blob was not found in storage"""
    
    def __init__(self, message: str = "Blob not found", blob_name: str = None):
        AppError.__init__(
            self, message, "BLOB_NOT_FOUND", 404,
            {"resource_type": "Blob", "blob_name": blob_name}
        )


class ContainerNotFoundError(StorageServiceError, NotFoundError):
    """Storage container was not found"""
    
    def __init__(self, message: str = "Container not found", container_name: str = None):
        AppError.__init__(
            self, message, "CONTAINER_NOT_FOUND", 404,
            {"resource_type": "Container", "container_name": container_name}
        )


class EntraIDServiceError(AzureServiceError):
    """Base exception for Microsoft Entra ID service errors"""
    
    def __init__(self, message: str = "Entra ID service error"):
        super().__init__(message, "EntraIDService")
        self.code = "ENTRA_ID_SERVICE_ERROR"


class EntraIDAuthorizationError(EntraIDServiceError):
    """
    Entra ID authorization failed - insufficient permissions (403).
    
    Typically occurs when:
    - Service Principal lacks required Graph API permissions
    - Missing User.ReadWrite.All or Directory.ReadWrite.All permissions
    """
    
    def __init__(self, message: str = "Insufficient permissions for Entra ID operation"):
        AppError.__init__(self, message, "ENTRA_ID_AUTHORIZATION_ERROR", 403)


class UserCreationError(EntraIDServiceError):
    """Failed to create Entra ID user"""
    
    def __init__(self, message: str = "Failed to create user", user_alias: str = None):
        super().__init__(message)
        self.code = "USER_CREATION_ERROR"
        if user_alias:
            self.details["user_alias"] = user_alias


class UserNotFoundError(EntraIDServiceError, NotFoundError):
    """Entra ID user was not found"""
    
    def __init__(self, message: str = "User not found", user_id: str = None):
        AppError.__init__(
            self, message, "USER_NOT_FOUND", 404,
            {"resource_type": "User", "user_id": user_id}
        )


class UserDeletionError(EntraIDServiceError):
    """Failed to delete Entra ID user"""
    
    def __init__(self, message: str = "Failed to delete user", user_id: str = None):
        super().__init__(message)
        self.code = "USER_DELETION_ERROR"
        if user_id:
            self.details["user_id"] = user_id


class CostServiceError(AzureServiceError):
    """Base exception for Cost Management service errors"""
    
    def __init__(self, message: str = "Cost service error"):
        super().__init__(message, "CostService")
        self.code = "COST_SERVICE_ERROR"


class CostQueryError(CostServiceError):
    """Failed to query cost data"""
    
    def __init__(self, message: str = "Cost query failed"):
        super().__init__(message)
        self.code = "COST_QUERY_ERROR"
