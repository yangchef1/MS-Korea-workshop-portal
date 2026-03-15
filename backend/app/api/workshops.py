"""워크샵 API 라우터.

워크샵 생명주기(생성, 조회, 삭제)와 관련 리소스(비용, 비밀번호, 이메일)를
관리하는 엔드포인트를 제공한다.
"""
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from app.config import settings
from app.core.deps import (
    get_cost_service,
    get_current_user,
    get_entra_id_service,
    get_resource_manager_service,
    get_subscription_service,
    get_storage_service,
    get_workshop_service,
    require_admin,
)
from app.exceptions import InvalidInputError, NotFoundError
from app.models import (
    CostResponse,
    DeletionFailureItem,
    DeletionFailureListResponse,
    EndDateExtension,
    MessageResponse,
    SurveyUrlUpdate,
    WorkshopDetail,
    WorkshopResponse,
)
from app.utils.csv_parser import generate_passwords_csv

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workshops", tags=["Workshops"])


class ResourceType(BaseModel):
    """Azure 리소스 유형."""

    value: str
    label: str
    category: str


class ParticipantSubscriptionUpdate(BaseModel):
    """참가자 구독 재배정 요청."""

    subscription_id: str


class VmSkuResponse(BaseModel):
    """VM SKU 정보 응답."""

    name: str
    family: str
    vcpus: int
    memory_gb: float


@router.get("/vm-skus/common", response_model=list[VmSkuResponse])
async def get_common_vm_skus(
    regions: str,
    resource_manager=Depends(get_resource_manager_service),
):
    """지정된 모든 리전에서 공통으로 지원되는 VM SKU 교집합을 반환한다 (24시간 캐시).

    Azure Compute SKUs API를 단일 호출로 조회하여 서버에서 교집합을 계산한다.

    Args:
        regions: 쉼표로 구분된 리전 목록 (예: 'koreacentral,eastus,westus2').
    """
    region_list = [r.strip() for r in regions.split(",") if r.strip()]
    skus = await resource_manager.list_common_vm_skus(region_list)
    return [
        VmSkuResponse(
            name=sku["name"],
            family=sku["family"],
            vcpus=sku["vcpus"],
            memory_gb=sku["memory_gb"],
        )
        for sku in skus
    ]


@router.get("/vm-sku-presets")
async def get_vm_sku_presets():
    """VM SKU 프리셋 목록을 반환한다."""
    return settings.VM_SKU_PRESETS


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
    workshop_service=Depends(get_workshop_service),
):
    """전체 워크샵 목록을 조회한다 (비용 제외, 빠른 응답)."""
    return await workshop_service.list_workshops()


@router.get("/costs")
async def get_workshops_costs(
    _admin=Depends(require_admin),
    workshop_service=Depends(get_workshop_service),
):
    """모든 워크샵의 비용을 일괄 조회한다 (lazy-load용).

    워크샵 ID를 키, {estimated_cost, currency}를 값으로 하는 맵을 반환한다.
    """
    return await workshop_service.get_workshops_costs()


@router.get("/{workshop_id}", response_model=WorkshopDetail)
async def get_workshop(
    workshop_id: str,
    workshop_service=Depends(get_workshop_service),
):
    """워크샵 상세 정보를 조회한다."""
    return await workshop_service.get_workshop_detail(workshop_id)


