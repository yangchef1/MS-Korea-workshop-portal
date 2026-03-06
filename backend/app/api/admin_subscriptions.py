"""Endpoints for viewing subscription status."""
from fastapi import APIRouter, Depends, Query

from app.core.deps import get_current_user, get_storage_service, get_subscription_service, require_admin
from app.models import MessageResponse

router = APIRouter(prefix="/subscriptions", tags=["Subscriptions"])


@router.get("")
async def get_subscriptions(
    refresh: bool = Query(
        False, description="캐시를 무시하고 Azure에서 즉시 새로고침 여부"
    ),
    subscription_service=Depends(get_subscription_service),
    _=Depends(get_current_user),
):
    """사용 가능한 구독 목록과 현재 사용 현황(in_use_map)을 조회한다."""
    result = await subscription_service.get_available_subscriptions(
        force_refresh=refresh
    )
    return result


@router.post(
    "/force-release/{workshop_id}",
    response_model=MessageResponse,
)
async def force_release_subscriptions(
    workshop_id: str,
    storage=Depends(get_storage_service),
    _: dict = Depends(require_admin),
):
    """특정 워크샵에 묶인 모든 구독을 강제 해제한다 (관리자 전용).

    워크샵 생성 실패 후 롤백이 불완전하게 끝나 in_use_map에 고아 alloc이
    남은 경우 수동 복구에 사용한다. 워크샵 메타데이터가 존재하지 않아도 동작한다.

    Args:
        workshop_id: 강제 해제할 워크샵 ID.
    """
    released = await storage.release_subscriptions_by_workshop(workshop_id)

    if not released:
        return MessageResponse(
            message="No subscriptions to release",
            detail=f"No in_use_map entries found for workshop '{workshop_id}'.",
        )

    return MessageResponse(
        message=f"Released {len(released)} subscription(s)",
        detail=f"Freed subscriptions: {', '.join(released)}",
    )
