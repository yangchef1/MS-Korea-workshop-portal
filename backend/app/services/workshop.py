"""Workshop 도메인 비즈니스 로직 서비스.

API 라우터에서 분리된 워크샵 생성/조회/삭제 오케스트레이션을 담당한다.
"""
import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Optional

from app.config import settings
from app.exceptions import AppError, InvalidInputError, NotFoundError
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
WORKSHOP_STATUS_CREATING = "creating"
WORKSHOP_STATUS_FAILED = "failed"
DEFAULT_CURRENCY = "USD"
NO_TEMPLATE = "none"


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
        """전체 워크샵 목록을 비용 정보와 함께 조회한다."""
        workshops = await self.storage.list_all_workshops()

        async def _enrich_workshop(workshop: dict) -> WorkshopResponse:
            participants = workshop.get("participants", [])
            cost_specs = self.build_cost_specs(participants)

            estimated_cost = 0.0
            currency = DEFAULT_CURRENCY

            if cost_specs:
                cost_data = await self.cost.get_workshop_total_cost(cost_specs, days=30)
                estimated_cost = cost_data.get("total_cost", 0.0)
                currency = cost_data.get("currency", DEFAULT_CURRENCY)

            policy_data = workshop.get("policy", {})
            return WorkshopResponse(
                id=workshop["id"],
                name=workshop["name"],
                start_date=workshop["start_date"],
                end_date=workshop["end_date"],
                participant_count=len(participants),
                status=workshop.get("status", WORKSHOP_STATUS_ACTIVE),
                created_at=workshop.get("created_at", ""),
                estimated_cost=estimated_cost,
                currency=currency,
                created_by=workshop.get("created_by"),
                description=workshop.get("description"),
                allowed_regions=policy_data.get("allowed_regions", []),
                deployment_region=workshop.get("deployment_region", ""),
            )

        return await asyncio.gather(*[_enrich_workshop(workshop) for workshop in workshops])

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
            if upns:
                try:
                    await self.entra_id.delete_users_bulk(upns)
                    logger.info("Rollback: deleted %d Entra ID users", len(upns))
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
        """새 워크샵을 생성한다."""
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

        created_users: list[dict] = []
        created_rg_specs: list[dict] = []
        assigned_subscription_ids: list[str] = []

        try:
            workshop_id = str(uuid.uuid4())
            participants = await parse_participants_csv(participants_file)
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
                "id": workshop_id,
                "name": name,
                "start_date": start_date,
                "end_date": end_date,
                "participants": [],
                "base_resources_template": base_resources_template,
                "deployment_region": resolved_deployment_region,
                "policy": {
                    "allowed_regions": regions,
                    "denied_services": services,
                    "allowed_vm_skus": vm_skus,
                    "vm_sku_preset": vm_sku_preset or None,
                },
                "status": WORKSHOP_STATUS_CREATING,
                "created_at": datetime.now(UTC).isoformat(),
                "created_by": user.get("name", "") if user else "",
                "description": description or "",
                "survey_url": survey_url or "",
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
                    f"Workshop creation failed: {len(failed_details)} of "
                    f"{len(participant_results)} participant(s) failed to setup. "
                    f"Details: {'; '.join(failed_details[:5])}",
                    code="PARTICIPANT_SETUP_FAILED",
                )

            metadata = {
                "id": workshop_id,
                "name": name,
                "start_date": start_date,
                "end_date": end_date,
                "participants": successful_participants,
                "base_resources_template": base_resources_template,
                "deployment_region": resolved_deployment_region,
                "policy": {
                    "allowed_regions": regions,
                    "denied_services": services,
                    "allowed_vm_skus": vm_skus,
                    "vm_sku_preset": vm_sku_preset or None,
                },
                "status": WORKSHOP_STATUS_ACTIVE,
                "created_at": datetime.now(UTC).isoformat(),
                "created_by": user.get("name", "") if user else "",
                "description": description or "",
                "survey_url": survey_url or "",
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
                created_at=metadata["created_at"],
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

    async def delete_workshop(self, workshop_id: str) -> MessageResponse:
        """워크샵과 관련 리소스를 모두 삭제한다 (구독별 지원)."""
        metadata = await self.get_workshop_or_raise(workshop_id)
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
        user_status = await self.entra_id.delete_users_bulk(upns)

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

        await self.storage.delete_workshop_metadata(workshop_id)

        logger.info("Workshop deleted: %s", workshop_id)

        return MessageResponse(
            message="Workshop deleted successfully",
            detail=f"Deleted {len(participants)} participants and their resources",
        )


workshop_service = WorkshopService()
