"""Azure Cost Management service.

Authentication: Uses DefaultAzureCredential (OIDC/Managed Identity)
- Local development: Azure CLI credential (az login)
- Production: Managed Identity assigned to App Service
"""
import logging
from functools import lru_cache
from typing import Dict, Optional, List
from datetime import datetime, timedelta
from azure.mgmt.costmanagement import CostManagementClient
from azure.mgmt.costmanagement.models import (
    QueryDefinition,
    QueryTimePeriod,
    QueryDataset,
    QueryAggregation,
    TimeframeType,
)

from app.config import settings
from app.services.credential import get_azure_credential

logger = logging.getLogger(__name__)

class CostService:
    """Service for querying Azure cost data with per-subscription support."""

    def __init__(self):
        """Initialize Cost Management client using Azure Identity."""
        try:
            self._credential = get_azure_credential()
            self._default_subscription_id = settings.azure_subscription_id
            logger.info("Initialized Cost Management service")
        except Exception as e:
            logger.error("Failed to initialize Cost Management client: %s", e)
            raise

    def _get_cost_client(self) -> CostManagementClient:
        """Get CostManagementClient (subscription-agnostic)"""
        return CostManagementClient(credential=self._credential)

    # Backward compatibility property
    @property
    def cost_client(self) -> CostManagementClient:
        return self._get_cost_client()

    async def get_resource_group_cost(
        self,
        resource_group_name: str,
        days: int = 30,
        start_date_str: str = None,
        end_date_str: str = None,
        subscription_id: str = None
    ) -> Optional[Dict]:
        """
        Get cost for a resource group in a specific subscription

        Args:
            resource_group_name: Resource group name
            days: Number of days to query (default 30, ignored if dates provided)
            start_date_str: Start date in ISO format (optional)
            end_date_str: End date in ISO format (optional)
            subscription_id: Target subscription ID (uses default if not provided)

        Returns:
            Cost data dictionary with total and currency
        """
        sub_id = subscription_id or self._default_subscription_id
        try:
            if start_date_str and end_date_str:
                start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00')).replace(tzinfo=None)
                end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00')).replace(tzinfo=None)
                if end_date > datetime.utcnow():
                    end_date = datetime.utcnow()
                days = (end_date - start_date).days + 1
            else:
                end_date = datetime.utcnow()
                start_date = end_date - timedelta(days=days)

            scope = f"/subscriptions/{sub_id}/resourceGroups/{resource_group_name}"

            time_period = QueryTimePeriod(
                from_property=start_date.strftime("%Y-%m-%dT%H:%M:%SZ"),
                to=end_date.strftime("%Y-%m-%dT%H:%M:%SZ")
            )

            dataset = QueryDataset(
                granularity="Daily",
                aggregation={
                    "totalCost": QueryAggregation(name="PreTaxCost", function="Sum")
                }
            )

            query = QueryDefinition(
                type="ActualCost",
                timeframe=TimeframeType.CUSTOM,
                time_period=time_period,
                dataset=dataset
            )

            result = self.cost_client.query.usage(scope=scope, parameters=query)

            total_cost = 0.0
            currency = "USD"

            if result.rows:
                for row in result.rows:
                    total_cost += float(row[0])
                    if len(row) > 2:
                        currency = row[2]

            return {
                'resource_group': resource_group_name,
                'total_cost': round(total_cost, 2),
                'currency': currency,
                'period_days': days,
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat()
            }

        except Exception as e:
            logger.error("Failed to query cost for %s: %s", resource_group_name, e)
            return {
                'resource_group': resource_group_name,
                'total_cost': 0.0,
                'currency': 'USD',
                'period_days': days,
                'error': str(e)
            }

    async def get_workshop_total_cost(
        self,
        participants: List[Dict],
        days: int = 30,
        start_date: str = None,
        end_date: str = None
    ) -> Dict:
        """
        Get total cost for all workshop participants (supports per-subscription)

        Args:
            participants: List of participant dicts with 'resource_group' and optionally 'subscription_id'
                         For backward compatibility, also accepts List[str] of resource group names
            days: Number of days to query (ignored if dates provided)
            start_date: Start date in ISO format (optional)
            end_date: End date in ISO format (optional)

        Returns:
            Dictionary with total cost and per-RG breakdown
        """
        import asyncio

        # Backward compatibility: convert list of strings to list of dicts
        if participants and isinstance(participants[0], str):
            participants = [{'resource_group': rg} for rg in participants]

        tasks = [
            self.get_resource_group_cost(
                p.get('resource_group'),
                days,
                start_date,
                end_date,
                subscription_id=p.get('subscription_id')
            )
            for p in participants
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        total_cost = 0.0
        currency = "USD"
        breakdown = []

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "Failed to get cost for %s: %s",
                    participants[i].get('resource_group'), result
                )
                breakdown.append({
                    'resource_group': participants[i].get('resource_group'),
                    'subscription_id': participants[i].get('subscription_id'),
                    'cost': 0.0,
                    'error': str(result)
                })
            else:
                total_cost += result['total_cost']
                currency = result.get('currency', 'USD')
                breakdown.append({
                    'resource_group': result['resource_group'],
                    'subscription_id': participants[i].get('subscription_id'),
                    'cost': result['total_cost']
                })

        return {
            'total_cost': round(total_cost, 2),
            'currency': currency,
            'period_days': days,
            'resource_groups_count': len(participants),
            'breakdown': breakdown
        }

    async def get_subscription_cost(
        self,
        days: int = 30,
        subscription_id: str = None
    ) -> Dict:
        """
        Get total subscription cost

        Args:
            days: Number of days to query
            subscription_id: Target subscription ID (uses default if not provided)

        Returns:
            Cost data dictionary
        """
        sub_id = subscription_id or self._default_subscription_id
        try:
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=days)

            scope = f"/subscriptions/{sub_id}"

            time_period = QueryTimePeriod(
                from_property=start_date.strftime("%Y-%m-%dT%H:%M:%SZ"),
                to=end_date.strftime("%Y-%m-%dT%H:%M:%SZ")
            )

            dataset = QueryDataset(
                granularity="Daily",
                aggregation={
                    "totalCost": QueryAggregation(name="PreTaxCost", function="Sum")
                }
            )

            query = QueryDefinition(
                type="ActualCost",
                timeframe=TimeframeType.CUSTOM,
                time_period=time_period,
                dataset=dataset
            )

            result = self.cost_client.query.usage(scope=scope, parameters=query)

            total_cost = 0.0
            currency = "USD"

            if result.rows:
                for row in result.rows:
                    total_cost += float(row[0])
                    if len(row) > 2:
                        currency = row[2]

            return {
                'subscription_id': sub_id,
                'total_cost': round(total_cost, 2),
                'currency': currency,
                'period_days': days
            }

        except Exception as e:
            logger.error("Failed to query subscription cost: %s", e)
            return {
                'subscription_id': sub_id,
                'total_cost': 0.0,
                'currency': 'USD',
                'period_days': days,
                'error': str(e)
            }


@lru_cache(maxsize=1)
def get_cost_service() -> CostService:
    """Get the CostService singleton instance."""
    return CostService()


cost_service = get_cost_service()
