"""Subscription discovery and assignment service."""
import asyncio
import logging
import time
from functools import lru_cache
from typing import Any

from azure.mgmt.resource import SubscriptionClient

from app.config import settings
from app.exceptions import InsufficientSubscriptionsError, ServiceUnavailableError
from app.services.credential import get_azure_credential
from app.services.storage import storage_service

logger = logging.getLogger(__name__)


class SubscriptionService:
    """Azure 구독을 조회하고 참가자에게 배정한다."""

    def __init__(self) -> None:
        self._credential = get_azure_credential()
        self._azure_cache: list[dict[str, str]] = []
        self._cache_time: float = 0.0

    def _cache_valid(self) -> bool:
        if not self._azure_cache:
            return False
        return (time.time() - self._cache_time) < settings.subscription_cache_ttl_seconds

    async def _fetch_azure_subscriptions(self) -> list[dict[str, str]]:
        def _list_subscriptions() -> list[dict[str, str]]:
            client = SubscriptionClient(credential=self._credential)
            try:
                subscriptions: list[dict[str, str]] = []
                for sub in client.subscriptions.list():
                    subscriptions.append(
                        {
                            "subscription_id": sub.subscription_id,
                            "display_name": getattr(sub, "display_name", ""),
                        }
                    )
                return subscriptions
            finally:
                try:
                    client.close()
                except Exception:
                    pass

        return await asyncio.to_thread(_list_subscriptions)

    async def _get_azure_subscriptions(self, force_refresh: bool = False) -> tuple[list[dict[str, str]], bool]:
        if self._cache_valid() and not force_refresh:
            return self._azure_cache, True

        subscriptions = await self._fetch_azure_subscriptions()
        self._azure_cache = subscriptions
        self._cache_time = time.time()
        return subscriptions, False

    async def _get_in_use_map(self) -> dict[str, str]:
        """현재 사용 중인 구독 매핑을 조회한다."""
        return await storage_service.get_in_use_map()

    def _exclude_deployment_subscription(
        self, subscriptions: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """포털 배포 구독을 목록에서 제외한다."""
        deployment_sub = settings.deployment_subscription_id.lower()
        if not deployment_sub:
            return subscriptions
        return [
            s for s in subscriptions
            if s["subscription_id"].lower() != deployment_sub
        ]

    async def get_available_subscriptions(
        self, force_refresh: bool = False,
    ) -> dict[str, Any]:
        """사용 가능한 구독 목록을 조회한다.

        포털 배포 구독을 제외하고, in_use_map을 포함하여 현재 사용 현황을
        반환한다.

        Args:
            force_refresh: 캐시를 무시하고 Azure에서 새로 조회할지 여부.

        Returns:
            subscriptions, in_use_map 등을 포함하는 딕셔너리.
        """
        subscriptions, from_cache = await self._get_azure_subscriptions(force_refresh)
        if not subscriptions:
            raise ServiceUnavailableError("No Azure subscriptions available for the portal")

        available = self._exclude_deployment_subscription(subscriptions)
        available.sort(key=lambda s: s.get("display_name", "").lower())
        in_use_map = await self._get_in_use_map()

        return {
            "subscriptions": available,
            "in_use_map": in_use_map,
            "from_cache": from_cache and not force_refresh,
        }

    async def assign_subscriptions(
        self, participants: list[dict[str, str]], workshop_id: str,
    ) -> dict[str, Any]:
        """참가자에게 1:1로 전용 구독을 배타적으로 할당한다.

        각 참가자는 고유한 구독 1개를 받는다. 사용 가능한 구독 풀에서
        순차적으로 배정한다.
        사용 가능한 구독이 부족하면 InsufficientSubscriptionsError를 발생시킨다.

        Args:
            participants: alias, email을 포함하는 참가자 목록.
            workshop_id: 할당 대상 워크샵 ID.

        Returns:
            할당 결과 딕셔너리.

        Raises:
            InsufficientSubscriptionsError: 사용 가능 구독 수 < 참가자 수.
            ServiceUnavailableError: 구독이 전혀 없는 경우.
        """
        available_result = await self.get_available_subscriptions()
        available = available_result["subscriptions"]
        in_use_map = available_result.get("in_use_map", {})

        if not available:
            raise ServiceUnavailableError("No available subscriptions to assign")

        # in_use_map에서 사용 중인 구독 제외 (현재 워크샵이 사용 중인 건 허용)
        all_available_ids = [s["subscription_id"] for s in available]
        pool = [
            sid for sid in all_available_ids
            if sid not in in_use_map or in_use_map[sid] == workshop_id
        ]

        if len(participants) > len(pool):
            raise InsufficientSubscriptionsError(
                f"{len(participants)} participants require subscriptions, "
                f"but only {len(pool)} available",
                required=len(participants),
                available=len(pool),
            )

        # 1:1 순차 배정
        assigned: list[dict[str, str]] = []
        for idx, participant in enumerate(participants):
            assigned.append({**participant, "subscription_id": pool[idx]})

        return {
            "participants": assigned,
            "available_subscriptions": available,
            "from_cache": available_result["from_cache"],
        }


@lru_cache(maxsize=1)
def get_subscription_service() -> SubscriptionService:
    return SubscriptionService()


subscription_service = get_subscription_service()
