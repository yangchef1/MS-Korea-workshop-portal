"""Azure Resource Manager 서비스 (비동기).

리소스 그룹, RBAC, ARM/Bicep 배포를 관리한다.
azure.mgmt.resource.aio / azure.mgmt.authorization.aio를 사용하여
네이티브 비동기 I/O를 제공한다.
"""
import asyncio
import json
import logging
import os
import re
import shutil
import tempfile
import time
import uuid
from functools import lru_cache
from typing import Any

from azure.core.exceptions import ResourceNotFoundError
from azure.mgmt.authorization.aio import AuthorizationManagementClient
from azure.mgmt.authorization.models import RoleAssignmentCreateParameters
from azure.mgmt.resource.resources.aio import ResourceManagementClient
from azure.mgmt.compute.aio import ComputeManagementClient
from azure.mgmt.resource.resources.models import (
    Deployment,
    DeploymentMode,
    DeploymentProperties,
    ResourceGroup,
)

from app.config import settings
from app.services.credential import get_async_azure_credential

logger = logging.getLogger(__name__)

_RESOURCE_TYPES_CACHE_TTL = 86400  # 24시간
_VM_SKUS_CACHE_TTL = 86400  # 24시간


class ResourceManagerService:
    """Azure 리소스 그룹, RBAC, ARM 배포를 관리하는 비동기 서비스.

    구독별 리소스 관리를 지원하며, azure.mgmt.resource.aio의
    네이티브 비동기 클라이언트를 사용하여 Non-blocking I/O를 제공한다.
    """

    _resource_types_cache: dict[str, dict[str, str]] = {}
    _resource_types_cache_time: float = 0
    _role_definition_cache: dict[tuple[str, str], str] = {}
    _vm_skus_cache: dict[str, list[dict[str, Any]]] = {}
    _vm_skus_cache_time: dict[str, float] = {}
    _common_vm_skus_cache: dict[str, list[dict[str, Any]]] = {}
    _common_vm_skus_cache_time: dict[str, float] = {}

    def __init__(self) -> None:
        """Azure Resource Manager 서비스를 초기화한다."""
        try:
            self._credential = get_async_azure_credential()
            self._default_subscription_id = settings.azure_subscription_id
            logger.info("Initialized async Resource Manager service")
        except Exception as e:
            logger.error("Failed to initialize Resource Manager client: %s", e)
            raise

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

    async def update_resource_group_tags(
        self,
        name: str,
        tags: dict[str, str],
        subscription_id: str | None = None,
    ) -> None:
        """리소스 그룹의 태그를 업데이트한다.

        기존 태그를 유지하면서 지정된 태그만 덮어쓴다.

        Args:
            name: 리소스 그룹 이름.
            tags: 업데이트할 태그 딕셔너리.
            subscription_id: 대상 구독 ID. 미지정 시 기본 구독 사용.
        """
        try:
            resource_client = self._get_resource_client(subscription_id)
            rg = await resource_client.resource_groups.get(name)
            merged_tags = {**(rg.tags or {}), **tags}
            rg_params = ResourceGroup(location=rg.location, tags=merged_tags)
            await resource_client.resource_groups.create_or_update(
                resource_group_name=name,
                parameters=rg_params,
            )
            logger.info(
                "Updated tags for resource group '%s' (subscription: %s)",
                name, subscription_id or "default",
            )
        except Exception as e:
            logger.warning(
                "Failed to update tags for resource group '%s': %s", name, e,
            )

    async def update_resource_group_tags_bulk(
        self,
        resource_groups: list[dict[str, Any]],
        tags: dict[str, str],
    ) -> None:
        """여러 리소스 그룹의 태그를 병렬로 업데이트한다.

        개별 실패는 경고 로그만 남기고 전체 작업을 중단하지 않는다.

        Args:
            resource_groups: name, subscription_id를 포함하는 딕셔너리 목록.
            tags: 업데이트할 태그 딕셔너리.
        """
        tasks = [
            self.update_resource_group_tags(
                name=rg["name"],
                tags=tags,
                subscription_id=rg.get("subscription_id"),
            )
            for rg in resource_groups
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def delete_resource_group(
        self, name: str, subscription_id: str | None = None,
    ) -> bool:
        """리소스 그룹 삭제를 시작한다(비동기 작업).

        이미 삭제되었거나 존재하지 않는 리소스 그룹은 성공으로 처리한다.

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

        except ResourceNotFoundError:
            # Already deleted or never existed — treat as success
            logger.info(
                "Resource group %s not found (already deleted), treating as success",
                name,
            )
            return True

        except Exception as e:
            logger.error("Failed to delete resource group %s: %s", name, e)
            raise

    async def delete_resource_groups_bulk(
        self, resource_groups: list[dict[str, Any]],
    ) -> dict[str, bool]:
        """여러 리소스 그룹을 병렬로 삭제한다.

        삭제 API가 일시적 오류를 반환하더라도 실제로는 Azure가 비동기적으로
        삭제를 완료하는 경우가 있다. 이를 방지하기 위해 실패로 보고된
        리소스 그룹의 존재 여부를 재확인한 후 최종 상태를 결정한다.

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

        # Verify that "failed" RGs actually still exist.
        # Azure may complete deletion asynchronously even when the initial
        # API call reported an error (e.g. transient 5xx, timeout).
        failed_rgs = [
            rg for rg in resource_groups
            if not status.get(rg['name'], False)
        ]
        if failed_rgs:
            await asyncio.sleep(5)
            verify_tasks = [
                self._resource_group_exists(
                    rg['name'], rg.get('subscription_id'),
                )
                for rg in failed_rgs
            ]
            verify_results = await asyncio.gather(
                *verify_tasks, return_exceptions=True,
            )
            for rg, exists in zip(failed_rgs, verify_results):
                if isinstance(exists, bool) and not exists:
                    logger.info(
                        "Resource group %s verified as deleted "
                        "(initial delete reported failure)",
                        rg['name'],
                    )
                    status[rg['name']] = True

        return status

    async def _resource_group_exists(
        self, name: str, subscription_id: str | None = None,
    ) -> bool:
        """리소스 그룹이 존재하는지 확인한다.

        Args:
            name: 리소스 그룹 이름.
            subscription_id: 대상 구독 ID.

        Returns:
            존재하면 True, 없으면 False.
        """
        try:
            resource_client = self._get_resource_client(subscription_id)
            await resource_client.resource_groups.get(name)
            return True
        except ResourceNotFoundError:
            return False
        except Exception:
            # Cannot determine — assume it still exists to be safe
            return True

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

    def _get_compute_client(
        self, subscription_id: str | None = None,
    ) -> ComputeManagementClient:
        """특정 구독의 비동기 ComputeManagementClient를 반환한다."""
        sub_id = subscription_id or self._default_subscription_id
        return ComputeManagementClient(
            credential=self._credential,
            subscription_id=sub_id,
        )

    async def list_vm_skus(
        self,
        location: str,
        subscription_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """특정 리전의 VM SKU 목록을 조회한다.

        Azure Compute API에서 리소스 SKU를 조회하여 VM 관련 SKU만
        필터링한다. 결과는 리전별 24시간 캐시된다.

        Args:
            location: Azure 리전 (예: 'koreacentral').
            subscription_id: 대상 구독 ID. 미지정 시 기본 구독 사용.

        Returns:
            name, family, vcpus, memory_gb를 포함하는 VM SKU 목록.
        """
        cls = type(self)
        current_time = time.time()
        cached = cls._vm_skus_cache.get(location)
        cache_time = cls._vm_skus_cache_time.get(location, 0)

        if cached and (current_time - cache_time) < _VM_SKUS_CACHE_TTL:
            logger.debug("Returning cached VM SKUs for %s", location)
            return cached

        try:
            logger.info("Fetching VM SKUs from Azure for location: %s", location)
            async with self._get_compute_client(subscription_id) as compute_client:
                skus: list[dict[str, Any]] = []

                async for sku in compute_client.resource_skus.list(
                    filter=f"location eq '{location}'"
                ):
                    # VM 관련 SKU만 필터링
                    if sku.resource_type != "virtualMachines":
                        continue

                    vcpus = 0
                    memory_gb = 0.0
                    family = sku.family or ""

                    for capability in (sku.capabilities or []):
                        if capability.name == "vCPUs":
                            vcpus = int(capability.value)
                        elif capability.name == "MemoryGB":
                            memory_gb = float(capability.value)

                    skus.append({
                        "name": sku.name,
                        "family": family,
                        "vcpus": vcpus,
                        "memory_gb": memory_gb,
                    })

                # 이름순 정렬
                skus.sort(key=lambda s: s["name"])

                cls._vm_skus_cache[location] = skus
                cls._vm_skus_cache_time[location] = current_time
                logger.info("Cached %d VM SKUs for %s", len(skus), location)
                return skus

        except Exception as e:
            logger.error("Failed to list VM SKUs for %s: %s", location, e)
            if cached:
                logger.warning("Returning expired VM SKU cache for %s", location)
                return cached
            return []

    async def list_common_vm_skus(
        self,
        regions: list[str],
        subscription_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """지정된 모든 리전에서 공통으로 지원되는 VM SKU 교집합을 조회한다.

        각 리전별로 ``location eq '{region}'`` 필터를 사용하여 병렬 조회한 뒤,
        모든 리전에 공통으로 존재하는 VM SKU만 반환한다.
        결과는 리전 조합별로 24시간 캐시된다.

        Note:
            ``resourceType eq 'virtualMachines'`` 필터는 Azure API에서
            서버 사이드 필터링을 지원하지 않아 전체 SKU(6만여 건, ~100MB)를
            반환하므로 사용하지 않는다.

        Args:
            regions: 교집합 대상 리전 목록 (예: ['koreacentral', 'eastus']).
            subscription_id: 대상 구독 ID. 미지정 시 기본 구독 사용.

        Returns:
            name, family, vcpus, memory_gb를 포함하는 VM SKU 목록.
        """
        if not regions:
            return []

        target_regions = [r.lower() for r in regions]
        cache_key = ",".join(sorted(target_regions))

        cls = type(self)
        current_time = time.time()
        cached = cls._common_vm_skus_cache.get(cache_key)
        cache_time = cls._common_vm_skus_cache_time.get(cache_key, 0)

        if cached and (current_time - cache_time) < _VM_SKUS_CACHE_TTL:
            logger.debug("Returning cached common VM SKUs (regions: %s)", cache_key)
            return cached

        # Table Storage 캐시 확인 (7일 TTL)
        try:
            from app.services.storage import storage_service
            from app.services.storage import _VM_SKUS_TABLE_CACHE_TTL_SECONDS
            table_skus, table_saved_at = await storage_service.get_vm_sku_cache(cache_key)
            if table_skus is not None and table_saved_at is not None:
                is_fresh = (current_time - table_saved_at) < _VM_SKUS_TABLE_CACHE_TTL_SECONDS
                # Empty cache for multiple regions is almost certainly stale/failed
                is_valid = len(table_skus) > 0 or len(target_regions) <= 1
                if is_fresh and is_valid:
                    logger.info(
                        "Returning Table Storage VM SKU cache (regions: %s, age: %.1fh)",
                        cache_key, (current_time - table_saved_at) / 3600,
                    )
                    cls._common_vm_skus_cache[cache_key] = table_skus
                    cls._common_vm_skus_cache_time[cache_key] = current_time
                    return table_skus
                if not is_valid:
                    logger.warning(
                        "Ignoring empty Table Storage VM SKU cache (regions: %s)",
                        cache_key,
                    )
        except Exception as e:
            logger.warning("Table Storage VM SKU cache lookup failed (non-fatal): %s", e)

        try:
            logger.info("Fetching common VM SKUs from Azure (regions: %s)", cache_key)

            # 각 리전별 SKU를 병렬 조회 (location 필터는 서버 사이드 지원됨)
            region_results = await asyncio.gather(
                *(self.list_vm_skus(region, subscription_id) for region in target_regions)
            )

            # 첫 번째 리전의 SKU 이름 집합에서 시작하여 교집합 계산
            common_names: set[str] = {sku["name"] for sku in region_results[0]}
            for region_skus in region_results[1:]:
                common_names &= {sku["name"] for sku in region_skus}

            # 첫 번째 리전의 상세 정보를 기준으로 교집합 SKU만 추출
            skus = [
                sku for sku in region_results[0]
                if sku["name"] in common_names
            ]
            skus.sort(key=lambda s: s["name"])

            cls._common_vm_skus_cache[cache_key] = skus
            cls._common_vm_skus_cache_time[cache_key] = current_time
            logger.info(
                "Cached %d common VM SKUs for regions: %s", len(skus), cache_key
            )

            # 실시간 조회 결과를 Table Storage에도 저장
            try:
                from app.services.storage import storage_service
                await storage_service.set_vm_sku_cache(cache_key, skus)
            except Exception as e:
                logger.warning("Failed to persist VM SKU cache to Table Storage (non-fatal): %s", e)

            return skus

        except Exception as e:
            logger.error(
                "Failed to list common VM SKUs (regions: %s): %s", cache_key, e
            )
            # Fallback 1: 만료된 인메모리 캐시
            if cached:
                logger.warning(
                    "Returning expired in-memory VM SKU cache for %s", cache_key
                )
                return cached

            # Fallback 2: 만료된 Table Storage 캐시 (서버 재시작 직후 등)
            try:
                from app.services.storage import storage_service
                stale_skus, _ = await storage_service.get_vm_sku_cache(cache_key)
                if stale_skus:
                    logger.warning(
                        "Returning stale Table Storage VM SKU cache for %s (%d SKUs)",
                        cache_key, len(stale_skus),
                    )
                    cls._common_vm_skus_cache[cache_key] = stale_skus
                    cls._common_vm_skus_cache_time[cache_key] = current_time
                    return stale_skus
            except Exception as fallback_err:
                logger.warning("Table Storage fallback also failed: %s", fallback_err)

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


async def compile_bicep_to_arm(bicep_content: str) -> str:
    """Bicep 템플릿을 ARM JSON 문자열로 컴파일한다.

    Bicep standalone CLI를 사용하여 Bicep 소스를
    ARM 템플릿 JSON으로 변환한다.
    템플릿 저장 시점에 호출되어 프리컴파일 결과를 저장한다.

    Args:
        bicep_content: Bicep 템플릿 소스 코드.

    Returns:
        컴파일된 ARM 템플릿 JSON 문자열.

    Raises:
        BicepCompilationError: 컴파일 실패 시.
    """
    from app.exceptions import BicepCompilationError

    tmp_dir = tempfile.mkdtemp(prefix="bicep_")
    bicep_file = os.path.join(tmp_dir, "template.bicep")
    arm_file = os.path.join(tmp_dir, "template.json")

    try:
        with open(bicep_file, "w", encoding="utf-8") as f:
            f.write(bicep_content)

        process = await asyncio.create_subprocess_exec(
            "bicep", "build", bicep_file,
            "--outfile", arm_file,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace").strip()
            raise BicepCompilationError(
                f"Bicep compilation failed: {error_msg}"
            )

        with open(arm_file, "r", encoding="utf-8") as f:
            arm_json = f.read()

        # Validate the output is valid JSON
        json.loads(arm_json)

        logger.info("Successfully compiled Bicep to ARM template")
        return arm_json

    except BicepCompilationError:
        raise
    except Exception as e:
        logger.error("Bicep compilation error: %s", e)
        raise BicepCompilationError(
            f"Unexpected error during Bicep compilation: {e}"
        ) from e
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
