"""Subscription discovery, filtering, and assignment service."""
import asyncio
import logging
import time
from functools import lru_cache
from typing import Any

from azure.mgmt.resource import SubscriptionClient

from app.config import settings
from app.exceptions import ServiceUnavailableError
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
        self, force_refresh: bool = False
    ) -> dict[str, Any]:
        subscriptions, from_cache = await self._get_azure_subscriptions(force_refresh)
        if not subscriptions:
            raise ServiceUnavailableError("No Azure subscriptions available for the portal")

        settings_data = await self._get_settings()
        allow_list = _normalize_ids(settings_data.get("allow_list", []))
        deny_list = _normalize_ids(settings_data.get("deny_list", []))

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
        self, participants: list[dict[str, str]]
    ) -> dict[str, Any]:
        available_result = await self.get_available_subscriptions()
        available = available_result["subscriptions"]
        if not available:
            raise ServiceUnavailableError("No available subscriptions to assign")

        available_ids = [s["subscription_id"] for s in available]
        replaced: list[str] = []
        assigned: list[dict[str, str]] = []
        index = 0

        for participant in participants:
            current_sub = (participant.get("subscription_id") or "").lower()
            if current_sub and current_sub in [sid.lower() for sid in available_ids]:
                assigned_sub = next(
                    sid for sid in available_ids if sid.lower() == current_sub
                )
            else:
                assigned_sub = available_ids[index % len(available_ids)]
                index += 1
                if current_sub:
                    replaced.append(participant.get("alias", ""))

            assigned.append({**participant, "subscription_id": assigned_sub})

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
