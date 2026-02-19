"""Azure Resource Manager 서비스 (비동기).

리소스 그룹, RBAC, ARM 배포를 관리한다.
azure.mgmt.resource.aio / azure.mgmt.authorization.aio를 사용하여
네이티브 비동기 I/O를 제공한다.
"""
import asyncio
import logging
import re
import time
import uuid
from functools import lru_cache
from typing import Any

from azure.identity.aio import (
    AzureCliCredential,
    ClientSecretCredential,
    DefaultAzureCredential,
)
from azure.mgmt.authorization.aio import AuthorizationManagementClient
from azure.mgmt.authorization.models import RoleAssignmentCreateParameters
from azure.mgmt.resource.resources.aio import ResourceManagementClient
from azure.mgmt.resource.resources.models import (
    Deployment,
    DeploymentMode,
    DeploymentProperties,
    ResourceGroup,
)

from app.config import settings

logger = logging.getLogger(__name__)

_RESOURCE_TYPES_CACHE_TTL = 86400  # 24시간


class ResourceManagerService:
    """Azure 리소스 그룹, RBAC, ARM 배포를 관리하는 비동기 서비스.

    구독별 리소스 관리를 지원하며, azure.mgmt.resource.aio의
    네이티브 비동기 클라이언트를 사용하여 Non-blocking I/O를 제공한다.
    """

    _resource_types_cache: dict[str, dict[str, str]] = {}
    _resource_types_cache_time: float = 0
    _role_definition_cache: dict[tuple[str, str], str] = {}

    def __init__(self) -> None:
        """Azure Resource Manager 서비스를 초기화한다."""
        try:
            self._credential = self._create_credential()
            self._default_subscription_id = settings.azure_subscription_id
            logger.info("Initialized async Resource Manager service")
        except Exception as e:
            logger.error("Failed to initialize Resource Manager client: %s", e)
            raise

    @staticmethod
    def _create_credential() -> ClientSecretCredential | DefaultAzureCredential | AzureCliCredential:
        """설정에 따라 적절한 비동기 Azure credential을 생성한다."""
        if settings.azure_sp_tenant_id and settings.azure_sp_client_id and settings.azure_sp_client_secret:
            return ClientSecretCredential(
                tenant_id=settings.azure_sp_tenant_id,
                client_id=settings.azure_sp_client_id,
                client_secret=settings.azure_sp_client_secret,
            )
        if settings.use_azure_cli_credential:
            return AzureCliCredential()
        return DefaultAzureCredential(
            exclude_shared_token_cache_credential=True,
            exclude_visual_studio_code_credential=True,
            exclude_azure_powershell_credential=True,
            exclude_interactive_browser_credential=True,
        )

    def _get_resource_client(
        self, subscription_id: str | None = None,
    ) -> ResourceManagementClient:
        """특정 구독의 비동기 ResourceManagementClient를 반환한다."""
        sub_id = subscription_id or self._default_subscription_id
        return ResourceManagementClient(
            credential=self._credential,
            subscription_id=sub_id,
            retry_total=settings.azure_retry_total,
            retry_backoff_factor=settings.azure_retry_backoff_factor,
        )

    def _get_auth_client(
        self, subscription_id: str | None = None,
    ) -> AuthorizationManagementClient:
        """특정 구독의 비동기 AuthorizationManagementClient를 반환한다."""
        sub_id = subscription_id or self._default_subscription_id
        return AuthorizationManagementClient(
            credential=self._credential,
            subscription_id=sub_id,
            retry_total=settings.azure_retry_total,
            retry_backoff_factor=settings.azure_retry_backoff_factor,
        )

    async def create_resource_group(
        self,
        name: str,
        location: str,
        tags: dict[str, str] | None = None,
        subscription_id: str | None = None,
    ) -> dict[str, Any]:
        """특정 구독에 리소스 그룹을 생성한다.

        Args:
            name: 리소스 그룹 이름.
            location: Azure 리전.
            tags: 리소스 태그.
            subscription_id: 대상 구독 ID. 미지정 시 기본 구독 사용.

        Returns:
            리소스 그룹 상세 정보.
        """
        try:
            resource_client = self._get_resource_client(subscription_id)
            rg_params = ResourceGroup(location=location, tags=tags or {})
            rg = await resource_client.resource_groups.create_or_update(
                resource_group_name=name,
                parameters=rg_params,
            )

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
        resource_groups: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """여러 리소스 그룹을 병렬로 생성한다.

        Args:
            resource_groups: name, location, tags, subscription_id를 포함하는 딕셔너리 목록.

        Returns:
            성공적으로 생성된 리소스 그룹 목록.
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
        self, name: str, subscription_id: str | None = None,
    ) -> bool:
        """리소스 그룹 삭제를 시작한다(비동기 작업).

        Args:
            name: 리소스 그룹 이름.
            subscription_id: 대상 구독 ID. 미지정 시 기본 구독 사용.

        Returns:
            삭제가 시작되면 True.
        """
        try:
            resource_client = self._get_resource_client(subscription_id)
            await resource_client.resource_groups.begin_delete(name)
            logger.info(
                "Started deletion of resource group: %s (subscription: %s)",
                name, subscription_id or 'default'
            )
            return True

        except Exception as e:
            logger.error("Failed to delete resource group %s: %s", name, e)
            raise

    async def delete_resource_groups_bulk(
        self, resource_groups: list[dict[str, Any]],
    ) -> dict[str, bool]:
        """여러 리소스 그룹을 병렬로 삭제한다.

        Args:
            resource_groups: name과 선택적 subscription_id를 포함하는 딕셔너리 목록.

        Returns:
            리소스 그룹 이름별 삭제 상태 매핑.
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
        subscription_id: str | None = None,
    ) -> dict[str, Any]:
        """프린시펄에 RBAC 역할을 할당한다.

        Args:
            scope: 리소스 범위 (예: 리소스 그룹 ID).
            principal_id: Azure AD 객체 ID.
            role_name: 역할 이름. 기본값은 Contributor.
            subscription_id: 대상 구독 ID. 미지정 시 기본 구독 사용.

        Returns:
            역할 할당 상세 정보.
        """
        try:
            auth_client = self._get_auth_client(subscription_id)
            role_id = await self._get_role_definition_id(role_name, subscription_id)
            role_assignment_name = str(uuid.uuid4())
            params = RoleAssignmentCreateParameters(
                role_definition_id=role_id,
                principal_id=principal_id,
            )
            assignment = await auth_client.role_assignments.create(
                scope=scope,
                role_assignment_name=role_assignment_name,
                parameters=params,
            )

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

    async def _get_role_definition_id(
        self, role_name: str, subscription_id: str | None = None,
    ) -> str:
        """역할 이름으로 역할 정의 ID를 조회한다.

        OData 필터를 사용하여 서버 측에서 필터링하고,
        클래스 레벨 캐시로 반복 조회를 방지한다.

        Args:
            role_name: Azure RBAC 역할 이름.
            subscription_id: 대상 구독 ID.

        Returns:
            역할 정의 전체 ID.

        Raises:
            ValueError: 역할을 찾을 수 없는 경우.
        """
        sub_id = subscription_id or self._default_subscription_id
        cache_key = (sub_id, role_name)

        cached = ResourceManagerService._role_definition_cache.get(cache_key)
        if cached:
            return cached

        scope = f"/subscriptions/{sub_id}"
        auth_client = self._get_auth_client(subscription_id)
        odata_filter = f"roleName eq '{role_name}'"

        async for role_def in auth_client.role_definitions.list(
            scope, filter=odata_filter,
        ):
            ResourceManagerService._role_definition_cache[cache_key] = role_def.id
            return role_def.id

        raise ValueError(f"Role '{role_name}' not found")

    async def deploy_template(
        self,
        resource_group_name: str,
        template: dict[str, Any],
        parameters: dict[str, Any] | None = None,
        deployment_name: str | None = None,
        subscription_id: str | None = None,
    ) -> dict[str, Any]:
        """인프라 템플릿을 리소스 그룹에 배포한다.

        Args:
            resource_group_name: 대상 리소스 그룹.
            template: 템플릿 JSON.
            parameters: 템플릿 파라미터.
            deployment_name: 배포 이름. 미지정 시 자동 생성.
            subscription_id: 대상 구독 ID. 미지정 시 기본 구독 사용.

        Returns:
            배포 상세 정보.
        """
        if not deployment_name:
            deployment_name = f"deployment-{uuid.uuid4().hex[:8]}"

        try:
            resource_client = self._get_resource_client(subscription_id)
            deployment_properties = DeploymentProperties(
                mode=DeploymentMode.INCREMENTAL,
                template=template,
                parameters=parameters or {},
            )
            deployment_params = Deployment(properties=deployment_properties)
            poller = await resource_client.deployments.begin_create_or_update(
                resource_group_name=resource_group_name,
                deployment_name=deployment_name,
                parameters=deployment_params,
            )
            result = await poller.result()

            logger.info(
                "Deployed template to %s: %s",
                resource_group_name, deployment_name
            )

            return {
                'deployment_name': deployment_name,
                'resource_group': resource_group_name,
                'provisioning_state': result.properties.provisioning_state,
                'outputs': result.properties.outputs
            }

        except Exception as e:
            logger.error("Failed to deploy template: %s", e)
            raise

    async def get_resource_group(
        self, name: str, subscription_id: str | None = None,
    ) -> dict[str, Any] | None:
        """리소스 그룹 상세 정보를 조회한다.

        Args:
            name: 리소스 그룹 이름.
            subscription_id: 대상 구독 ID. 미지정 시 기본 구독 사용.

        Returns:
            리소스 그룹 상세 정보. 존재하지 않으면 None.
        """
        try:
            resource_client = self._get_resource_client(subscription_id)
            rg = await resource_client.resource_groups.get(name)

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
        subscription_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """리소스 그룹 내 모든 리소스를 조회한다.

        Args:
            resource_group_name: 리소스 그룹 이름.
            subscription_id: 대상 구독 ID. 미지정 시 기본 구독 사용.

        Returns:
            리소스 목록.
        """
        try:
            resource_client = self._get_resource_client(subscription_id)
            resources = [
                r async for r in resource_client.resources.list_by_resource_group(
                    resource_group_name=resource_group_name
                )
            ]

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
        self, namespaces: list[str] | None = None,
    ) -> list[dict[str, str]]:
        """Azure Resource Provider에서 사용 가능한 리소스 타입을 조회한다.

        결과는 클래스 레벨에서 24시간 동안 캐시된다.

        Args:
            namespaces: 조회할 프로바이더 네임스페이스 목록.

        Returns:
            value, label, category를 포함하는 리소스 타입 목록.
        """
        cls = type(self)
        current_time = time.time()
        if cls._resource_types_cache and \
           (current_time - cls._resource_types_cache_time) < _RESOURCE_TYPES_CACHE_TTL:
            logger.debug("Returning cached resource types")
            return list(cls._resource_types_cache.values())

        if namespaces is None:
            namespaces = settings.default_services

        try:
            logger.info("Fetching resource types from Azure for namespaces: %s", namespaces)
            resource_client = self._get_resource_client()
            resource_types: list[dict[str, str]] = []

            for namespace in namespaces:
                try:
                    provider = await resource_client.providers.get(namespace)
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
                            'category': category,
                        })

                except Exception as e:
                    logger.warning("Failed to get provider %s: %s", namespace, e)
                    continue

            cls._resource_types_cache = {rt['value']: rt for rt in resource_types}
            cls._resource_types_cache_time = current_time

            logger.info("Cached %d resource types", len(resource_types))
            return resource_types

        except Exception as e:
            logger.error("Failed to get resource types: %s", e)
            if cls._resource_types_cache:
                logger.warning("Returning expired cache due to error")
                return list(cls._resource_types_cache.values())
            return []


@lru_cache(maxsize=1)
def get_resource_manager_service() -> ResourceManagerService:
    """ResourceManagerService 싱글턴 인스턴스를 반환한다."""
    return ResourceManagerService()


resource_manager_service = get_resource_manager_service()
