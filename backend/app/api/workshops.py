"""워크샵 API 라우터.

워크샵 생명주기(생성, 조회, 삭제)와 관련 리소스(비용, 비밀번호, 이메일)를
관리하는 엔드포인트를 제공한다.
"""
import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from app.config import settings
from app.core.deps import (
    get_cost_service,
    get_email_service,
    get_entra_id_service,
    get_policy_service,
    get_resource_manager_service,
    get_storage_service,
)
from app.exceptions import InvalidInputError, NotFoundError
from app.models import (
    CostResponse,
    DeletionFailureItem,
    DeletionFailureListResponse,
    MessageResponse,
    PolicyData,
    SurveyUrlUpdate,
    WorkshopCreateInput,
    WorkshopDetail,
    WorkshopResponse,
)
from app.utils.csv_parser import generate_passwords_csv, parse_participants_csv

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workshops", tags=["Workshops"])


async def _rollback_workshop_resources(
    created_users: list[dict],
    created_rg_specs: list[dict],
    entra_id,
    resource_mgr,
) -> None:
    """워크샵 생성 실패 시 이미 생성된 Azure 리소스를 정리한다.

    보상 트랜잭션(Saga) 패턴으로, 후속 단계 오류 시 좀비 리소스가
    남지 않도록 역순으로 rollback을 수행한다.
    각 rollback 단계의 실패는 로깅만 하고 나머지 정리를 계속 진행한다.

    Args:
        created_users: 생성된 Entra ID 사용자 목록.
        created_rg_specs: 생성된 리소스 그룹 스펙 (name, subscription_id).
        entra_id: EntraIDService 인스턴스.
        resource_mgr: ResourceManagerService 인스턴스.
    """
    if not created_users and not created_rg_specs:
        return

    logger.warning(
        "Rolling back workshop resources: %d users, %d resource groups",
        len(created_users),
        len(created_rg_specs),
    )

    # 역순: 리소스 그룹 먼저 삭제 (비용 발생 리소스 포함)
    if created_rg_specs:
        try:
            await resource_mgr.delete_resource_groups_bulk(created_rg_specs)
            logger.info("Rollback: deleted %d resource groups", len(created_rg_specs))
        except Exception as e:
            logger.error("Rollback: failed to delete resource groups: %s", e)

    # 그 다음 Entra ID 사용자 삭제
    if created_users:
        upns = [u.get('upn') for u in created_users if u.get('upn')]
        if upns:
            try:
                await entra_id.delete_users_bulk(upns)
                logger.info("Rollback: deleted %d Entra ID users", len(upns))
            except Exception as e:
                logger.error("Rollback: failed to delete users: %s", e)


class ResourceType(BaseModel):
    """Azure 리소스 유형."""

    value: str
    label: str
    category: str


class EmailSendResponse(BaseModel):
    """이메일 전송 결과."""

    total: int
    sent: int
    failed: int
    results: dict


@router.get("/resource-types", response_model=list[ResourceType])
async def get_resource_types(resource_manager=Depends(get_resource_manager_service)):
    """Azure 리소스 유형 목록을 조회한다 (24시간 캐시)."""
    try:
        resource_types_data = await resource_manager.get_resource_types()
        return [
            ResourceType(
                value=rt.get("value", ""),
                label=rt.get("label", ""),
                category=rt.get("category", ""),
            )
            for rt in resource_types_data
        ]
    except Exception as e:
        logger.error("Failed to get resource types: %s", e)
        return []


def _build_cost_specs(participants: list[dict]) -> list[dict]:
    """참가자 목록에서 비용 조회용 스펙을 추출한다."""
    return [
        {
            "resource_group": p.get("resource_group"),
            "subscription_id": p.get("subscription_id"),
        }
        for p in participants
    ]