@router.patch(
    "/{workshop_id}/participants/{alias}/subscription",
    response_model=MessageResponse,
)
async def update_participant_subscription(
    workshop_id: str,
    alias: str,
    payload: ParticipantSubscriptionUpdate,
    storage=Depends(get_storage_service),
    subscription_service=Depends(get_subscription_service),
    _: dict = Depends(require_admin),
):
    """참가자의 구독을 수동 재배정한다 (관리자 전용)."""
    metadata = await _get_workshop_or_raise(storage, workshop_id)

    subscription_data = await subscription_service.get_available_subscriptions(
        force_refresh=True
    )
    available_subs = subscription_data.get("subscriptions", [])
    target_sub = payload.subscription_id.lower()
    available_map = {
        sub.get("subscription_id", "").lower(): sub.get("subscription_id", "")
        for sub in available_subs
    }

    if target_sub not in available_map:
        raise InvalidInputError(
            f"Subscription '{payload.subscription_id}' is not available for assignment"
        )

    participants = metadata.get("participants", [])
    updated = False
    for participant in participants:
        if participant.get("alias") == alias:
            participant["subscription_id"] = available_map[target_sub]
            updated = True
            break

    if not updated:
        raise NotFoundError(
            f"Participant '{alias}' not found in workshop '{workshop_id}'",
            resource_type="Participant",
        )

    metadata["participants"] = participants
    await storage.save_workshop_metadata(workshop_id, metadata)

    return MessageResponse(
        message="Subscription reassigned",
        detail=f"Participant '{alias}' now uses subscription '{available_map[target_sub]}'",
    )


@router.post("", response_model=WorkshopDetail)
async def create_workshop(
    name: str = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...),
    base_resources_template: str = Form(...),
    allowed_regions: str = Form(...),
    denied_services: str = Form(default=""),
    allowed_vm_skus: str = Form(default=""),
    vm_sku_preset: str = Form(default=""),
    deployment_region: str = Form(default=""),
    participants_file: UploadFile = File(...),
    description: str = Form(default=""),
    survey_url: Optional[str] = Form(default=None, description="M365 Forms 만족도 조사 URL"),
    user=Depends(get_current_user),
    workshop_service=Depends(get_workshop_service),
):
    """새 워크샵을 생성한다.

    CSV 형식: 이메일만 포함하는 단일 컬럼.
    구독은 사용 가능한 풀에서 순차적으로 자동 배정한다.
    Azure 리소스 생성 후 DB 저장이 실패하면 보상 트랜잭션(rollback)을 수행한다.
    """
    return await workshop_service.create_workshop(
        name=name,
        start_date=start_date,
        end_date=end_date,
        base_resources_template=base_resources_template,
        allowed_regions=allowed_regions,
        denied_services=denied_services,
        allowed_vm_skus=allowed_vm_skus,
        vm_sku_preset=vm_sku_preset,
        deployment_region=deployment_region,
        participants_file=participants_file,
        description=description,
        survey_url=survey_url,
        user=user,
    )


