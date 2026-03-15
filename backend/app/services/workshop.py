"""Workshop 도메인 비즈니스 로직 서비스.

API 라우터에서 분리된 워크샵 생성/조회/삭제 오케스트레이션을 담당한다.
"""
import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Optional

from app.config import settings
from app.exceptions import AppError, InvalidDateRangeError, InvalidInputError, NotFoundError
from app.models import DeletionFailureItem, MessageResponse, WorkshopCreateInput, WorkshopDetail, WorkshopResponse
from app.services.cost import cost_service
from app.services.entra_id import entra_id_service
from app.services.policy import policy_service
from app.services.resource_manager import resource_manager_service
from app.services.storage import storage_service
from app.services.subscription import subscription_service
from app.utils.csv_parser import parse_participants_csv

logger = logging.getLogger(__name__)

WORKSHOP_ALLOWED_LOCATIONS_ASSIGNMENT = "workshop-allowed-locations"
WORKSHOP_DENIED_RESOURCES_ASSIGNMENT = "workshop-denied-resources"
WORKSHOP_ALLOWED_VM_SKUS_ASSIGNMENT = "workshop-allowed-vm-skus"

WORKSHOP_STATUS_ACTIVE = "active"
WORKSHOP_STATUS_COMPLETED = "completed"
WORKSHOP_STATUS_CREATING = "creating"
WORKSHOP_STATUS_FAILED = "failed"
WORKSHOP_STATUS_SCHEDULED = "scheduled"

EXTENDABLE_STATUSES = {WORKSHOP_STATUS_ACTIVE, WORKSHOP_STATUS_SCHEDULED}
DEFAULT_CURRENCY = "USD"
NO_TEMPLATE = "none"

# Workshop dates from the frontend are naive ISO strings in KST (UTC+9)
_KST = timezone(timedelta(hours=9))

# Workshops starting within this window are provisioned immediately
IMMEDIATE_PROVISION_THRESHOLD = timedelta(hours=1)


def _strip_sensitive_participant_data(workshop: dict) -> dict:
    """completed 전환 시 참가자 민감 데이터를 제거한다.

    password, object_id 등 리소스 정리 후 불필요한 민감 정보를 삭제하여
    아카이빙 데이터의 보안 위험을 최소화한다.

    Args:
        workshop: 워크샵 메타데이터 딕셔너리 (in-place 수정).

    Returns:
        민감 데이터가 제거된 워크샵 딕셔너리.
    """
    sensitive_fields = ("password", "object_id")
    for participant in workshop.get("participants", []):
        for field in sensitive_fields:
            participant.pop(field, None)
    return workshop