async def _get_workshop_or_raise(storage, workshop_id: str) -> dict:
    """워크샵 메타데이터를 조회하고 없으면 NotFoundError를 발생시킨다.

    Args:
        storage: StorageService 인스턴스.
        workshop_id: 워크샵 ID.

    Returns:
        워크샵 메타데이터 딕셔너리.

    Raises:
        NotFoundError: 워크샵을 찾을 수 없는 경우.
    """
    metadata = await storage.get_workshop_metadata(workshop_id)
    if not metadata:
        raise NotFoundError(
            f"Workshop '{workshop_id}' not found",
            resource_type="Workshop",
        )
    return metadata


@router.get("", response_model=list[WorkshopResponse])
async def list_workshops(
    storage=Depends(get_storage_service),
    cost=Depends(get_cost_service),
):
    """전체 워크샵 목록을 비용 정보와 함께 조회한다."""
    workshops = await storage.list_all_workshops()

    async def _enrich_workshop(workshop: dict) -> WorkshopResponse:
        participants = workshop.get("participants", [])
        cost_specs = _build_cost_specs(participants)

        estimated_cost = 0.0
        currency = "USD"

        if cost_specs:
            cost_data = await cost.get_workshop_total_cost(cost_specs, days=30)
            estimated_cost = cost_data.get("total_cost", 0.0)
            currency = cost_data.get("currency", "USD")

        return WorkshopResponse(
            id=workshop["id"],
            name=workshop["name"],
            start_date=workshop["start_date"],
            end_date=workshop["end_date"],
            participant_count=len(participants),
            status=workshop.get("status", "active"),
            created_at=workshop.get("created_at", ""),
            estimated_cost=estimated_cost,
            currency=currency,
        )

    return await asyncio.gather(*[_enrich_workshop(w) for w in workshops])


@router.get("/{workshop_id}", response_model=WorkshopDetail)
async def get_workshop(
    workshop_id: str,
    storage=Depends(get_storage_service),
    cost=Depends(get_cost_service),
):
    """워크샵 상세 정보를 조회한다."""
    metadata = await _get_workshop_or_raise(storage, workshop_id)

    cost_specs = _build_cost_specs(metadata.get("participants", []))
    cost_data = await cost.get_workshop_total_cost(cost_specs, days=30)

    return WorkshopDetail(
        id=metadata["id"],
        name=metadata["name"],
        start_date=metadata["start_date"],
        end_date=metadata["end_date"],
        participants=metadata.get("participants", []),
        base_resources_template=metadata.get("base_resources_template", ""),
        policy=metadata.get("policy", {}),
        status=metadata.get("status", "active"),
        created_at=metadata.get("created_at", ""),
        total_cost=cost_data.get("total_cost", 0.0),
        currency=cost_data.get("currency", "USD"),
        cost_breakdown=cost_data.get("breakdown"),
        survey_url=metadata.get("survey_url") or None,
    )


async def _setup_participant(
    user: dict,
    rg_result: Optional[dict],
    base_resources_template: str,
    regions: list[str],
    services: list[str],
    storage,
    resource_mgr,
    policy,
) -> Optional[dict]:
    """개별 참가자의 RBAC, ARM 배포, 정책을 설정한다.

    Args:
        user: Entra ID 사용자 정보.
        rg_result: 생성된 리소스 그룹 정보 (없으면 None 반환).
        base_resources_template: ARM 템플릿 이름.
        regions: 허용 리전 목록.
        services: 허용 서비스 목록.
        storage: StorageService 인스턴스.
        resource_mgr: ResourceManagerService 인스턴스.
        policy: PolicyService 인스턴스.

    Returns:
        참가자 데이터 딕셔너리 또는 실패 시 None.
    """
    if not rg_result:
        return None

    try:
        subscription_id = user["subscription_id"]

        await resource_mgr.assign_rbac_role(
            scope=rg_result["id"],
            principal_id=user["object_id"],
            role_name=settings.default_user_role,
            subscription_id=subscription_id,
        )

        if base_resources_template and base_resources_template != "none":
            template = await storage.get_template(base_resources_template)
            if template:
                await resource_mgr.deploy_template(
                    resource_group_name=rg_result["name"],
                    template=template,
                    parameters={},
                    subscription_id=subscription_id,
                )

        # Policy scope: resource group level to isolate participants in the same subscription
        rg_scope = f"/subscriptions/{subscription_id}/resourceGroups/{rg_result['name']}"
        await policy.assign_workshop_policies(
            scope=rg_scope,
            allowed_locations=regions,
            allowed_resource_types=services,
            subscription_id=subscription_id,
        )

        return {
            "alias": user["alias"],
            "email": user.get("email", ""),
            "upn": user["upn"],
            "password": user["password"],
            "subscription_id": subscription_id,
            "resource_group": rg_result["name"],
            "object_id": user["object_id"],
        }
    except Exception as e:
        logger.error("Failed to setup participant %s: %s", user["alias"], e)
        return None


