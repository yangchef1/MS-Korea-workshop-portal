"""Azure Cost Management \uc11c\ube44\uc2a4.

\uc6cc\ud06c\uc0f5 \ub9ac\uc18c\uc2a4 \uadf8\ub8f9 \ubc0f \uad6c\ub3c5 \ub2e8\uc704 \ube44\uc6a9\uc744 \uc870\ud68c\ud55c\ub2e4.

Authentication: DefaultAzureCredential (OIDC/Managed Identity)
"""
import asyncio
import logging
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Optional

from azure.mgmt.costmanagement import CostManagementClient
from azure.mgmt.costmanagement.models import (
    QueryAggregation,
    QueryDataset,
    QueryDefinition,
    QueryTimePeriod,
    TimeframeType,
)

from app.config import settings
from app.services.credential import get_azure_credential

logger = logging.getLogger(__name__)

# Cost API 응답에서 사용하는 상수
_DEFAULT_CURRENCY = "USD"
_COST_GRANULARITY = "Daily"


def _parse_date_range(
    start_date_str: Optional[str],
    end_date_str: Optional[str],
    default_days: int,
) -> tuple[datetime, datetime, int]:
    """비용 조회용 날짜 범위를 파싱한다.

    Args:
        start_date_str: ISO 형식 시작일 (선택).
        end_date_str: ISO 형식 종료일 (선택).
        default_days: 날짜가 미지정 시 기본 조회 일수.

    Returns:
        (start_date, end_date, period_days) 튜플.
    """
    if start_date_str and end_date_str:
        start_date = datetime.fromisoformat(
            start_date_str.replace("Z", "+00:00")
        ).replace(tzinfo=None)
        end_date = datetime.fromisoformat(
            end_date_str.replace("Z", "+00:00")
        ).replace(tzinfo=None)
        now = datetime.now(UTC).replace(tzinfo=None)
        if end_date > now:
            end_date = now
        period_days = (end_date - start_date).days + 1
    else:
        end_date = datetime.now(UTC).replace(tzinfo=None)
        start_date = end_date - timedelta(days=default_days)
        period_days = default_days

    return start_date, end_date, period_days