class WorkshopService:
    """워크샵 수명주기 관련 비즈니스 로직을 담당한다."""

    def __init__(
        self,
        storage=storage_service,
        cost=cost_service,
        entra_id=entra_id_service,
        resource_mgr=resource_manager_service,
        policy=policy_service,
        subscription_service_instance=subscription_service,
    ) -> None:
        self.storage = storage
        self.cost = cost
        self.entra_id = entra_id
        self.resource_mgr = resource_mgr
        self.policy = policy
        self.subscription_service = subscription_service_instance

    @staticmethod
    def build_cost_specs(participants: list[dict]) -> list[dict]:
        """참가자 목록에서 비용 조회용 스펙을 추출한다 (구독 레벨)."""
        return [
            {"subscription_id": participant.get("subscription_id")}
            for participant in participants
            if participant.get("subscription_id")
        ]

    async def get_workshop_or_raise(self, workshop_id: str) -> dict:
        """워크샵 메타데이터를 조회하고 없으면 NotFoundError를 발생시킨다."""
        metadata = await self.storage.get_workshop_metadata(workshop_id)
        if not metadata:
            raise NotFoundError(
                f"Workshop '{workshop_id}' not found",
                resource_type="Workshop",
            )
        return metadata

    async def list_workshops(self) -> list[WorkshopResponse]:
        """전체 워크샵 목록을 조회한다 (비용 정보 제외).

        비용 정보는 별도의 get_workshops_costs()를 통해 lazy-load한다.
        """
        workshops = await self.storage.list_all_workshops()

        return [
            WorkshopResponse(
                id=workshop["id"],
                name=workshop["name"],
                start_date=workshop["start_date"],
                end_date=workshop["end_date"],
                participant_count=len(workshop.get("participants", [])),
                planned_participant_count=len(workshop.get("planned_participants", [])),
                status=workshop.get("status", WORKSHOP_STATUS_ACTIVE),
                created_at=workshop.get("created_at", ""),
                estimated_cost=None,
                currency=DEFAULT_CURRENCY,
                created_by=workshop.get("created_by"),
                description=workshop.get("description"),
                allowed_regions=workshop.get("policy", {}).get("allowed_regions", []),
                deployment_region=workshop.get("deployment_region", ""),
            )
            for workshop in workshops
        ]

    async def get_workshops_costs(self) -> dict[str, dict]:
        """모든 워크샵의 비용을 일괄 조회한다.

        워크샵 목록과 분리하여 비용만 lazy-load할 때 사용한다.

        Returns:
            워크샵 ID를 키로, {estimated_cost, currency}를 값으로 가지는 딕셔너리.
        """
        workshops = await self.storage.list_all_workshops()

        async def _fetch_cost(workshop: dict) -> tuple[str, dict]:
            """단일 워크샵의 비용을 조회한다."""
            workshop_id = workshop["id"]
            participants = workshop.get("participants", [])
            cost_specs = self.build_cost_specs(participants)

            if not cost_specs:
                return workshop_id, {"estimated_cost": 0.0, "currency": DEFAULT_CURRENCY}

            cost_data = await self.cost.get_workshop_total_cost(cost_specs, days=30)
            return workshop_id, {
                "estimated_cost": cost_data.get("total_cost", 0.0),
                "currency": cost_data.get("currency", DEFAULT_CURRENCY),
            }

        results = await asyncio.gather(
            *[_fetch_cost(w) for w in workshops],
            return_exceptions=True,
        )

        costs: dict[str, dict] = {}
        for result in results:
            if isinstance(result, Exception):
                logger.error("Failed to fetch workshop cost: %s", result)
                continue
            workshop_id, cost_info = result
            costs[workshop_id] = cost_info

        return costs

    async def get_workshop_detail(self, workshop_id: str) -> WorkshopDetail:
        """워크샵 상세 정보를 조회한다."""
        metadata = await self.get_workshop_or_raise(workshop_id)

        subscription_data = await self.subscription_service.get_available_subscriptions()
        available_subs = subscription_data.get("subscriptions", [])
        valid_ids = {subscription.get("subscription_id", "").lower() for subscription in available_subs}

        participants_data = metadata.get("participants", [])
        invalid_participants = [
            {
                "alias": participant.get("alias", ""),
                "subscription_id": participant.get("subscription_id", ""),
            }
            for participant in participants_data
            if participant.get("subscription_id")
            and participant.get("subscription_id", "").lower() not in valid_ids
        ]

        cost_specs = self.build_cost_specs(metadata.get("participants", []))
        cost_data = await self.cost.get_workshop_total_cost(cost_specs, days=30)

        return WorkshopDetail(
            id=metadata["id"],
            name=metadata["name"],
            start_date=metadata["start_date"],
            end_date=metadata["end_date"],
            participants=metadata.get("participants", []),
            planned_participants=metadata.get("planned_participants", []),
            planned_participant_count=len(metadata.get("planned_participants", [])),
            base_resources_template=metadata.get("base_resources_template", ""),
            deployment_region=metadata.get("deployment_region", ""),
            policy=metadata.get("policy", {}),
            status=metadata.get("status", WORKSHOP_STATUS_ACTIVE),
            created_at=metadata.get("created_at", ""),
            total_cost=cost_data.get("total_cost", 0.0),
            currency=cost_data.get("currency", DEFAULT_CURRENCY),
            cost_breakdown=cost_data.get("breakdown"),
            survey_url=metadata.get("survey_url") or None,
            available_subscriptions=available_subs,
            invalid_participants=invalid_participants or None,
        )

    async def _rollback_workshop_resources(
        self,
        created_users: list[dict],
        created_rg_specs: list[dict],
        assigned_subscription_ids: list[str],
        workshop_id: str = "",
    ) -> None:
        """워크샵 생성 실패 시 이미 생성된 Azure 리소스를 정리한다.

        정리 순서: 정책 할당 → 리소스 그룹(ARM 배포 포함) → Entra ID 유저(RBAC 포함) → 구독.
        각 단계의 실패는 로그만 남기고 다음 단계를 계속 진행한다.
        구독 해제는 workshop_id로 in_use_map을 역조회하여 고아 alloc도 함께 정리한다.
        """
        if not created_users and not created_rg_specs and not assigned_subscription_ids:
            return

        logger.warning(
            "Rolling back workshop resources: %d users, %d resource groups, %d subscriptions",
            len(created_users),
            len(created_rg_specs),
            len(assigned_subscription_ids),
        )

        # Roll back policy assignments on subscription scope
        for subscription_id in assigned_subscription_ids:
            sub_scope = f"/subscriptions/{subscription_id}"
            for assignment_name in (
                WORKSHOP_ALLOWED_LOCATIONS_ASSIGNMENT,
                WORKSHOP_DENIED_RESOURCES_ASSIGNMENT,
                WORKSHOP_ALLOWED_VM_SKUS_ASSIGNMENT,
            ):
                try:
                    await self.policy.delete_policy_assignment(
                        scope=sub_scope,
                        assignment_name=assignment_name,
                        subscription_id=subscription_id,
                    )
                except Exception as e:
                    logger.warning(
                        "Rollback: failed to remove policy %s on %s: %s",
                        assignment_name,
                        subscription_id,
                        e,
                    )

        if created_rg_specs:
            try:
                await self.resource_mgr.delete_resource_groups_bulk(created_rg_specs)
                logger.info("Rollback: deleted %d resource groups", len(created_rg_specs))
            except Exception as e:
                logger.error("Rollback: failed to delete resource groups: %s", e)

        if created_users:
            upns = [user.get("upn") for user in created_users if user.get("upn")]
            upn_to_object_id = {
                user["upn"]: user["object_id"]
                for user in created_users
                if user.get("upn") and user.get("object_id")
            }
            if upns:
                try:
                    user_status = await self.entra_id.delete_users_bulk(
                        upns, upn_to_object_id=upn_to_object_id,
                    )
                    succeeded = sum(1 for v in user_status.values() if v)
                    failed = len(user_status) - succeeded
                    if failed:
                        logger.warning(
                            "Rollback: deleted %d/%d Entra ID users (%d failed)",
                            succeeded, len(user_status), failed,
                        )
                    else:
                        logger.info("Rollback: deleted %d Entra ID users", succeeded)
                except Exception as e:
                    logger.error("Rollback: failed to delete users: %s", e)

        if assigned_subscription_ids or workshop_id:
            try:
                if workshop_id:
                    # workshop_id 역조회로 해제 — 참가자 목록 불일치·고아 alloc도 처리
                    released = await self.storage.release_subscriptions_by_workshop(workshop_id)
                    logger.info(
                        "Rollback: released %d subscription(s) for workshop %s",
                        len(released), workshop_id,
                    )
                else:
                    await self.storage.release_subscriptions(assigned_subscription_ids)
                    logger.info(
                        "Rollback: released %d subscription(s)", len(assigned_subscription_ids),
                    )
            except Exception as e:
                logger.critical(
                    "Rollback: FAILED to release subscription(s) for workshop %s — "
                    "in_use_map may contain orphaned entries. "
                    "Run admin force-release to recover. Error: %s",
                    workshop_id, e,
                )

        # Delete 'creating' metadata record so it doesn't linger in the workshop list
        if workshop_id:
            try:
                await self.storage.delete_workshop_metadata(workshop_id)
                logger.info("Rollback: deleted creating metadata for workshop %s", workshop_id)
            except Exception as e:
                logger.error(
                    "Rollback: failed to delete creating metadata for workshop %s: %s",
                    workshop_id, e,
                )

    async def _setup_participant(
        self,
        user: dict,
        rg_result: Optional[dict],
        base_resources_template: str,
        regions: list[str],
        denied_services: list[str],
        allowed_vm_skus: list[str] | None = None,
    ) -> Optional[dict]:
        """개별 참가자의 RBAC, ARM 배포, 정책을 설정한다."""
        if not rg_result:
            return None

        try:
            subscription_id = user["subscription_id"]
            sub_scope = f"/subscriptions/{subscription_id}"

            await self.resource_mgr.assign_rbac_role(
                scope=sub_scope,
                principal_id=user["object_id"],
                role_name=settings.default_user_role,
                subscription_id=subscription_id,
            )

            if base_resources_template and base_resources_template != NO_TEMPLATE:
                template = await self.storage.get_template(base_resources_template)
                if template:
                    await self.resource_mgr.deploy_template(
                        resource_group_name=rg_result["name"],
                        template=template,
                        parameters={},
                        subscription_id=subscription_id,
                    )

            await self.policy.assign_workshop_policies(
                scope=sub_scope,
                allowed_locations=regions,
                denied_resource_types=denied_services,
                subscription_id=subscription_id,
                allowed_vm_skus=allowed_vm_skus or [],
            )

            return {
                "alias": user["alias"],
                "upn": user["upn"],
                "password": user["password"],
                "subscription_id": subscription_id,
                "resource_group": rg_result["name"],
                "object_id": user["object_id"],
            }
        except Exception as e:
            logger.error("Failed to setup participant %s: %s", user["alias"], e)
            return None

    async def _validate_vm_skus_for_regions(
        self,
        vm_skus: list[str],
        regions: list[str],
    ) -> None:
        """허용 VM SKU 목록이 선택된 모든 리전에서 사용 가능한지 검증한다."""
        if not vm_skus:
            return

        unique_regions = [region for region in dict.fromkeys(regions) if region]
        missing_skus_by_region: dict[str, list[str]] = {}

        for region in unique_regions:
            available_skus = await self.resource_mgr.list_vm_skus(region)
            available_sku_names = {sku["name"] for sku in available_skus}
            missing_skus = [sku for sku in vm_skus if sku not in available_sku_names]

            if missing_skus:
                missing_skus_by_region[region] = missing_skus

        if not missing_skus_by_region:
            return

        details = []
        for region, missing_skus in missing_skus_by_region.items():
            preview = ", ".join(missing_skus[:5])
            suffix = " ..." if len(missing_skus) > 5 else ""
            details.append(f"{region}: {preview}{suffix}")

        raise InvalidInputError(
            "Some VM SKUs are not available in all selected regions. "
            f"Details: {'; '.join(details)}"
        )

    async def create_workshop(
        self,
        name: str,
        start_date: str,
        end_date: str,
        base_resources_template: str,
        allowed_regions: str,
        denied_services: str,
        allowed_vm_skus: str,
        vm_sku_preset: str,
        deployment_region: str,
        participants_file,
        description: str,
        survey_url: Optional[str],
        user: Optional[dict[str, Any]],
    ) -> WorkshopDetail:
        """새 워크샵을 생성한다.

        start_date가 현재 시각 + 1시간 이내이면 즉시 프로비저닝하고,
        그렇지 않으면 scheduled 상태로 저장하여 Provision Job이 처리하도록 한다.

        Args:
            name: 워크샵 이름.
            start_date: 시작 날짜 (ISO 형식).
            end_date: 종료 날짜 (ISO 형식).
            base_resources_template: 기본 리소스 템플릿 이름.
            allowed_regions: 허용 리전 (쉼표 구분).
            denied_services: 거부 서비스 (쉼표 구분).
            allowed_vm_skus: 허용 VM SKU (쉼표 구분).
            vm_sku_preset: VM SKU 프리셋 이름.
            deployment_region: 배포 리전.
            participants_file: 참가자 CSV 파일.
            description: 워크샵 설명.
            survey_url: 설문 URL.
            user: 생성자 정보.

        Returns:
            생성 또는 예약된 WorkshopDetail.

        Raises:
            InvalidInputError: 입력값이 유효하지 않은 경우.
            InsufficientSubscriptionsError: 구독이 부족한 경우.
        """
        regions = [region.strip() for region in allowed_regions.split(",")]
        services = [service.strip() for service in denied_services.split(",") if service.strip()]
        vm_skus = [sku.strip() for sku in allowed_vm_skus.split(",") if sku.strip()]

        if vm_skus and settings.VM_RESOURCE_TYPE in services:
            logger.warning(
                "VM resource type is denied but allowed_vm_skus provided; "
                "ignoring VM SKU policy (vm_skus=%s)", vm_skus
            )
            vm_skus = []

        await self._validate_vm_skus_for_regions(vm_skus, regions)

        resolved_deployment_region = deployment_region.strip() if deployment_region else ""
        if not resolved_deployment_region:
            resolved_deployment_region = regions[0]
        if resolved_deployment_region not in regions:
            raise InvalidInputError(
                f"Deployment region '{resolved_deployment_region}' is not in "
                f"allowed regions: {regions}"
            )

        try:
            WorkshopCreateInput(
                name=name,
                start_date=start_date,
                end_date=end_date,
                allowed_regions=regions,
                denied_services=services,
                allowed_vm_skus=vm_skus,
            )
        except Exception as e:
            raise InvalidInputError(f"Invalid workshop input: {e}") from e

        workshop_id = str(uuid.uuid4())
        participants = await parse_participants_csv(participants_file)

        # Temporal availability check (soft validation, no actual lock)
        await self.subscription_service.check_temporal_availability(
            start_date, end_date, len(participants),
        )

        created_by = user.get("name", "") if user else ""
        now_utc = datetime.now(UTC)

        base_metadata = {
            "id": workshop_id,
            "name": name,
            "start_date": start_date,
            "end_date": end_date,
            "base_resources_template": base_resources_template,
            "deployment_region": resolved_deployment_region,
            "policy": {
                "allowed_regions": regions,
                "denied_services": services,
                "allowed_vm_skus": vm_skus,
                "vm_sku_preset": vm_sku_preset or None,
            },
            "created_at": now_utc.isoformat(),
            "created_by": created_by,
            "description": description or "",
            "survey_url": survey_url or "",
        }

        # Determine immediate vs scheduled provisioning
        start_dt = datetime.fromisoformat(start_date)
        if start_dt.tzinfo is None:
            # Frontend sends naive datetime-local in KST; match provision.py convention
            start_dt = start_dt.replace(tzinfo=_KST)

        is_immediate = start_dt <= now_utc + IMMEDIATE_PROVISION_THRESHOLD

        if is_immediate:
            return await self._execute_provisioning(
                workshop_id, base_metadata, participants,
            )
        return await self._schedule_workshop(
            workshop_id, base_metadata, participants,
        )

    async def _schedule_workshop(
        self,
        workshop_id: str,
        base_metadata: dict[str, Any],
        participants: list[dict[str, str]],
    ) -> WorkshopDetail:
        """워크샵을 scheduled 상태로 저장한다.

        리소스를 프로비저닝하지 않고, 메타데이터만 저장하여
        Provision Job이 start_date 1시간 전에 프로비저닝하도록 한다.

        Args:
            workshop_id: 워크샵 고유 식별자.
            base_metadata: 공통 메타데이터 (id, name, dates, policy 등).
            participants: CSV에서 파싱된 참가자 목록 [{alias, email}].

        Returns:
            scheduled 상태의 WorkshopDetail.
        """
        planned_participants = [
            {"alias": p["alias"], "email": p["email"]}
            for p in participants
        ]

        metadata = {
            **base_metadata,
            "participants": [],
            "planned_participants": planned_participants,
            "status": WORKSHOP_STATUS_SCHEDULED,
        }
        await self.storage.save_workshop_metadata(workshop_id, metadata)

        logger.info(
            "Workshop '%s' scheduled with %d planned participants (start: %s)",
            base_metadata["name"],
            len(planned_participants),
            base_metadata["start_date"],
        )

        return WorkshopDetail(
            id=workshop_id,
            name=base_metadata["name"],
            start_date=base_metadata["start_date"],
            end_date=base_metadata["end_date"],
            participants=[],
            planned_participants=planned_participants,
            planned_participant_count=len(planned_participants),
            base_resources_template=base_metadata.get("base_resources_template", ""),
            deployment_region=base_metadata.get("deployment_region", ""),
            policy=base_metadata.get("policy", {}),
            status=WORKSHOP_STATUS_SCHEDULED,
            created_at=base_metadata["created_at"],
            total_cost=0.0,
            currency=DEFAULT_CURRENCY,
            survey_url=base_metadata.get("survey_url") or None,
        )

    async def _execute_provisioning(
        self,
        workshop_id: str,
        base_metadata: dict[str, Any],
        participants: list[dict[str, str]],
    ) -> WorkshopDetail:
        """Azure 리소스를 프로비저닝하여 워크샵을 활성화한다.

        구독 할당 → Entra ID 유저 생성 → 리소스 그룹 생성 →
        RBAC/ARM/정책 설정 순서로 프로비저닝한다.
        실패 시 이미 생성된 리소스를 롤백한다.

        Args:
            workshop_id: 워크샵 고유 식별자.
            base_metadata: 공통 메타데이터 (id, name, dates, policy 등).
            participants: 참가자 목록 [{alias, email}].

        Returns:
            활성화된 WorkshopDetail.

        Raises:
            AppError: 참가자 설정이 부분 실패한 경우.
            InvalidInputError: Entra ID 유저 생성에 모두 실패한 경우.
        """
        created_users: list[dict] = []
        created_rg_specs: list[dict] = []
        assigned_subscription_ids: list[str] = []

        name = base_metadata["name"]
        start_date = base_metadata["start_date"]
        end_date = base_metadata["end_date"]
        base_resources_template = base_metadata.get("base_resources_template", "")
        resolved_deployment_region = base_metadata.get("deployment_region", "")
        policy = base_metadata.get("policy", {})
        regions = policy.get("allowed_regions", [])
        services = policy.get("denied_services", [])
        vm_skus = policy.get("allowed_vm_skus", [])
        vm_sku_preset = policy.get("vm_sku_preset")
        survey_url = base_metadata.get("survey_url", "")

        try:
            assignment = await self.subscription_service.assign_subscriptions(
                participants,
                workshop_id,
            )
            participants = assignment["participants"]

            assigned_subscription_ids = list({
                participant["subscription_id"]
                for participant in participants
                if participant.get("subscription_id")
            })

            await self.storage.acquire_subscriptions(assigned_subscription_ids, workshop_id)

            # Save minimal metadata with 'creating' status before resource provisioning
            creating_metadata = {
                **base_metadata,
                "participants": [],
                "planned_participants": [],
                "status": WORKSHOP_STATUS_CREATING,
            }
            await self.storage.save_workshop_metadata(workshop_id, creating_metadata)

            logger.info(
                "Creating workshop '%s' with %d participants",
                name,
                len(participants),
            )

            user_results = await self.entra_id.create_users_bulk(
                [participant["alias"] for participant in participants]
            )
            if not user_results:
                raise InvalidInputError("Failed to create any Entra ID users")
            created_users = user_results

            alias_to_sub = {
                participant["alias"]: participant["subscription_id"]
                for participant in participants
            }
            for created_user in user_results:
                created_user["subscription_id"] = alias_to_sub.get(created_user["alias"], "")

            rg_specs = [
                {
                    "name": (
                        f"{settings.resource_group_prefix}"
                        f"-{workshop_id[:8]}-{created_user['alias']}"
                    ),
                    "location": resolved_deployment_region,
                    "subscription_id": created_user["subscription_id"],
                    "tags": {
                        "workshop_id": workshop_id,
                        "workshop_name": name,
                        "end_date": end_date,
                        "participant": created_user["alias"],
                    },
                }
                for created_user in user_results
            ]
            rg_results = await self.resource_mgr.create_resource_groups_bulk(rg_specs)
            created_rg_specs = [
                {"name": rg_result["name"], "subscription_id": rg_result.get("subscription_id")}
                for rg_result in rg_results
            ]

            setup_tasks = [
                self._setup_participant(
                    user=created_user,
                    rg_result=next(
                        (result for result in rg_results if result["name"] == spec["name"]),
                        None,
                    ),
                    base_resources_template=base_resources_template,
                    regions=regions,
                    denied_services=services,
                    allowed_vm_skus=vm_skus,
                )
                for created_user, spec in zip(user_results, rg_specs)
            ]
            participant_results = await asyncio.gather(*setup_tasks, return_exceptions=True)

            failed_details = []
            successful_participants = []
            for i, result in enumerate(participant_results):
                alias = user_results[i]["alias"]
                if isinstance(result, Exception):
                    failed_details.append(f"{alias}: {result}")
                elif not result:
                    failed_details.append(f"{alias}: setup returned None")
                else:
                    successful_participants.append(result)

            if failed_details:
                logger.error(
                    "%d of %d participant(s) failed to setup: %s",
                    len(failed_details),
                    len(participant_results),
                    "; ".join(failed_details[:10]),
                )
                raise AppError(
                    f"{len(failed_details)} of "
                    f"{len(participant_results)} participant(s) failed to setup.",
                    code="PARTICIPANT_SETUP_FAILED",
                    details={
                        "failed_participants": failed_details[:10],
                        "total": len(participant_results),
                        "failed": len(failed_details),
                    },
                )

            metadata = {
                **base_metadata,
                "participants": successful_participants,
                "planned_participants": [],
                "status": WORKSHOP_STATUS_ACTIVE,
            }
            await self.storage.save_workshop_metadata(workshop_id, metadata)

            logger.info("Workshop created: %s", workshop_id)

            return WorkshopDetail(
                id=workshop_id,
                name=name,
                start_date=start_date,
                end_date=end_date,
                participants=successful_participants,
                base_resources_template=base_resources_template,
                deployment_region=resolved_deployment_region,
                policy=metadata["policy"],
                status=WORKSHOP_STATUS_ACTIVE,
                created_at=base_metadata["created_at"],
                total_cost=0.0,
                currency=DEFAULT_CURRENCY,
                survey_url=survey_url or None,
            )
        except Exception:
            await self._rollback_workshop_resources(
                created_users,
                created_rg_specs,
                assigned_subscription_ids,
                workshop_id=workshop_id,
            )
            raise

    async def extend_end_date(self, workshop_id: str, new_end_date: str) -> MessageResponse:
        """워크샵의 종료 시간을 연장한다.

        기존 end_date보다 뒤로만 연장할 수 있다. active 상태일 때는
        참가자 리소스 그룹의 end_date 태그도 동기화한다 (best-effort).

        Args:
            workshop_id: 워크샵 고유 식별자.
            new_end_date: 새 종료 날짜 (ISO 형식).

        Returns:
            성공 메시지.

        Raises:
            NotFoundError: 워크샵이 존재하지 않는 경우.
            InvalidInputError: 워크샵 상태가 연장 불가능한 경우.
            InvalidDateRangeError: 새 종료일이 기존 종료일 이전이거나 현재 시각 이전인 경우.
            InsufficientSubscriptionsError: 연장 기간에 구독이 부족한 경우.
        """
        metadata = await self.get_workshop_or_raise(workshop_id)

        status = metadata.get("status", "")
        if status not in EXTENDABLE_STATUSES:
            raise InvalidInputError(
                f"Workshop '{workshop_id}' cannot be extended "
                f"(current status: '{status}'). "
                f"Only {EXTENDABLE_STATUSES} workshops can be extended."
            )

        current_end_date = metadata["end_date"]
        current_end_dt = datetime.fromisoformat(current_end_date)
        new_end_dt = datetime.fromisoformat(new_end_date)

        if new_end_dt <= current_end_dt:
            raise InvalidDateRangeError(
                f"New end_date '{new_end_date}' must be after "
                f"current end_date '{current_end_date}'"
            )

        now_utc = datetime.now(UTC)
        # Ensure naive datetimes are treated as UTC for comparison
        new_end_dt_aware = (
            new_end_dt if new_end_dt.tzinfo else new_end_dt.replace(tzinfo=UTC)
        )
        if new_end_dt_aware <= now_utc:
            raise InvalidDateRangeError(
                f"New end_date '{new_end_date}' must be in the future"
            )

        # Check subscription availability for the extended period
        participant_count = max(
            len(metadata.get("participants", [])),
            len(metadata.get("planned_participants", [])),
        )
        await self.subscription_service.check_temporal_availability(
            metadata["start_date"],
            new_end_date,
            participant_count,
            exclude_workshop_id=workshop_id,
        )

        # Update metadata
        metadata["end_date"] = new_end_date
        await self.storage.save_workshop_metadata(workshop_id, metadata)

        logger.info(
            "Extended workshop '%s' end_date: %s -> %s",
            workshop_id, current_end_date, new_end_date,
        )

        # Sync RG tags for active workshops (best-effort)
        if status == WORKSHOP_STATUS_ACTIVE:
            participants = metadata.get("participants", [])
            rg_specs = [
                {
                    "name": p.get("resource_group", ""),
                    "subscription_id": p.get("subscription_id"),
                }
                for p in participants
                if p.get("resource_group")
            ]
            if rg_specs:
                await self.resource_mgr.update_resource_group_tags_bulk(
                    rg_specs, {"end_date": new_end_date},
                )

        return MessageResponse(
            message="Workshop end date extended successfully",
            detail=f"{current_end_date} → {new_end_date}",
        )

    async def provision_scheduled_workshop(self, workshop_id: str) -> WorkshopDetail:
        """예약된 워크샵을 프로비저닝한다.

        Provision Job이 호출한다. scheduled 상태인 워크샵의 planned_participants를
        기반으로 Azure 리소스를 프로비저닝하고 active 상태로 전환한다.

        Args:
            workshop_id: 프로비저닝할 워크샵 ID.

        Returns:
            활성화된 WorkshopDetail.

        Raises:
            NotFoundError: 워크샵이 존재하지 않는 경우.
            InvalidInputError: 워크샵이 scheduled 상태가 아닌 경우.
        """
        metadata = await self.get_workshop_or_raise(workshop_id)

        if metadata.get("status") != WORKSHOP_STATUS_SCHEDULED:
            raise InvalidInputError(
                f"Workshop '{workshop_id}' is not in scheduled status "
                f"(current: {metadata.get('status')})"
            )

        planned = metadata.get("planned_participants", [])
        if not planned:
            raise InvalidInputError(
                f"Workshop '{workshop_id}' has no planned participants"
            )

        participants = [
            {"alias": p["alias"], "email": p["email"]}
            for p in planned
        ]

        base_metadata = {
            "id": workshop_id,
            "name": metadata["name"],
            "start_date": metadata["start_date"],
            "end_date": metadata["end_date"],
            "base_resources_template": metadata.get("base_resources_template", ""),
            "deployment_region": metadata.get("deployment_region", ""),
            "policy": metadata.get("policy", {}),
            "created_at": metadata.get("created_at", ""),
            "created_by": metadata.get("created_by", ""),
            "description": metadata.get("description", ""),
            "survey_url": metadata.get("survey_url", ""),
        }

        logger.info(
            "Provisioning scheduled workshop '%s' (%s) with %d participants",
            metadata["name"],
            workshop_id,
            len(participants),
        )

        return await self._execute_provisioning(
            workshop_id, base_metadata, participants,
        )

    async def delete_workshop(self, workshop_id: str) -> MessageResponse:
        """워크샵과 관련 리소스를 모두 삭제한다 (구독별 지원).

        scheduled 상태인 워크샵은 리소스가 없으므로 메타데이터만 삭제한다.
        """
        metadata = await self.get_workshop_or_raise(workshop_id)

        # Completed workshops are already cleaned up — no further deletion allowed
        if metadata.get("status") == WORKSHOP_STATUS_COMPLETED:
            return MessageResponse(
                message="Workshop already completed",
                detail="This workshop has already been cleaned up and archived.",
            )

        # Scheduled workshops have no Azure resources — metadata-only deletion
        if metadata.get("status") == WORKSHOP_STATUS_SCHEDULED:
            try:
                released = await self.storage.release_subscriptions_by_workshop(workshop_id)
                if released:
                    logger.info(
                        "Released %d subscription(s) for scheduled workshop %s",
                        len(released), workshop_id,
                    )
            except Exception as e:
                logger.warning(
                    "Failed to release subscriptions for scheduled workshop %s: %s",
                    workshop_id, e,
                )

            await self.storage.delete_workshop_metadata(workshop_id)
            planned_count = len(metadata.get("planned_participants", []))
            logger.info("Scheduled workshop deleted: %s", workshop_id)

            return MessageResponse(
                message="Scheduled workshop deleted successfully",
                detail=f"Removed scheduled workshop with {planned_count} planned participants",
            )

        participants = metadata.get("participants", [])
        workshop_name = metadata.get("name", "")

        rg_specs = []
        subscription_ids_to_release: list[str] = []

        for participant in participants:
            subscription_id = participant.get("subscription_id")
            rg_name = participant.get("resource_group")

            if subscription_id:
                subscription_ids_to_release.append(subscription_id)

                sub_scope = f"/subscriptions/{subscription_id}"
                for assignment_name in (
                    WORKSHOP_ALLOWED_LOCATIONS_ASSIGNMENT,
                    WORKSHOP_DENIED_RESOURCES_ASSIGNMENT,
                    WORKSHOP_ALLOWED_VM_SKUS_ASSIGNMENT,
                ):
                    try:
                        await self.policy.delete_policy_assignment(
                            scope=sub_scope,
                            assignment_name=assignment_name,
                            subscription_id=subscription_id,
                        )
                    except Exception as e:
                        logger.warning(
                            "Failed to remove policy %s on %s: %s",
                            assignment_name,
                            subscription_id,
                            e,
                        )

            if rg_name:
                rg_specs.append({
                    "name": rg_name,
                    "subscription_id": subscription_id,
                })

        rg_status = await self.resource_mgr.delete_resource_groups_bulk(rg_specs)

        upns = [participant.get("upn") for participant in participants]
        upn_to_object_id = {
            p["upn"]: p["object_id"]
            for p in participants
            if p.get("upn") and p.get("object_id")
        }
        user_status = await self.entra_id.delete_users_bulk(
            upns, upn_to_object_id=upn_to_object_id,
        )

        failures: list[DeletionFailureItem] = []
        now_iso = datetime.now(UTC).isoformat()

        for spec in rg_specs:
            rg_name = spec["name"]
            if rg_name and not rg_status.get(rg_name, False):
                failures.append(
                    DeletionFailureItem(
                        id=str(uuid.uuid4()),
                        workshop_id=workshop_id,
                        workshop_name=workshop_name,
                        resource_type="resource_group",
                        resource_name=rg_name,
                        subscription_id=spec.get("subscription_id"),
                        error_message=f"Failed to delete resource group '{rg_name}'",
                        failed_at=now_iso,
                        status="pending",
                        retry_count=0,
                    )
                )

        for participant in participants:
            upn = participant.get("upn")
            if upn and not user_status.get(upn, False):
                failures.append(
                    DeletionFailureItem(
                        id=str(uuid.uuid4()),
                        workshop_id=workshop_id,
                        workshop_name=workshop_name,
                        resource_type="user",
                        resource_name=upn,
                        subscription_id=None,
                        error_message=f"Failed to delete user '{upn}'",
                        failed_at=now_iso,
                        status="pending",
                        retry_count=0,
                    )
                )

        if failures:
            for failure in failures:
                await self.storage.save_deletion_failure(failure)

            metadata["status"] = WORKSHOP_STATUS_FAILED
            await self.storage.save_workshop_metadata(workshop_id, metadata)

            try:
                # workshop_id 역조회로 해제 — 참가자 목록 불일치·고아 alloc도 함께 처리
                released = await self.storage.release_subscriptions_by_workshop(workshop_id)
                logger.info(
                    "Released %d subscription(s) during partial delete of workshop %s",
                    len(released), workshop_id,
                )
            except Exception as e:
                logger.error(
                    "Failed to release subscriptions after partial deletion of workshop %s: %s",
                    workshop_id, e,
                )

            logger.warning(
                "Workshop %s deletion partially failed: %d failures",
                workshop_id,
                len(failures),
            )

            return MessageResponse(
                message="Workshop deletion partially failed",
                detail=(
                    f"{len(failures)} resource(s) failed to delete. "
                    "Check the deletion failures tab for details."
                ),
            )

        try:
            # workshop_id 역조회로 해제 — 참가자 목록과 in_use_map 불일치도 커버
            released = await self.storage.release_subscriptions_by_workshop(workshop_id)
            logger.info(
                "Released %d subscription(s) for workshop %s",
                len(released), workshop_id,
            )
        except Exception as e:
            logger.error(
                "Failed to release subscriptions after deletion of workshop %s: %s",
                workshop_id, e,
            )

        _strip_sensitive_participant_data(metadata)
        metadata["status"] = WORKSHOP_STATUS_COMPLETED
        await self.storage.save_workshop_metadata(workshop_id, metadata)

        logger.info("Workshop completed: %s", workshop_id)

        return MessageResponse(
            message="Workshop deleted successfully",
            detail=f"Deleted {len(participants)} participants and their resources",
        )


workshop_service = WorkshopService()
