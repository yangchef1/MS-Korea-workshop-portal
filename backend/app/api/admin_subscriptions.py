"""Admin endpoints for viewing subscription status."""
from fastapi import APIRouter, Depends, Query

from app.core.deps import get_subscription_service, require_admin

router = APIRouter(prefix="/admin/subscriptions", tags=["Admin"])


@router.get("")
async def get_subscriptions(
    refresh: bool = Query(
        False, description="캐시를 무시하고 Azure에서 즉시 새로고침 여부"
    ),
    subscription_service=Depends(get_subscription_service),
    _: dict = Depends(require_admin),
):
    """사용 가능한 구독 목록과 현재 사용 현황(in_use_map)을 조회한다."""
    result = await subscription_service.get_available_subscriptions(
        force_refresh=refresh
    )
    return result