@router.post("", response_model=WorkshopDetail)
async def create_workshop(
    name: str = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...),
    base_resources_template: str = Form(...),
    allowed_regions: str = Form(...),
    allowed_services: str = Form(...),
    participants_file: UploadFile = File(...),
    survey_url: Optional[str] = Form(default=None, description="M365 Forms 만족도 조사 URL"),
    storage=Depends(get_storage_service),
    entra_id=Depends(get_entra_id_service),
    resource_mgr=Depends(get_resource_manager_service),
    policy=Depends(get_policy_service),
):
    """새 워크샵을 생성한다.

    CSV 형식: 이메일만 포함하는 단일 컬럼 또는 이메일+subscription_id 2컬럼.
    Azure 리소스 생성 후 DB 저장이 실패하면 보상 트랜잭션(rollback)을 수행한다.
    """
    # Step 0: 입력값 사전 검증 (Azure 리소스 생성 전에 빠르게 실패)
    regions = [r.strip() for r in allowed_regions.split(",")]
    services = [s.strip() for s in allowed_services.split(",")]
    try:
        WorkshopCreateInput(
            name=name,
            start_date=start_date,
            end_date=end_date,
            allowed_regions=regions,
            allowed_services=services,
        )
    except Exception as e:
        raise InvalidInputError(f"Invalid workshop input: {e}") from e

    created_users: list[dict] = []
    created_rg_specs: list[dict] = []

    try:
        workshop_id = str(uuid.uuid4())
        participants = await parse_participants_csv(participants_file)

        logger.info(
            "Creating workshop '%s' with %d participants",
            name,
            len(participants),
        )

        # Step 1: Entra ID 사용자 생성
        user_results = await entra_id.create_users_bulk(
            [p["alias"] for p in participants]
        )
        if not user_results:
            raise InvalidInputError("Failed to create any Entra ID users")
        created_users = user_results

        alias_to_email = {p["alias"]: p["email"] for p in participants}
        alias_to_sub = {p["alias"]: p["subscription_id"] for p in participants}
        for user in user_results:
            user["email"] = alias_to_email.get(user["alias"], "")
            user["subscription_id"] = alias_to_sub.get(
                user["alias"], settings.azure_subscription_id
            )

        # Step 2: 리소스 그룹 생성
        rg_specs = [
            {
                "name": (
                    f"{settings.resource_group_prefix}"
                    f"-{workshop_id[:8]}-{user['alias']}"
                ),
                "location": regions[0],
                "subscription_id": user["subscription_id"],
                "tags": {
                    "workshop_id": workshop_id,
                    "workshop_name": name,
                    "end_date": end_date,
                    "participant": user["alias"],
                },
            }
            for user in user_results
        ]
        rg_results = await resource_mgr.create_resource_groups_bulk(rg_specs)
        created_rg_specs = [
            {"name": rg["name"], "subscription_id": rg.get("subscription_id")}
            for rg in rg_results
        ]

        # Step 3: 참가자별 설정 (RBAC, ARM 배포, 정책)
        setup_tasks = [
            _setup_participant(
                user=user,
                rg_result=next(
                    (r for r in rg_results if r["name"] == spec["name"]), None
                ),
                base_resources_template=base_resources_template,
                regions=regions,
                services=services,
                storage=storage,
                resource_mgr=resource_mgr,
                policy=policy,
            )
            for user, spec in zip(user_results, rg_specs)
        ]
        participant_results = await asyncio.gather(
            *setup_tasks, return_exceptions=True
        )
        successful_participants = [
            p
            for p in participant_results
            if p and not isinstance(p, Exception)
        ]

        # Step 4: Table Storage 저장
        metadata = {
            "id": workshop_id,
            "name": name,
            "start_date": start_date,
            "end_date": end_date,
            "participants": successful_participants,
            "base_resources_template": base_resources_template,
            "policy": {"allowed_regions": regions, "allowed_services": services},
            "status": "active",
            "created_at": datetime.now(UTC).isoformat(),
            "survey_url": survey_url or "",
        }
        await storage.save_workshop_metadata(workshop_id, metadata)

        csv_content = generate_passwords_csv(successful_participants)
        await storage.save_passwords_csv(workshop_id, csv_content)

        logger.info("Workshop created: %s", workshop_id)

        return WorkshopDetail(
            id=workshop_id,
            name=name,
            start_date=start_date,
            end_date=end_date,
            participants=successful_participants,
            base_resources_template=base_resources_template,
            policy=metadata["policy"],
            status="active",
            created_at=metadata["created_at"],
            total_cost=0.0,
            currency="USD",
            survey_url=survey_url or None,
        )
    except Exception:
        await _rollback_workshop_resources(
            created_users, created_rg_specs, entra_id, resource_mgr
        )
        raise


