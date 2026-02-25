"""Subscription discovery, filtering, and assignment service."""
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


def _normalize_ids(values: list[str]) -> list[str]:
    """Deduplicate and normalize subscription IDs to lowercase."""
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values:
        if not value:
            continue
        lower = value.strip().lower()
        if lower and lower not in seen:
            seen.add(lower)
            normalized.append(lower)
    return normalized


class SubscriptionService:
    """Azure 구독을 조회하고 허용/제외 설정을 적용하여 참가자에 배정한다."""

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

    async def _get_settings(self) -> dict[str, list[str]]:
        return await storage_service.get_portal_subscription_settings()

    async def _save_settings(self, allow_list: list[str], deny_list: list[str]) -> dict[str, list[str]]:
        return await storage_service.save_portal_subscription_settings(allow_list, deny_list)

    async def get_available_subscriptions(
        self, force_refresh: bool = False,
    ) -> dict[str, Any]:
        """사용 가능한 구독 목록을 조회한다.

        allow/deny 필터와 in_use_map을 적용하여 현재 할당 가능한
        구독만 반환한다.

        Args:
            force_refresh: 캐시를 무시하고 Azure에서 새로 조회할지 여부.

        Returns:
            subscriptions, allow_list, deny_list, in_use_map 등을 포함하는 딕셔너리.
        """
        subscriptions, from_cache = await self._get_azure_subscriptions(force_refresh)
        if not subscriptions:
            raise ServiceUnavailableError("No Azure subscriptions available for the portal")

        settings_data = await self._get_settings()
        allow_list = _normalize_ids(settings_data.get("allow_list", []))
        deny_list = _normalize_ids(settings_data.get("deny_list", []))
        in_use_map: dict[str, str] = settings_data.get("in_use_map", {})

        deployment_sub = settings.deployment_subscription_id.lower()
        if deployment_sub and deployment_sub not in deny_list:
            deny_list.append(deployment_sub)

        available, pruned_ids, allow_list, deny_list = await self._apply_filters(
            subscriptions, allow_list, deny_list
        )

        return {
            "subscriptions": available,
            "allow_list": allow_list,
            "deny_list": deny_list,
            "in_use_map": in_use_map,
            "pruned_ids": pruned_ids,
            "from_cache": from_cache and not force_refresh,
        }

    async def _apply_filters(
        self,
        subscriptions: list[dict[str, str]],
        allow_list: list[str],
        deny_list: list[str],
    ) -> tuple[list[dict[str, str]], list[str], list[str], list[str]]:
        azure_ids = {s["subscription_id"].lower(): s for s in subscriptions}

        pruned_ids = [sid for sid in allow_list + deny_list if sid not in azure_ids]
        if pruned_ids:
            allow_list = [sid for sid in allow_list if sid in azure_ids]
            deny_list = [sid for sid in deny_list if sid in azure_ids]
            await self._save_settings(allow_list, deny_list)
            logger.info("Pruned %d stale subscription ids from settings", len(pruned_ids))

        available: list[dict[str, str]] = []
        allow_filter = set(allow_list)
        deny_filter = set(deny_list)

        for sub_id, sub in azure_ids.items():
            if sub_id in deny_filter:
                continue
            if allow_filter and sub_id not in allow_filter:
                continue
            available.append(sub)

        return available, pruned_ids, allow_list, deny_list

    async def assign_subscriptions(
        self, participants: list[dict[str, str]], workshop_id: str,
    ) -> dict[str, Any]:
        """참가자에게 1:1로 전용 구독을 배타적으로 할당한다.

        각 참가자는 고유한 구독 1개를 받는다. 이미 유효한 subscription_id를
        가진 참가자는 기존 할당을 유지한다.
        사용 가능한 구독이 부족하면 InsufficientSubscriptionsError를 발생시킨다.

        Args:
            participants: alias, email, (선택적) subscription_id를 포함하는 참가자 목록.
            workshop_id: 할당 대상 워크샵 ID.

        Returns:
            할당 결과 딕셔너리.

        Raises:
            InsufficientSubscriptionsError: 사용 가능 구독 수 < 참가자 수.
            ServiceUnavailableError: 구독이 전혀 없는 경우.
        """
        available_result = await self.get_available_subscriptions()
        available = available_result["subscriptions"]
        in_use_map: dict[str, str] = available_result.get("in_use_map", {})

        if not available:
            raise ServiceUnavailableError("No available subscriptions to assign")

        # in_use_map에서 사용 중인 구독 제외 (현재 워크샵이 사용 중인 건 허용)
        all_available_ids = [s["subscription_id"] for s in available]
        free_ids = [
            sid for sid in all_available_ids
            if sid not in in_use_map or in_use_map[sid] == workshop_id
        ]

        replaced: list[str] = []
        assigned: list[dict[str, str]] = []
        used_ids: set[str] = set()
        needs_assignment: list[tuple[int, dict[str, str]]] = []

        # Phase 1: 기존 유효 할당 보존
        for i, participant in enumerate(participants):
            current_sub = (participant.get("subscription_id") or "").lower()
            if current_sub and current_sub in [sid.lower() for sid in free_ids]:
                assigned_sub = next(
                    sid for sid in free_ids if sid.lower() == current_sub
                )
                assigned.append({**participant, "subscription_id": assigned_sub})
                used_ids.add(assigned_sub.lower())
            else:
                assigned.append(participant)  # placeholder
                needs_assignment.append((i, participant))
                if current_sub:
                    replaced.append(participant.get("alias", ""))

        # Phase 2: 신규 할당용 풀 구성
        pool = [sid for sid in free_ids if sid.lower() not in used_ids]

        if len(needs_assignment) > len(pool):
            raise InsufficientSubscriptionsError(
                f"{len(participants)} participants require {len(needs_assignment)} "
                f"subscriptions, but only {len(pool)} available",
                required=len(needs_assignment),
                available=len(pool),
            )

        # Phase 3: 1:1 배타적 할당
        for idx, (i, participant) in enumerate(needs_assignment):
            assigned_sub = pool[idx]
            assigned[i] = {**participant, "subscription_id": assigned_sub}
            used_ids.add(assigned_sub.lower())

        return {
            "participants": assigned,
            "replaced_aliases": replaced,
            "available_subscriptions": available,
            "pruned_ids": available_result["pruned_ids"],
            "from_cache": available_result["from_cache"],
        }

    async def update_subscription_settings(
        self, allow_list: list[str], deny_list: list[str]
    ) -> dict[str, Any]:
        allow = _normalize_ids(allow_list)
        deny = _normalize_ids(deny_list)

        deployment_sub = settings.deployment_subscription_id.lower()
        allow = [sid for sid in allow if sid != deployment_sub]
        deny = [sid for sid in deny if sid != deployment_sub]

        subscriptions, _ = await self._get_azure_subscriptions(force_refresh=True)
        if not subscriptions:
            raise ServiceUnavailableError("No Azure subscriptions available for the portal")

        azure_ids = {s["subscription_id"].lower() for s in subscriptions}
        pruned_allow = [sid for sid in allow if sid in azure_ids]
        pruned_deny = [sid for sid in deny if sid in azure_ids]
        pruned_ids = [sid for sid in allow + deny if sid not in azure_ids]

        await self._save_settings(pruned_allow, pruned_deny)

        available, _, final_allow, final_deny = await self._apply_filters(
            subscriptions, pruned_allow, pruned_deny
        )

        return {
            "allow_list": final_allow,
            "deny_list": final_deny,
            "pruned_ids": pruned_ids,
            "subscriptions": available,
            "from_cache": False,
        }


@lru_cache(maxsize=1)
def get_subscription_service() -> SubscriptionService:
    return SubscriptionService()


subscription_service = get_subscription_service()