@router.delete("/{workshop_id}", response_model=MessageResponse, status_code=202)
async def delete_workshop(
    workshop_id: str,
    background_tasks: BackgroundTasks,
    workshop_service=Depends(get_workshop_service),
):
    """워크샵 정리를 시작한다 (비동기, 202 Accepted).

    스냅샷을 캡처하고 cleaning_up 상태로 전환한 뒤 즉시 반환한다.
    실제 리소스 삭제는 백그라운드에서 수행된다.
    scheduled 워크샵은 즉시 삭제된다.
    """
    result = await workshop_service.delete_workshop(workshop_id)
    # If the workshop was transitioned to cleaning_up, run actual cleanup in background
    if result.message == "Workshop cleanup started":
        background_tasks.add_task(workshop_service.execute_cleanup, workshop_id)
    return result


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
    """워크샵의 모든 삭제 실패가 해결되었으면 상태를 completed로 전환한다.

    Args:
        workshop_id: 워크샵 ID.
        storage: StorageService 인스턴스.

    Returns:
        워크샵이 completed로 전환되었으면 True.
    """
    remaining = await storage.list_deletion_failures_by_workshop(workshop_id)
    if remaining:
        return False

    metadata = await storage.get_workshop_metadata(workshop_id)
    if metadata:
        sensitive_fields = ("password", "object_id")
        for participant in metadata.get("participants", []):
            for field in sensitive_fields:
                participant.pop(field, None)
        metadata["status"] = "completed"
        await storage.save_workshop_metadata(workshop_id, metadata)
    logger.info(
        "All failures resolved — workshop %s status set to completed",
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
            detail += ". All failures resolved — workshop marked as completed."
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
        detail += ". All failures resolved — workshop marked as completed."

    return MessageResponse(
        message="Retry all completed",
        detail=detail,
    )


@router.get("/{workshop_id}/passwords", response_class=Response)
async def download_passwords(
    workshop_id: str,
    storage=Depends(get_storage_service),
):
    """참가자 계정 정보 CSV 파일을 다운로드한다.

    메타데이터의 participants에서 실시간으로 CSV를 생성한다.
    개인 이메일은 포함하지 않는다 (컴플라이언스).
    """
    metadata = await _get_workshop_or_raise(storage, workshop_id)
    participants = metadata.get("participants", [])
    if not participants:
        raise NotFoundError(
            f"No participants found for workshop '{workshop_id}'",
            resource_type="Participants",
        )

    csv_content = generate_passwords_csv(participants)

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
    """워크샵 리소스를 조회한다.

    completed 상태에서는 아카이브된 스냅샷 데이터를 반환한다.
    cleaning_up/active 상태에서는 Azure API를 실시간 조회한다.
    """
    metadata = await _get_workshop_or_raise(storage, workshop_id)

    # Return archived snapshot for completed workshops
    if metadata.get("status") == "completed" and metadata.get("resource_snapshot"):
        snapshot = metadata["resource_snapshot"]
        return {
            "workshop_id": workshop_id,
            "total_count": snapshot.get("total_count", 0),
            "resources": snapshot.get("resources", []),
            "is_snapshot": True,
        }

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
    _admin=Depends(require_admin),
    storage=Depends(get_storage_service),
    cost=Depends(get_cost_service),
    workshop_service=Depends(get_workshop_service),
):
    """워크샵 비용을 조회한다.

    completed 상태에서는 아카이브된 스냅샷 데이터를 반환한다.
    cleaning_up/active 상태에서는 Azure Cost Management API를 실시간 조회한다.
    """
    metadata = await _get_workshop_or_raise(storage, workshop_id)

    # Return archived snapshot for completed workshops
    if metadata.get("status") == "completed" and metadata.get("cost_snapshot"):
        snapshot = metadata["cost_snapshot"]
        return CostResponse(
            total_cost=snapshot.get("total_cost", 0.0),
            currency=snapshot.get("currency", "USD"),
            period_days=snapshot.get("period_days", 0),
            start_date=snapshot.get("start_date"),
            end_date=snapshot.get("end_date"),
            breakdown=snapshot.get("breakdown"),
        )

    cost_specs = workshop_service.build_cost_specs(metadata.get("participants", []))

    if use_workshop_period:
        start_date = metadata.get("start_date")
        end_date = metadata.get("end_date")
        cost_data = await cost.get_workshop_total_cost(
            cost_specs, start_date=start_date, end_date=end_date
        )
    else:
        cost_data = await cost.get_workshop_total_cost(cost_specs, days=30)

    return CostResponse(**cost_data)


# send-credentials endpoint removed: personal emails are no longer stored
# (compliance). Credential emails are sent in-memory during workshop creation only.


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


@router.patch("/{workshop_id}/end-date", response_model=MessageResponse)
async def extend_end_date(
    workshop_id: str,
    body: EndDateExtension,
    workshop_service=Depends(get_workshop_service),
    _: dict = Depends(require_admin),
):
    """워크샵의 종료 시간을 연장한다 (관리자 전용).

    기존 end_date보다 뒤로만 연장할 수 있다.
    active 상태일 때는 참가자 리소스 그룹의 end_date 태그도 동기화한다.
    """
    return await workshop_service.extend_end_date(workshop_id, body.new_end_date)


# send-survey endpoint removed: personal emails are no longer stored
# (compliance). Survey links should be shared through other channels.