@router.delete("/{workshop_id}", response_model=MessageResponse)
async def delete_workshop(
    workshop_id: str,
    storage=Depends(get_storage_service),
    entra_id=Depends(get_entra_id_service),
    resource_mgr=Depends(get_resource_manager_service),
):
    """워크샵과 관련 리소스를 모두 삭제한다 (구독별 지원).

    삭제 실패 항목이 있으면 status를 'failed'로 변경하고 메타데이터를 유지한다.
    """
    metadata = await _get_workshop_or_raise(storage, workshop_id)
    participants = metadata.get("participants", [])
    workshop_name = metadata.get("name", "")

    # Step 1: 리소스 그룹 삭제
    rg_specs = [
        {
            "name": p.get("resource_group"),
            "subscription_id": p.get("subscription_id"),
        }
        for p in participants
    ]
    rg_status = await resource_mgr.delete_resource_groups_bulk(rg_specs)

    # Step 2: Entra ID 사용자 삭제
    upns = [p.get("upn") for p in participants]
    user_status = await entra_id.delete_users_bulk(upns)

    # Step 3: 실패 항목 추적
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

    for p in participants:
        upn = p.get("upn")
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
        # 실패 항목 저장 및 status 변경
        for failure in failures:
            await storage.save_deletion_failure(failure)

        metadata["status"] = "failed"
        await storage.save_workshop_metadata(workshop_id, metadata)

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

    # 전부 성공 → 메타데이터 삭제
    await storage.delete_workshop_metadata(workshop_id)

    logger.info("Workshop deleted: %s", workshop_id)

    return MessageResponse(
        message="Workshop deleted successfully",
        detail=f"Deleted {len(participants)} participants and their resources",
    )


# ------------------------------------------------------------------
# Deletion failure endpoints
# ------------------------------------------------------------------


