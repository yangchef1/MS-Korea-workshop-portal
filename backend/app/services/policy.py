"""
Azure Policy management service

Authentication: Uses DefaultAzureCredential (OIDC/Managed Identity)
- Local development: Azure CLI credential (az login)
- Production: Managed Identity assigned to App Service
"""
import asyncio
import logging
import re
import uuid
from functools import lru_cache
from typing import Any, Dict, List, Optional

from azure.core.exceptions import (
    AzureError,
    ClientAuthenticationError,
    HttpResponseError,
    ResourceNotFoundError,
    ServiceRequestError,
)
from azure.identity.aio import DefaultAzureCredential, AzureCliCredential
from azure.mgmt.resource.policy.aio import PolicyClient
from azure.mgmt.resource.policy.models import PolicyAssignment

from app.config import settings
from app.exceptions import (
    PolicyServiceError,
    AzureAuthenticationError,
    PolicyNotFoundError,
    PolicyAssignmentError,
    InvalidScopeError,
)

logger = logging.getLogger(__name__)


class PolicyService:
    """
    Service for managing Azure Policies.
    
    Uses async Azure SDK for non-blocking I/O operations.
    All methods are truly asynchronous and can be parallelized with asyncio.gather().
    Supports per-participant subscription assignment.
    """

    ALLOWED_LOCATIONS_POLICY_ID = (
        "/providers/Microsoft.Authorization/policyDefinitions/"
        "e56962a6-4747-49cd-b67b-bf8b01975c4c"
    )
    ALLOWED_RESOURCE_TYPES_POLICY_ID = (
        "/providers/Microsoft.Authorization/policyDefinitions/"
        "a08ec900-254a-4555-9bf5-e42af04b5c5c"
    )

    def __init__(self) -> None:
        """
        Initialize Policy service using Azure Identity (OIDC/Managed Identity).
        
        Raises:
            AzureAuthenticationError: If credential initialization fails
        """
        try:
            self._credential = self._create_credential()
            self._default_subscription_id = settings.azure_subscription_id
            logger.info("PolicyService initialized successfully")
        except ClientAuthenticationError as e:
            logger.error("Authentication failed during PolicyService initialization")
            raise AzureAuthenticationError(
                "Failed to authenticate with Azure. Please check your credentials."
            ) from e
        except Exception as e:
            logger.error("PolicyService initialization failed: %s", type(e).__name__)
            raise PolicyServiceError(
                "Failed to initialize PolicyService"
            ) from e

    def _create_credential(self) -> DefaultAzureCredential | AzureCliCredential:
        """Create appropriate Azure credential based on configuration."""
        if settings.use_azure_cli_credential:
            logger.debug("Using AzureCliCredential (async) for local development")
            return AzureCliCredential()
        
        logger.debug("Using DefaultAzureCredential (async)")
        return DefaultAzureCredential(
            exclude_shared_token_cache_credential=True,
            exclude_visual_studio_code_credential=True,
            exclude_azure_powershell_credential=True,
            exclude_interactive_browser_credential=True,
        )

    def _get_policy_client(self, subscription_id: Optional[str] = None) -> PolicyClient:
        """Get PolicyClient for a specific subscription."""
        sub_id = subscription_id or self._default_subscription_id
        return PolicyClient(
            credential=self._credential,
            subscription_id=sub_id
        )

    # Backward compatibility property
    @property
    def _policy_client(self) -> PolicyClient:
        return self._get_policy_client()

    async def assign_location_policy(
        self,
        scope: str,
        allowed_locations: List[str],
        assignment_name: Optional[str] = None,
        subscription_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Assign allowed locations policy to a scope.

        Args:
            scope: Resource scope (e.g., /subscriptions/{sub-id} for subscription-level policy)
            allowed_locations: List of allowed Azure regions (e.g., ['koreacentral', 'koreasouth'])
            assignment_name: Optional custom policy assignment name
            subscription_id: Target subscription ID (uses default if not provided)

        Returns:
            Policy assignment details

        Raises:
            AzureAuthenticationError: If authentication fails
            PolicyAssignmentError: If policy assignment fails
        """
        if not assignment_name:
            assignment_name = f"allowed-locations-{uuid.uuid4().hex[:8]}"

        if not allowed_locations:
            raise PolicyAssignmentError("At least one location must be specified")

        parameters = {
            "listOfAllowedLocations": {"value": allowed_locations}
        }

        assignment = PolicyAssignment(
            display_name=f"Allowed Locations: {', '.join(allowed_locations[:3])}{'...' if len(allowed_locations) > 3 else ''}",
            policy_definition_id=self.ALLOWED_LOCATIONS_POLICY_ID,
            parameters=parameters,
            description="Restricts resource deployment to allowed regions"
        )

        try:
            policy_client = self._get_policy_client(subscription_id)
            result = await policy_client.policy_assignments.create(
                scope=scope,
                policy_assignment_name=assignment_name,
                parameters=assignment
            )

            logger.info("Assigned location policy to %s", scope)

            return {
                'id': result.id,
                'name': result.name,
                'scope': scope,
                'allowed_locations': allowed_locations
            }

        except ClientAuthenticationError as e:
            logger.error("Authentication failed during location policy assignment")
            raise AzureAuthenticationError(
                "Authentication failed. Please re-authenticate."
            ) from e
        except HttpResponseError as e:
            logger.error(
                "HTTP error during location policy assignment: %s", e.status_code
            )
            raise PolicyAssignmentError(
                f"Failed to assign location policy: {e.message}"
            ) from e
        except ServiceRequestError as e:
            logger.error("Network error during location policy assignment")
            raise PolicyAssignmentError(
                "Network error. Please check connectivity and retry."
            ) from e

    async def assign_resource_types_policy(
        self,
        scope: str,
        allowed_resource_types: List[str],
        assignment_name: Optional[str] = None,
        subscription_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Assign allowed resource types policy to a scope.

        Args:
            scope: Resource scope
            allowed_resource_types: List of allowed resource types 
                (e.g., ['Microsoft.Network/virtualNetworks', 'Microsoft.Compute/virtualMachines'])
            assignment_name: Optional custom policy assignment name
            subscription_id: Target subscription ID (uses default if not provided)

        Returns:
            Policy assignment details

        Raises:
            AzureAuthenticationError: If authentication fails
            PolicyAssignmentError: If policy assignment fails
        """
        if not allowed_resource_types:
            logger.warning("No resource types provided, skipping policy assignment")
            return {'skipped': True, 'reason': 'No resource types provided'}

        if not assignment_name:
            assignment_name = f"allowed-resources-{uuid.uuid4().hex[:8]}"

        parameters = {
            "listOfResourceTypesAllowed": {"value": allowed_resource_types}
        }

        assignment = PolicyAssignment(
            display_name=f"Allowed Resource Types ({len(allowed_resource_types)} types)",
            policy_definition_id=self.ALLOWED_RESOURCE_TYPES_POLICY_ID,
            parameters=parameters,
            description=f"Restricts deployment to {len(allowed_resource_types)} allowed resource types"
        )

        try:
            policy_client = self._get_policy_client(subscription_id)
            result = await policy_client.policy_assignments.create(
                scope=scope,
                policy_assignment_name=assignment_name,
                parameters=assignment
            )

            logger.info(
                "Assigned resource types policy to %s with %d types",
                scope, len(allowed_resource_types)
            )

            return {
                'id': result.id,
                'name': result.name,
                'scope': scope,
                'allowed_resource_types': allowed_resource_types
            }

        except ClientAuthenticationError as e:
            logger.error("Authentication failed during resource types policy assignment")
            raise AzureAuthenticationError(
                "Authentication failed. Please re-authenticate."
            ) from e
        except HttpResponseError as e:
            logger.error(
                "HTTP error during resource types policy assignment: %s", e.status_code
            )
            raise PolicyAssignmentError(
                f"Failed to assign resource types policy: {e.message}"
            ) from e
        except ServiceRequestError as e:
            logger.error("Network error during resource types policy assignment")
            raise PolicyAssignmentError(
                "Network error. Please check connectivity and retry."
            ) from e

    async def assign_workshop_policies(
        self,
        scope: str,
        allowed_locations: List[str],
        allowed_resource_types: List[str],
        subscription_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Assign all workshop policies to a scope (location + resource types).

        Runs both policy assignments concurrently for better performance.
        Partial failures are captured and returned, not raised.

        Args:
            scope: Resource scope
            allowed_locations: List of allowed Azure regions
            allowed_resource_types: List of allowed resource types
            subscription_id: Target subscription ID (uses default if not provided)

        Returns:
            Dictionary with both policy assignment results (None if failed)
        """
        tasks = [
            self.assign_location_policy(scope, allowed_locations, subscription_id=subscription_id),
            self.assign_resource_types_policy(scope, allowed_resource_types, subscription_id=subscription_id)
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        policies: Dict[str, Any] = {
            'location_policy': None,
            'resource_types_policy': None
        }

        if isinstance(results[0], Exception):
            logger.error("Failed to assign location policy: %s", results[0])
        else:
            policies['location_policy'] = results[0]

        if isinstance(results[1], Exception):
            logger.error("Failed to assign resource types policy: %s", results[1])
        else:
            policies['resource_types_policy'] = results[1]

        return policies

    async def delete_policy_assignment(
        self, 
        scope: str, 
        assignment_name: str,
        subscription_id: Optional[str] = None
    ) -> bool:
        """
        Delete a policy assignment.

        Args:
            scope: Resource scope
            assignment_name: Policy assignment name to delete
            subscription_id: Target subscription ID (uses default if not provided)

        Returns:
            True if deletion was successful

        Raises:
            PolicyNotFoundError: If the policy assignment doesn't exist
            AzureAuthenticationError: If authentication fails
            PolicyServiceError: If deletion fails for other reasons
        """
        try:
            policy_client = self._get_policy_client(subscription_id)
            await policy_client.policy_assignments.delete(
                scope=scope,
                policy_assignment_name=assignment_name
            )

            logger.info("Policy assignment deleted: %s", assignment_name)
            return True

        except ResourceNotFoundError as e:
            logger.warning("Policy assignment not found: %s", assignment_name)
            raise PolicyNotFoundError(
                f"Policy assignment '{assignment_name}' not found"
            ) from e
        except ClientAuthenticationError as e:
            logger.error("Authentication failed during policy deletion")
            raise AzureAuthenticationError(
                "Authentication failed. Please re-authenticate."
            ) from e
        except AzureError as e:
            logger.error("Azure error during policy deletion: %s", type(e).__name__)
            raise PolicyServiceError(
                f"Failed to delete policy assignment: {str(e)}"
            ) from e

    async def list_policy_assignments(
        self,
        scope: str,
        subscription_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        List policy assignments for a subscription or resource group scope.

        Args:
            scope: Subscription or Resource group scope 
                (format: /subscriptions/{sub-id} or /subscriptions/{sub-id}/resourceGroups/{rg-name})
            subscription_id: Target subscription ID (uses default if not provided)

        Returns:
            List of policy assignment details

        Raises:
            InvalidScopeError: If scope format is invalid
            AzureAuthenticationError: If authentication fails
            PolicyServiceError: If listing fails
        """
        # Check if it's a subscription-level scope
        sub_pattern = re.compile(r"^/subscriptions/[a-f0-9-]+$", re.IGNORECASE)
        rg_pattern = re.compile(r"^/subscriptions/[a-f0-9-]+/resourceGroups/([^/]+)$", re.IGNORECASE)
        
        rg_match = rg_pattern.match(scope)
        is_subscription_scope = sub_pattern.match(scope) is not None
        
        if not is_subscription_scope and not rg_match:
            raise InvalidScopeError(
                "Invalid scope format. Expected: "
                "/subscriptions/{subscription-id} or "
                "/subscriptions/{subscription-id}/resourceGroups/{resource-group-name}"
            )

        try:
            policy_client = self._get_policy_client(subscription_id)
            if is_subscription_scope:
                # List assignments for subscription
                assignments = policy_client.policy_assignments.list()
            else:
                # List assignments for resource group
                resource_group_name = rg_match.group(1)
                assignments = policy_client.policy_assignments.list_for_resource_group(
                    resource_group_name=resource_group_name
                )

            result: List[Dict[str, Any]] = []
            async for assignment in assignments:
                result.append({
                    'id': assignment.id,
                    'name': assignment.name,
                    'display_name': assignment.display_name,
                    'policy_definition_id': assignment.policy_definition_id,
                    'scope': assignment.scope
                })

            logger.debug(
                "Listed %d policy assignments for %s", len(result), scope
            )
            return result

        except ClientAuthenticationError as e:
            logger.error("Authentication failed during policy listing")
            raise AzureAuthenticationError(
                "Authentication failed. Please re-authenticate."
            ) from e
        except AzureError as e:
            logger.error("Azure error during policy listing: %s", type(e).__name__)
            raise PolicyServiceError(
                f"Failed to list policy assignments: {str(e)}"
            ) from e


@lru_cache(maxsize=1)
def get_policy_service() -> PolicyService:
    """
    Get the PolicyService singleton instance.
    
    Thread-safe via @lru_cache. The instance is created on first call
    and reused for subsequent calls.
    
    Returns:
        PolicyService singleton instance
    
    Usage:
        service = get_policy_service()
        result = await service.assign_location_policy(...)
    """
    return PolicyService()


policy_service = get_policy_service()
