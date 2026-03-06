"""Azure Policy 관리 서비스.

DefaultAzureCredential(OIDC/Managed Identity)을 사용하여 인증한다.
- 로컬 개발: Azure CLI credential (az login)
- 프로덕션: App Service에 할당된 Managed Identity
"""
import asyncio
import logging
import uuid
from functools import lru_cache
from typing import Any

from azure.core.exceptions import (
    AzureError,
    ClientAuthenticationError,
    HttpResponseError,
    ResourceNotFoundError,
    ServiceRequestError,
)
from azure.mgmt.resource.policy.aio import PolicyClient
from azure.mgmt.resource.policy.models import PolicyAssignment

from app.config import settings
from app.exceptions import (
    AzureAuthenticationError,
    PolicyAssignmentError,
    PolicyNotFoundError,
    PolicyServiceError,
)
from app.services.credential import get_async_azure_credential

logger = logging.getLogger(__name__)

WORKSHOP_ALLOWED_LOCATIONS_ASSIGNMENT = "workshop-allowed-locations"
WORKSHOP_DENIED_RESOURCES_ASSIGNMENT = "workshop-denied-resources"
WORKSHOP_ALLOWED_VM_SKUS_ASSIGNMENT = "workshop-allowed-vm-skus"


class PolicyService:
    """Azure Policy 할당/삭제/조회를 관리하는 서비스.

    비동기 Azure SDK를 사용하며, asyncio.gather()로 병렬 실행이 가능하다.

    Attributes:
        ALLOWED_LOCATIONS_POLICY_ID: 허용 지역 정책 정의 ID.
        DENIED_RESOURCE_TYPES_POLICY_ID: 차단 리소스 타입 정책 정의 ID.
    """

    ALLOWED_LOCATIONS_POLICY_ID = (
        "/providers/Microsoft.Authorization/policyDefinitions/"
        "e56962a6-4747-49cd-b67b-bf8b01975c4c"
    )
    DENIED_RESOURCE_TYPES_POLICY_ID = (
        "/providers/Microsoft.Authorization/policyDefinitions/"
        "6c112d4e-5bc7-47ae-a041-ea2d9dccd749"
    )

    def __init__(self) -> None:
        """Azure Identity를 사용하여 PolicyService를 초기화한다.

        Raises:
            AzureAuthenticationError: 인증 실패 시.
            PolicyServiceError: 기타 초기화 실패 시.
        """
        try:
            self._credential = get_async_azure_credential()
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

    def _get_policy_client(self, subscription_id: str | None = None) -> PolicyClient:
        """특정 구독의 PolicyClient를 반환한다."""
        sub_id = subscription_id or self._default_subscription_id
        return PolicyClient(credential=self._credential, subscription_id=sub_id)

    @property
    def _policy_client(self) -> PolicyClient:
        """기본 구독용 PolicyClient (하위 호환성)."""
        return self._get_policy_client()

    async def _create_assignment(
        self,
        scope: str,
        assignment_name: str,
        assignment: PolicyAssignment,
        policy_type: str,
        subscription_id: str | None = None,
    ) -> dict[str, Any]:
        """정책 할당을 생성하고 공통 에러 처리를 수행한다.

        Args:
            scope: 리소스 범위.
            assignment_name: 정책 할당 이름.
            assignment: 정책 할당 객체.
            policy_type: 에러 메시지용 정책 유형 (예: "location", "resource types").
            subscription_id: 대상 구독 ID. 미지정 시 기본 구독 사용.

        Returns:
            정책 할당 결과의 id, name, scope.

        Raises:
            AzureAuthenticationError: 인증 실패 시.
            PolicyAssignmentError: 정책 할당 실패 시.
        """
        try:
            policy_client = self._get_policy_client(subscription_id)
            result = await policy_client.policy_assignments.create(
                scope=scope,
                policy_assignment_name=assignment_name,
                parameters=assignment,
            )
            return {"id": result.id, "name": result.name, "scope": scope}
        except ClientAuthenticationError as e:
            logger.error("Authentication failed during %s policy assignment", policy_type)
            raise AzureAuthenticationError(
                "Authentication failed. Please re-authenticate."
            ) from e
        except HttpResponseError as e:
            logger.error(
                "HTTP error during %s policy assignment: %s", policy_type, e.status_code
            )
            raise PolicyAssignmentError(
                f"Failed to assign {policy_type} policy: {e.message}"
            ) from e
        except ServiceRequestError as e:
            logger.error("Network error during %s policy assignment", policy_type)
            raise PolicyAssignmentError(
                "Network error. Please check connectivity and retry."
            ) from e

    async def assign_location_policy(
        self,
        scope: str,
        allowed_locations: list[str],
        assignment_name: str | None = None,
        subscription_id: str | None = None,
    ) -> dict[str, Any]:
        """허용 지역 정책을 특정 범위에 할당한다.

        Args:
            scope: 리소스 범위 (예: /subscriptions/{sub-id}).
            allowed_locations: 허용 Azure 리전 목록 (예: ['koreacentral']).
            assignment_name: 정책 할당 이름. 미지정 시 자동 생성.
            subscription_id: 대상 구독 ID. 미지정 시 기본 구독 사용.

        Returns:
            정책 할당 결과 (id, name, scope, allowed_locations).

        Raises:
            PolicyAssignmentError: 지역 목록이 비어있거나 할당 실패 시.
            AzureAuthenticationError: 인증 실패 시.
        """
        if not allowed_locations:
            raise PolicyAssignmentError("At least one location must be specified")

        if not assignment_name:
            assignment_name = f"allowed-locations-{uuid.uuid4().hex[:8]}"

        location_preview = ", ".join(allowed_locations[:3])
        ellipsis_suffix = "..." if len(allowed_locations) > 3 else ""

        assignment = PolicyAssignment(
            display_name=f"Allowed Locations: {location_preview}{ellipsis_suffix}",
            policy_definition_id=self.ALLOWED_LOCATIONS_POLICY_ID,
            parameters={"listOfAllowedLocations": {"value": allowed_locations}},
            description="Restricts resource deployment to allowed regions",
        )

        result = await self._create_assignment(
            scope, assignment_name, assignment, "location", subscription_id
        )
        logger.info("Assigned location policy to %s", scope)
        result["allowed_locations"] = allowed_locations
        return result

    async def assign_denied_resource_types_policy(
        self,
        scope: str,
        denied_resource_types: list[str],
        assignment_name: str | None = None,
        subscription_id: str | None = None,
    ) -> dict[str, Any]:
        """차단 리소스 타입 정책을 특정 범위에 할당한다.

        블랙리스트 방식으로, 지정된 리소스 타입의 배포를 거부한다.

        Args:
            scope: 리소스 범위.
            denied_resource_types: 차단할 리소스 타입 목록
                (예: ['Microsoft.Compute/virtualMachines']).
            assignment_name: 정책 할당 이름. 미지정 시 자동 생성.
            subscription_id: 대상 구독 ID. 미지정 시 기본 구독 사용.

        Returns:
            정책 할당 결과 (id, name, scope, denied_resource_types).

        Raises:
            PolicyAssignmentError: 할당 실패 시.
            AzureAuthenticationError: 인증 실패 시.
        """
        if not denied_resource_types:
            logger.warning("No denied resource types provided, skipping policy assignment")
            return {"skipped": True, "reason": "No denied resource types provided"}

        if not assignment_name:
            assignment_name = f"denied-resources-{uuid.uuid4().hex[:8]}"

        type_count = len(denied_resource_types)
        assignment = PolicyAssignment(
            display_name=f"Not Allowed Resource Types ({type_count} types)",
            policy_definition_id=self.DENIED_RESOURCE_TYPES_POLICY_ID,
            parameters={"listOfResourceTypesNotAllowed": {"value": denied_resource_types}},
            description=f"Denies deployment of {type_count} resource types",
        )

        result = await self._create_assignment(
            scope, assignment_name, assignment, "denied resource types", subscription_id
        )
        logger.info(
            "Assigned denied resource types policy to %s with %d types", scope, type_count
        )
        result["denied_resource_types"] = denied_resource_types
        return result

    async def assign_workshop_policies(
        self,
        scope: str,
        allowed_locations: list[str],
        denied_resource_types: list[str],
        subscription_id: str | None = None,
        allowed_vm_skus: list[str] | None = None,
    ) -> dict[str, Any]:
        """워크샵 정책(지역 허용 + 리소스 타입 차단)을 한 번에 할당한다.

        두 정책 할당을 병렬로 실행하며, 부분 실패는 예외를 발생시키지 않고
        결과에 None으로 표시한다.

        Args:
            scope: 리소스 범위.
            allowed_locations: 허용 Azure 리전 목록.
            denied_resource_types: 차단할 리소스 타입 목록.
            subscription_id: 대상 구독 ID. 미지정 시 기본 구독 사용.
            allowed_vm_skus: 허용할 VM SKU 목록. 미지정 시 VM SKU 정책을 할당하지 않음.

        Returns:
            location_policy와 resource_types_policy 결과 딕셔너리.
        """
        tasks = [
            self.assign_location_policy(
                scope, allowed_locations,
                assignment_name=WORKSHOP_ALLOWED_LOCATIONS_ASSIGNMENT,
                subscription_id=subscription_id,
            ),
            self.assign_denied_resource_types_policy(
                scope, denied_resource_types,
                assignment_name=WORKSHOP_DENIED_RESOURCES_ASSIGNMENT,
                subscription_id=subscription_id,
            ),
        ]
        policy_keys = ["location_policy", "resource_types_policy"]

        if allowed_vm_skus:
            tasks.append(
                self.assign_allowed_vm_skus_policy(
                    scope, allowed_vm_skus,
                    assignment_name=WORKSHOP_ALLOWED_VM_SKUS_ASSIGNMENT,
                    subscription_id=subscription_id,
                )
            )
            policy_keys.append("vm_skus_policy")

        results = await asyncio.gather(*tasks, return_exceptions=True)

        policies: dict[str, Any] = {}

        for key, result in zip(policy_keys, results):
            if isinstance(result, Exception):
                logger.error("Failed to assign %s: %s", key, result)
                policies[key] = None
            else:
                policies[key] = result

        return policies

    async def delete_policy_assignment(
        self,
        scope: str,
        assignment_name: str,
        subscription_id: str | None = None,
    ) -> bool:
        """정책 할당을 삭제한다.

        Args:
            scope: 리소스 범위.
            assignment_name: 삭제할 정책 할당 이름.
            subscription_id: 대상 구독 ID. 미지정 시 기본 구독 사용.

        Returns:
            삭제 성공 시 True.

        Raises:
            PolicyNotFoundError: 정책 할당을 찾을 수 없는 경우.
            AzureAuthenticationError: 인증 실패 시.
            PolicyServiceError: 기타 삭제 실패 시.
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


@lru_cache(maxsize=1)
def get_policy_service() -> PolicyService:
    """PolicyService 싱글턴 인스턴스를 반환한다.

    @lru_cache를 통해 스레드 안전한 싱글턴 패턴을 구현한다.

    Returns:
        PolicyService 싱글턴 인스턴스.
    """
    return PolicyService()


policy_service = get_policy_service()