@router.get(
    "/{workshop_id}/deletion-failures",
    response_model=DeletionFailureListResponse,
)
async def list_deletion_failures(
    workshop_id: str,
    storage=Depends(get_storage_service),
):
    """워크샵의 삭제 실패 항목 목록을 조회한다."""
    await _get_workshop_or_raise(storage, workshop_id)

    items = await storage.list_deletion_failures_by_workshop(workshop_id)

    return DeletionFailureListResponse(
        items=[DeletionFailureItem(**item) for item in items],
        total_count=len(items),
    )


async def _retry_single_failure(
    failure: dict,
    workshop_id: str,
    storage,
    resource_mgr,
    entra_id,
) -> bool:
    """단일 삭제 실패 항목에 대해 재시도를 수행한다.

    성공 시 failure 레코드를 삭제하고 True를 반환한다.
    실패 시 retry_count를 증가시키고 False를 반환한다.

    Args:
        failure: 삭제 실패 항목 dict.
        workshop_id: 워크샵 ID.
        storage: StorageService 인스턴스.
        resource_mgr: ResourceManagerService 인스턴스.
        entra_id: EntraIDService 인스턴스.

    Returns:
        재시도 성공 여부.
    """
    failure_id = failure["id"]
    resource_type = failure["resource_type"]
    resource_name = failure["resource_name"]

    try:
        if resource_type == "resource_group":
            await resource_mgr.delete_resource_group(
                name=resource_name,
                subscription_id=failure.get("subscription_id"),
            )
        elif resource_type == "user":
            await entra_id.delete_user(resource_name)

        await storage.delete_deletion_failure(failure_id, workshop_id)
        logger.info(
            "Retry succeeded for %s '%s' (workshop: %s)",
            resource_type,
            resource_name,
            workshop_id,
        )
        return True

    except Exception as e:
        logger.error(
            "Retry failed for %s '%s': %s",
            resource_type,
            resource_name,
            e,
        )
        await storage.update_deletion_failure(
            failure_id,
            workshop_id,
            {
                "retry_count": failure.get("retry_count", 0) + 1,
                "error_message": str(e),
            },
        )
        return False


async def _finalize_workshop_if_resolved(
    workshop_id: str, storage
) -> bool:
    """워크샵의 모든 삭제 실패가 해결되었으면 메타데이터를 정리한다.

    Args:
        workshop_id: 워크샵 ID.
        storage: StorageService 인스턴스.

    Returns:
        워크샵이 정리되었으면 True.
    """
    remaining = await storage.list_deletion_failures_by_workshop(workshop_id)
    if remaining:
        return False

    await storage.delete_workshop_metadata(workshop_id)
    logger.info(
        "All failures resolved — workshop %s metadata deleted",
        workshop_id,
    )
    return True


@router.post(
    "/{workshop_id}/deletion-failures/{failure_id}/retry",
    response_model=MessageResponse,
)
async def retry_deletion(
    workshop_id: str,
    failure_id: str,
    storage=Depends(get_storage_service),
    resource_mgr=Depends(get_resource_manager_service),
    entra_id=Depends(get_entra_id_service),
):
    """삭제 실패 항목을 수동으로 재시도한다."""
    await _get_workshop_or_raise(storage, workshop_id)

    items = await storage.list_deletion_failures_by_workshop(workshop_id)
    failure = next((f for f in items if f["id"] == failure_id), None)
    if not failure:
        raise NotFoundError(
            f"Deletion failure '{failure_id}' not found in workshop '{workshop_id}'",
            resource_type="DeletionFailure",
        )

    success = await _retry_single_failure(
        failure, workshop_id, storage, resource_mgr, entra_id
    )

    if success:
        workshop_finalized = await _finalize_workshop_if_resolved(
            workshop_id, storage
        )
        detail = "Resource deleted successfully"
        if workshop_finalized:
            detail += ". All failures resolved — workshop cleaned up."
        return MessageResponse(message="Retry succeeded", detail=detail)

    return MessageResponse(
        message="Retry failed",
        detail="The resource could not be deleted. Check error details.",
    )


