"""Azure Resource Manager service for resource groups, RBAC, and ARM deployments.

Authentication: Uses DefaultAzureCredential (OIDC/Managed Identity)
- Local development: Azure CLI credential (az login)
- Production: Managed Identity assigned to App Service
"""
import asyncio
import logging
import re
import time
import uuid
from functools import lru_cache
from typing import List, Dict, Optional

from azure.mgmt.resource import ResourceManagementClient
from azure.mgmt.resource.resources.models import (
    ResourceGroup,
    Deployment,
    DeploymentProperties,
    DeploymentMode,
)
from azure.mgmt.authorization import AuthorizationManagementClient
from azure.mgmt.authorization.models import RoleAssignmentCreateParameters

from app.config import settings
from app.services.credential import get_azure_credential

logger = logging.getLogger(__name__)

_resource_types_cache: Dict[str, List[Dict]] = {}
_resource_types_cache_time: float = 0
RESOURCE_TYPES_CACHE_TTL = 86400


class ResourceManagerService:
    """Service for managing Azure resources with per-subscription support."""

    def __init__(self):
        """Initialize credentials for Azure Resource Manager."""
        try:
            self._credential = get_azure_credential()
            self._default_subscription_id = settings.azure_subscription_id
            logger.info("Initialized Resource Manager service")
        except Exception as e:
            logger.error("Failed to initialize Resource Manager client: %s", e)
            raise

    def _get_resource_client(
        self, subscription_id: Optional[str] = None
    ) -> ResourceManagementClient:
        """Get ResourceManagementClient for a specific subscription."""
        sub_id = subscription_id or self._default_subscription_id
        return ResourceManagementClient(
            credential=self._credential,
            subscription_id=sub_id
        )

    def _get_auth_client(
        self, subscription_id: Optional[str] = None
    ) -> AuthorizationManagementClient:
        """Get AuthorizationManagementClient for a specific subscription."""
        sub_id = subscription_id or self._default_subscription_id
        return AuthorizationManagementClient(
            credential=self._credential,
            subscription_id=sub_id
        )

    async def create_resource_group(
        self,
        name: str,
        location: str,
        tags: Optional[Dict[str, str]] = None,
        subscription_id: Optional[str] = None
    ) -> Dict:
        """Create a resource group in a specific subscription.

        Args:
            name: Resource group name
            location: Azure region
            tags: Resource tags
            subscription_id: Target subscription ID (uses default if not provided)

        Returns:
            Resource group details
        """
        def _create():
            resource_client = self._get_resource_client(subscription_id)
            rg_params = ResourceGroup(location=location, tags=tags or {})
            return resource_client.resource_groups.create_or_update(
                resource_group_name=name,
                parameters=rg_params
            )

        try:
            rg = await asyncio.to_thread(_create)

            logger.info(
                "Created resource group: %s in %s (subscription: %s)",
                name, location, subscription_id or 'default'
            )

            return {
                'name': rg.name,
                'location': rg.location,
                'id': rg.id,
                'tags': rg.tags,
                'subscription_id': subscription_id or self._default_subscription_id
            }

        except Exception as e:
            logger.error("Failed to create resource group %s: %s", name, e)
            raise

    async def create_resource_groups_bulk(
        self,
        resource_groups: List[Dict]
    ) -> List[Dict]:
        """Create multiple resource groups (supports per-participant subscription).

        Args:
            resource_groups: List of dicts with name, location, tags, and
                optionally subscription_id

        Returns:
            List of created resource group details
        """
        tasks = [
            self.create_resource_group(
                name=rg['name'],
                location=rg['location'],
                tags=rg.get('tags'),
                subscription_id=rg.get('subscription_id')
            )
            for rg in resource_groups
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        created_rgs = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "Failed to create RG %s: %s",
                    resource_groups[i]['name'], result
                )
            else:
                created_rgs.append(result)

        return created_rgs

    async def delete_resource_group(
        self, name: str, subscription_id: Optional[str] = None
    ) -> bool:
        """Delete a resource group (async operation).

        Args:
            name: Resource group name
            subscription_id: Target subscription ID (uses default if not provided)

        Returns:
            True if deletion started
        """
        def _delete():
            resource_client = self._get_resource_client(subscription_id)
            return resource_client.resource_groups.begin_delete(name)

        try:
            await asyncio.to_thread(_delete)
            logger.info(
                "Started deletion of resource group: %s (subscription: %s)",
                name, subscription_id or 'default'
            )
            return True

        except Exception as e:
            logger.error("Failed to delete resource group %s: %s", name, e)
            raise

    async def delete_resource_groups_bulk(
        self, resource_groups: List[Dict]
    ) -> Dict[str, bool]:
        """Delete multiple resource groups (supports per-participant subscription).

        Args:
            resource_groups: List of dicts with 'name' and optionally 'subscription_id'

        Returns:
            Dictionary mapping name to deletion status
        """
        if resource_groups and isinstance(resource_groups[0], str):
            resource_groups = [{'name': name} for name in resource_groups]

        tasks = [
            self.delete_resource_group(
                name=rg['name'],
                subscription_id=rg.get('subscription_id')
            )
            for rg in resource_groups
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        status = {}
        for i, result in enumerate(results):
            name = resource_groups[i]['name']
            if isinstance(result, Exception):
                logger.error("Failed to delete RG %s: %s", name, result)
                status[name] = False
            else:
                status[name] = result

        return status

    async def assign_rbac_role(
        self,
        scope: str,
        principal_id: str,
        role_name: str = "Contributor",
        subscription_id: Optional[str] = None
    ) -> Dict:
        """Assign RBAC role to a principal.

        Args:
            scope: Resource scope (e.g., resource group ID)
            principal_id: Azure AD object ID
            role_name: Role name (default: Contributor)
            subscription_id: Target subscription ID (uses default if not provided)

        Returns:
            Role assignment details
        """
        def _assign():
            auth_client = self._get_auth_client(subscription_id)
            role_id = self._get_role_definition_id(role_name, subscription_id)
            role_assignment_name = str(uuid.uuid4())
            params = RoleAssignmentCreateParameters(
                role_definition_id=role_id,
                principal_id=principal_id
            )
            return auth_client.role_assignments.create(
                scope=scope,
                role_assignment_name=role_assignment_name,
                parameters=params
            )

        try:
            assignment = await asyncio.to_thread(_assign)

            logger.info(
                "Assigned %s role to %s on %s",
                role_name, principal_id, scope
            )

            return {
                'id': assignment.id,
                'scope': assignment.scope,
                'role_definition_id': assignment.role_definition_id,
                'principal_id': assignment.principal_id
            }

        except Exception as e:
            logger.error("Failed to assign role: %s", e)
            raise

    def _get_role_definition_id(
        self, role_name: str, subscription_id: Optional[str] = None
    ) -> str:
        """Get role definition ID by name."""
        sub_id = subscription_id or self._default_subscription_id
        scope = f"/subscriptions/{sub_id}"
        auth_client = self._get_auth_client(subscription_id)
        
        for role_def in auth_client.role_definitions.list(scope):
            if role_def.role_name == role_name:
                return role_def.id

        raise ValueError(f"Role '{role_name}' not found")

    async def deploy_arm_template(
        self,
        resource_group_name: str,
        template: Dict,
        parameters: Optional[Dict] = None,
        deployment_name: Optional[str] = None,
        subscription_id: Optional[str] = None
    ) -> Dict:
        """Deploy ARM template to resource group.

        Args:
            resource_group_name: Target resource group
            template: ARM template JSON
            parameters: Template parameters
            deployment_name: Deployment name (auto-generated if not provided)
            subscription_id: Target subscription ID (uses default if not provided)

        Returns:
            Deployment details
        """
        if not deployment_name:
            deployment_name = f"deployment-{uuid.uuid4().hex[:8]}"

        def _deploy():
            resource_client = self._get_resource_client(subscription_id)
            deployment_properties = DeploymentProperties(
                mode=DeploymentMode.INCREMENTAL,
                template=template,
                parameters=parameters or {}
            )
            deployment_params = Deployment(properties=deployment_properties)
            poller = resource_client.deployments.begin_create_or_update(
                resource_group_name=resource_group_name,
                deployment_name=deployment_name,
                parameters=deployment_params
            )
            return poller.result()

        try:
            result = await asyncio.to_thread(_deploy)

            logger.info(
                "Deployed ARM template to %s: %s",
                resource_group_name, deployment_name
            )

            return {
                'deployment_name': deployment_name,
                'resource_group': resource_group_name,
                'provisioning_state': result.properties.provisioning_state,
                'outputs': result.properties.outputs
            }

        except Exception as e:
            logger.error("Failed to deploy ARM template: %s", e)
            raise

    async def get_resource_group(
        self, name: str, subscription_id: Optional[str] = None
    ) -> Optional[Dict]:
        """Get resource group details.

        Args:
            name: Resource group name
            subscription_id: Target subscription ID (uses default if not provided)

        Returns:
            Resource group details or None if not found
        """
        def _get():
            resource_client = self._get_resource_client(subscription_id)
            return resource_client.resource_groups.get(name)

        try:
            rg = await asyncio.to_thread(_get)

            return {
                'name': rg.name,
                'location': rg.location,
                'id': rg.id,
                'tags': rg.tags,
                'provisioning_state': rg.properties.provisioning_state
            }

        except Exception:
            logger.warning("Resource group not found: %s", name)
            return None

    async def list_resources_in_group(
        self,
        resource_group_name: str,
        subscription_id: Optional[str] = None
    ) -> List[Dict]:
        """List all resources in a resource group.

        Args:
            resource_group_name: Resource group name
            subscription_id: Target subscription ID (uses default if not provided)

        Returns:
            List of resources
        """
        def _list():
            resource_client = self._get_resource_client(subscription_id)
            return list(resource_client.resources.list_by_resource_group(
                resource_group_name=resource_group_name
            ))

        try:
            resources = await asyncio.to_thread(_list)
            
            return [
                {
                    'id': resource.id,
                    'name': resource.name,
                    'type': resource.type,
                    'location': resource.location,
                    'tags': resource.tags or {},
                    'provisioning_state': getattr(
                        resource, 'provisioning_state', None
                    )
                }
                for resource in resources
            ]

        except Exception as e:
            logger.error("Failed to list resources in %s: %s", resource_group_name, e)
            return []

    async def get_resource_types(
        self, namespaces: Optional[List[str]] = None
    ) -> List[Dict]:
        """Get available resource types from Azure Resource Providers.

        Results are cached in-memory for 24 hours.

        Args:
            namespaces: List of provider namespaces to query

        Returns:
            List of resource types with value, label, and category
        """
        global _resource_types_cache, _resource_types_cache_time

        current_time = time.time()
        if _resource_types_cache and \
           (current_time - _resource_types_cache_time) < RESOURCE_TYPES_CACHE_TTL:
            logger.debug("Returning cached resource types")
            return list(_resource_types_cache.values())

        if namespaces is None:
            namespaces = settings.default_services

        def _fetch():
            resource_client = self._get_resource_client()
            resource_types = []
            
            for namespace in namespaces:
                try:
                    provider = resource_client.providers.get(namespace)
                    category = namespace.split('.')[-1] if '.' in namespace else namespace

                    for rt in provider.resource_types:
                        if '/' in rt.resource_type:
                            continue
                        
                        full_type = f"{namespace}/{rt.resource_type}"
                        label = rt.resource_type
                        label = re.sub(r'([a-z])([A-Z])', r'\1 \2', label)
                        label = label.title()

                        resource_types.append({
                            'value': full_type,
                            'label': label,
                            'category': category
                        })

                except Exception as e:
                    logger.warning("Failed to get provider %s: %s", namespace, e)
                    continue
            
            return resource_types

        try:
            logger.info("Fetching resource types from Azure for namespaces: %s", namespaces)
            resource_types = await asyncio.to_thread(_fetch)

            _resource_types_cache = {rt['value']: rt for rt in resource_types}
            _resource_types_cache_time = current_time

            logger.info("Cached %d resource types", len(resource_types))
            return resource_types

        except Exception as e:
            logger.error("Failed to get resource types: %s", e)
            if _resource_types_cache:
                logger.warning("Returning expired cache due to error")
                return list(_resource_types_cache.values())
            return []


@lru_cache(maxsize=1)
def get_resource_manager_service() -> ResourceManagerService:
    """Get the ResourceManagerService singleton instance."""
    return ResourceManagerService()


resource_manager_service = get_resource_manager_service()
