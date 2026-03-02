"""Endpoints for viewing subscription status."""
from fastapi import APIRouter, Depends, Query

from app.core.deps import get_current_user, get_subscription_service

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