@router.post(
    "/{workshop_id}/deletion-failures/retry-all",
    response_model=MessageResponse,
)
async def retry_all_deletions(
    workshop_id: str,
    storage=Depends(get_storage_service),
    resource_mgr=Depends(get_resource_manager_service),
    entra_id=Depends(get_entra_id_service),
):
    """워크샵의 모든 삭제 실패 항목을 일괄 재시도한다."""
    await _get_workshop_or_raise(storage, workshop_id)

    items = await storage.list_deletion_failures_by_workshop(workshop_id)
    if not items:
        return MessageResponse(
            message="No failures to retry",
            detail="There are no pending deletion failures for this workshop.",
        )

    succeeded = 0
    failed = 0
    for failure in items:
        ok = await _retry_single_failure(
            failure, workshop_id, storage, resource_mgr, entra_id
        )
        if ok:
            succeeded += 1
        else:
            failed += 1

    workshop_finalized = await _finalize_workshop_if_resolved(
        workshop_id, storage
    )
    detail = f"{succeeded} succeeded, {failed} failed"
    if workshop_finalized:
        detail += ". All failures resolved — workshop cleaned up."

    return MessageResponse(
        message="Retry all completed",
        detail=detail,
    )


@router.get("/{workshop_id}/passwords", response_class=Response)
async def download_passwords(
    workshop_id: str,
    storage=Depends(get_storage_service),
):
    """참가자 비밀번호 CSV 파일을 다운로드한다."""
    csv_content = await storage.get_passwords_csv(workshop_id)
    if not csv_content:
        raise NotFoundError(
            f"Passwords file for workshop '{workshop_id}' not found",
            resource_type="PasswordsCSV",
        )

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f"attachment; filename=workshop-{workshop_id}-passwords.csv"
            )
        },
    )


@router.get("/{workshop_id}/resources")
async def get_workshop_resources(
    workshop_id: str,
    storage=Depends(get_storage_service),
    resource_mgr=Depends(get_resource_manager_service),
):
    """워크샵 리소스 그룹 내 모든 리소스를 조회한다 (구독별 지원)."""
    metadata = await _get_workshop_or_raise(storage, workshop_id)
    participants = metadata.get("participants", [])
    all_resources = []

    for participant in participants:
        rg_name = participant.get("resource_group")
        subscription_id = participant.get("subscription_id")
        if not rg_name:
            continue

        resources = await resource_mgr.list_resources_in_group(
            rg_name, subscription_id=subscription_id
        )
        for resource in resources:
            resource["participant"] = participant.get("alias", "")
            resource["resource_group"] = rg_name
            resource["subscription_id"] = subscription_id
        all_resources.extend(resources)

    return {
        "workshop_id": workshop_id,
        "total_count": len(all_resources),
        "resources": all_resources,
    }


@router.get("/{workshop_id}/cost", response_model=CostResponse)
async def get_workshop_cost(
    workshop_id: str,
    use_workshop_period: bool = True,
    storage=Depends(get_storage_service),
    cost=Depends(get_cost_service),
):
    """워크샵 기간 기반 비용 상세를 조회한다 (구독별 지원)."""
    metadata = await _get_workshop_or_raise(storage, workshop_id)
    cost_specs = _build_cost_specs(metadata.get("participants", []))

    if use_workshop_period:
        start_date = metadata.get("start_date")
        end_date = metadata.get("end_date")
        cost_data = await cost.get_workshop_total_cost(
            cost_specs, start_date=start_date, end_date=end_date
        )
        cost_data["start_date"] = start_date
        cost_data["end_date"] = end_date
    else:
        cost_data = await cost.get_workshop_total_cost(cost_specs, days=30)

    return CostResponse(**cost_data)