def _build_cost_query(start_date: datetime, end_date: datetime) -> QueryDefinition:
    """Cost Management API용 쿼리 정의를 생성한다."""
    time_period = QueryTimePeriod(
        from_property=start_date.strftime("%Y-%m-%dT%H:%M:%SZ"),
        to=end_date.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    dataset = QueryDataset(
        granularity=_COST_GRANULARITY,
        aggregation={
            "totalCost": QueryAggregation(name="PreTaxCost", function="Sum")
        },
    )
    return QueryDefinition(
        type="ActualCost",
        timeframe=TimeframeType.CUSTOM,
        time_period=time_period,
        dataset=dataset,
    )


def _sum_cost_rows(result) -> tuple[float, str]:
    """Cost API 결과 행에서 총 비용과 통화를 집계한다."""
    total_cost = 0.0
    currency = _DEFAULT_CURRENCY

    if result.rows:
        for row in result.rows:
            total_cost += float(row[0])
            if len(row) > 2:
                currency = row[2]

    return round(total_cost, 2), currency


class CostService:
    """구독별 Azure 비용 조회 서비스."""

    def __init__(self) -> None:
        """Cost Management 클라이언트를 초기화한다."""
        try:
            self._credential = get_azure_credential()
            self._default_subscription_id = settings.azure_sp_subscription_id
            logger.info("Initialized Cost Management service")
        except Exception as e:
            logger.error("Failed to initialize Cost Management client: %s", e)
            raise

    def _get_cost_client(self) -> CostManagementClient:
        """CostManagementClient를 생성한다 (구독 비종속)."""
        return CostManagementClient(credential=self._credential)

    async def get_resource_group_cost(
        self,
        resource_group_name: str,
        days: int = 30,
        start_date_str: Optional[str] = None,
        end_date_str: Optional[str] = None,
        subscription_id: Optional[str] = None,
    ) -> dict:
        """특정 리소스 그룹의 비용을 조회한다.

        Args:
            resource_group_name: 리소스 그룹 이름.
            days: 기본 조회 일수 (날짜가 지정되면 무시).
            start_date_str: ISO 형식 시작일 (선택).
            end_date_str: ISO 형식 종료일 (선택).
            subscription_id: 대상 구독 ID (미지정 시 기본값 사용).

        Returns:
            총 비용과 통화를 포함한 비용 데이터 딕셔너리.
        """
        sub_id = subscription_id or self._default_subscription_id
        try:
            start_date, end_date, period_days = _parse_date_range(
                start_date_str, end_date_str, days
            )
            scope = f"/subscriptions/{sub_id}/resourceGroups/{resource_group_name}"
            query = _build_cost_query(start_date, end_date)

            result = self._get_cost_client().query.usage(
                scope=scope, parameters=query
            )
            total_cost, currency = _sum_cost_rows(result)

            return {
                "resource_group": resource_group_name,
                "total_cost": total_cost,
                "currency": currency,
                "period_days": period_days,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            }
        except Exception as e:
            logger.error("Failed to query cost for %s: %s", resource_group_name, e)
            return {
                "resource_group": resource_group_name,
                "total_cost": 0.0,
                "currency": _DEFAULT_CURRENCY,
                "period_days": days,
                "error": str(e),
            }

    async def get_workshop_total_cost(
        self,
        participants: list[dict],
        days: int = 30,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> dict:
        """워크샵 전체 참가자의 비용 합계를 조회한다.

        Args:
            participants: 'resource_group'과 선택적 'subscription_id'를 가진 딕셔너리 리스트.
                하위 호환을 위해 문자열 리스트(리소스 그룹 이름)도 허용.
            days: 기본 조회 일수 (날짜가 지정되면 무시).
            start_date: ISO 형식 시작일 (선택).
            end_date: ISO 형식 종료일 (선택).

        Returns:
            총 비용과 리소스 그룹별 내역을 포함한 딕셔너리.
        """
        # 하위 호환: 문자열 리스트를 딕셔너리 리스트로 변환
        if participants and isinstance(participants[0], str):
            participants = [{"resource_group": rg} for rg in participants]

        tasks = [
            self.get_resource_group_cost(
                p.get("resource_group"),
                days,
                start_date,
                end_date,
                subscription_id=p.get("subscription_id"),
            )
            for p in participants
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        total_cost = 0.0
        currency = _DEFAULT_CURRENCY
        breakdown = []

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "Failed to get cost for %s: %s",
                    participants[i].get("resource_group"),
                    result,
                )
                breakdown.append({
                    "resource_group": participants[i].get("resource_group"),
                    "subscription_id": participants[i].get("subscription_id"),
                    "cost": 0.0,
                    "error": str(result),
                })
            else:
                total_cost += result["total_cost"]
                currency = result.get("currency", _DEFAULT_CURRENCY)
                breakdown.append({
                    "resource_group": result["resource_group"],
                    "subscription_id": participants[i].get("subscription_id"),
                    "cost": result["total_cost"],
                })

        return {
            "total_cost": round(total_cost, 2),
            "currency": currency,
            "period_days": days,
            "resource_groups_count": len(participants),
            "breakdown": breakdown,
        }

    async def get_subscription_cost(
        self,
        days: int = 30,
        subscription_id: Optional[str] = None,
    ) -> dict:
        """구독 전체 비용을 조회한다.

        Args:
            days: 조회 일수.
            subscription_id: 대상 구독 ID (미지정 시 기본값 사용).

        Returns:
            비용 데이터 딕셔너리.
        """
        sub_id = subscription_id or self._default_subscription_id
        try:
            end_date = datetime.now(UTC).replace(tzinfo=None)
            start_date = end_date - timedelta(days=days)
            scope = f"/subscriptions/{sub_id}"

            query = _build_cost_query(start_date, end_date)
            result = self._get_cost_client().query.usage(
                scope=scope, parameters=query
            )
            total_cost, currency = _sum_cost_rows(result)

            return {
                "subscription_id": sub_id,
                "total_cost": total_cost,
                "currency": currency,
                "period_days": days,
            }
        except Exception as e:
            logger.error("Failed to query subscription cost: %s", e)
            return {
                "subscription_id": sub_id,
                "total_cost": 0.0,
                "currency": _DEFAULT_CURRENCY,
                "period_days": days,
                "error": str(e),
            }


@lru_cache(maxsize=1)
def get_cost_service() -> CostService:
    """CostService 싱글턴 인스턴스를 반환한다."""
    return CostService()


cost_service = get_cost_service()
