"""Admin endpoints for managing subscription allow/deny lists."""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.core.deps import get_subscription_service, require_admin

router = APIRouter(prefix="/admin/subscriptions", tags=["Admin"])


class SubscriptionSettingsUpdate(BaseModel):
    """허용/제외 구독 설정 업데이트 요청."""

    allow_list: list[str] = []
    deny_list: list[str] = []


@router.get("")
async def get_subscriptions(
    refresh: bool = Query(
        False, description="캐시를 무시하고 Azure에서 즉시 새로고침 여부"
    ),
    subscription_service=Depends(get_subscription_service),
    _: dict = Depends(require_admin),
):
    """사용 가능한 구독 목록과 현재 설정을 조회한다."""
    result = await subscription_service.get_available_subscriptions(
        force_refresh=refresh
    )
    return result


@router.put("")
async def update_subscriptions(
    payload: SubscriptionSettingsUpdate,
    subscription_service=Depends(get_subscription_service),
    _: dict = Depends(require_admin),
):
    """허용/제외 구독 설정을 갱신한다."""
    return await subscription_service.update_subscription_settings(
        payload.allow_list or [], payload.deny_list or []
    )