@router.post("/{workshop_id}/send-credentials", response_model=EmailSendResponse)
async def send_credentials_email(
    workshop_id: str,
    participant_emails: Optional[list[str]] = Query(
        default=None,
        description="전송 대상 참가자 이메일. 미지정 시 전체 참가자에게 전송.",
    ),
    storage=Depends(get_storage_service),
    email=Depends(get_email_service),
):
    """워크샵 참가자에게 자격 증명 이메일을 전송한다."""
    metadata = await _get_workshop_or_raise(storage, workshop_id)

    workshop_name = metadata.get("name", "Azure Workshop")
    all_participants = metadata.get("participants", [])

    if participant_emails:
        lower_emails = {e.lower() for e in participant_emails}
        participants_to_send = [
            p for p in all_participants
            if p.get("email", "").lower() in lower_emails
        ]
        if not participants_to_send:
            raise InvalidInputError(
                "No matching participants found for provided emails"
            )
    else:
        participants_to_send = all_participants

    participants_with_email = [p for p in participants_to_send if p.get("email")]
    if not participants_with_email:
        raise InvalidInputError(
            "No participants have email addresses configured"
        )

    results = await email.send_credentials_bulk(
        participants_with_email, workshop_name
    )

    sent_count = sum(1 for v in results.values() if v)
    failed_count = len(results) - sent_count

    logger.info(
        "Sent credentials for workshop %s: %d sent, %d failed",
        workshop_id,
        sent_count,
        failed_count,
    )

    return EmailSendResponse(
        total=len(results),
        sent=sent_count,
        failed=failed_count,
        results=results,
    )


@router.patch("/{workshop_id}/survey-url", response_model=MessageResponse)
async def update_survey_url(
    workshop_id: str,
    body: SurveyUrlUpdate,
    storage=Depends(get_storage_service),
):
    """워크샵의 만족도 조사 URL을 등록 또는 수정한다."""
    metadata = await _get_workshop_or_raise(storage, workshop_id)
    metadata["survey_url"] = body.survey_url
    await storage.save_workshop_metadata(workshop_id, metadata)

    logger.info("Updated survey URL for workshop %s", workshop_id)

    return MessageResponse(
        message="Survey URL updated successfully",
        detail=body.survey_url,
    )


@router.post("/{workshop_id}/send-survey", response_model=EmailSendResponse)
async def send_survey_email(
    workshop_id: str,
    participant_emails: Optional[list[str]] = Query(
        default=None,
        description="전송 대상 참가자 이메일. 미지정 시 전체 참가자에게 전송.",
    ),
    storage=Depends(get_storage_service),
    email=Depends(get_email_service),
):
    """워크샵 참가자에게 만족도 조사 이메일을 전송한다."""
    metadata = await _get_workshop_or_raise(storage, workshop_id)

    survey_url = metadata.get("survey_url", "")
    if not survey_url:
        raise InvalidInputError(
            f"Workshop '{workshop_id}' does not have a survey URL configured"
        )

    workshop_name = metadata.get("name", "Azure Workshop")
    all_participants = metadata.get("participants", [])

    if participant_emails:
        lower_emails = {e.lower() for e in participant_emails}
        participants_to_send = [
            p for p in all_participants
            if p.get("email", "").lower() in lower_emails
        ]
        if not participants_to_send:
            raise InvalidInputError(
                "No matching participants found for provided emails"
            )
    else:
        participants_to_send = all_participants

    participants_with_email = [p for p in participants_to_send if p.get("email")]
    if not participants_with_email:
        raise InvalidInputError(
            "No participants have email addresses configured"
        )

    results = await email.send_survey_bulk(
        participants_with_email, workshop_name, survey_url
    )

    sent_count = sum(1 for v in results.values() if v)
    failed_count = len(results) - sent_count

    logger.info(
        "Sent survey for workshop %s: %d sent, %d failed",
        workshop_id,
        sent_count,
        failed_count,
    )

    return EmailSendResponse(
        total=len(results),
        sent=sent_count,
        failed=failed_count,
        results=results,
    )
