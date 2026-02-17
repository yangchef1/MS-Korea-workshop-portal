"""
Azure Function for automated workshop cleanup
Runs daily at 2 AM KST to delete expired workshops
"""
import azure.functions as func
import logging
import json
import asyncio
import uuid
from datetime import datetime, timezone
from azure.identity import DefaultAzureCredential
from azure.data.tables import TableServiceClient
from azure.mgmt.resource import ResourceManagementClient
from msgraph import GraphServiceClient
import os

app = func.FunctionApp()

# Multi-subscription support: prefer ALLOWED_SUBSCRIPTION_IDS, fall back to legacy single-sub env var
_ALLOWED_SUBS_RAW = os.getenv("ALLOWED_SUBSCRIPTION_IDS", "")
_LEGACY_SUB = os.getenv("AZURE_SUBSCRIPTION_ID", "")
ALLOWED_SUBSCRIPTION_IDS = [
    s.strip() for s in _ALLOWED_SUBS_RAW.split(",") if s.strip()
] or ([_LEGACY_SUB] if _LEGACY_SUB else [])
DEFAULT_SUBSCRIPTION_ID = ALLOWED_SUBSCRIPTION_IDS[0] if ALLOWED_SUBSCRIPTION_IDS else ""

AZURE_DOMAIN = os.getenv("AZURE_DOMAIN")
TABLE_STORAGE_ACCOUNT = os.getenv("TABLE_STORAGE_ACCOUNT")

# Per-subscription ResourceManagementClient cache
_resource_clients: dict[str, ResourceManagementClient] = {}


def get_resource_client(
    credential: DefaultAzureCredential, subscription_id: str
) -> ResourceManagementClient:
    """Return a cached ResourceManagementClient for the given subscription."""
    if subscription_id not in _resource_clients:
        _resource_clients[subscription_id] = ResourceManagementClient(
            credential=credential, subscription_id=subscription_id
        )
    return _resource_clients[subscription_id]

WORKSHOPS_TABLE = "workshops"
PASSWORDS_TABLE = "passwords"
DELETION_FAILURES_TABLE = "deletionfailures"
WORKSHOP_PARTITION_KEY = "workshop"
PASSWORD_PARTITION_KEY = "password"

logger = logging.getLogger(__name__)


@app.schedule(
    schedule="0 0 2 * * *",  # Daily at 2 AM KST (cron: 0 0 2 * * *)
    arg_name="timer",
    run_on_startup=False,
    use_monitor=True
)
async def workshop_cleanup(timer: func.TimerRequest) -> None:
    """
    Automated workshop cleanup function
    Deletes expired workshops and their resources
    """
    if timer.past_due:
        logger.info('The timer is past due!')

    logger.info('Starting workshop cleanup process')

    try:
        credential = DefaultAzureCredential()

        table_service_client = TableServiceClient(
            endpoint=f"https://{TABLE_STORAGE_ACCOUNT}.table.core.windows.net",
            credential=credential
        )
        workshops_table = table_service_client.get_table_client(WORKSHOPS_TABLE)
        passwords_table = table_service_client.get_table_client(PASSWORDS_TABLE)
        failures_table = table_service_client.get_table_client(DELETION_FAILURES_TABLE)

        resource_client = ResourceManagementClient(
            credential=credential,
            subscription_id=DEFAULT_SUBSCRIPTION_ID
        )

        graph_client = GraphServiceClient(
            credentials=credential,
            scopes=['https://graph.microsoft.com/.default']
        )

        today = datetime.now(timezone.utc).date()

        query_filter = f"PartitionKey eq '{WORKSHOP_PARTITION_KEY}'"
        entities = workshops_table.query_entities(query_filter)
        workshops_to_cleanup = []

        for entity in entities:
            workshop = {
                "id": entity["RowKey"],
                "name": entity.get("name", ""),
                "end_date": entity.get("end_date", ""),
                "participants": json.loads(entity.get("participants_json", "[]")),
            }

            end_date = datetime.fromisoformat(
                workshop['end_date'].replace('Z', '+00:00')
            ).date()

            if end_date < today:
                logger.info(f"Workshop {workshop['name']} (ID: {workshop['id']}) is expired")
                workshops_to_cleanup.append(workshop)

        if not workshops_to_cleanup:
            logger.info("No expired workshops found")
            return

        logger.info(f"Found {len(workshops_to_cleanup)} expired workshops to cleanup")

        cleanup_results = []
        for workshop in workshops_to_cleanup:
            result = await cleanup_workshop(
                workshop,
                credential,
                graph_client,
                workshops_table,
                passwords_table,
                failures_table,
            )
            cleanup_results.append(result)

        successful = len([r for r in cleanup_results if r['success']])
        logger.info(f"Cleanup completed: {successful}/{len(cleanup_results)} workshops cleaned up successfully")

    except Exception as e:
        logger.error(f"Cleanup process failed: {e}")
        raise


async def cleanup_workshop(
    workshop: dict,
    credential: DefaultAzureCredential,
    graph_client: GraphServiceClient,
    workshops_table,
    passwords_table,
    failures_table,
) -> dict:
    """
    Cleanup a single workshop and its resources.

    Uses per-participant subscription_id to select the correct
    ResourceManagementClient for each resource group deletion.

    Args:
        workshop: Workshop metadata.
        credential: Azure credential for creating per-sub clients.
        graph_client: Microsoft Graph client.
        workshops_table: Table client for workshops table.
        passwords_table: Table client for passwords table.
        failures_table: Table client for deletionfailures table.

    Returns:
        Dictionary with cleanup results.
    """
    workshop_id = workshop['id']
    workshop_name = workshop['name']

    result = {
        'workshop_id': workshop_id,
        'workshop_name': workshop_name,
        'success': False,
        'errors': []
    }

    try:
        participants = workshop.get('participants', [])
        logger.info(f"Cleaning up workshop {workshop_name} with {len(participants)} participants")
        now_iso = datetime.now(timezone.utc).isoformat()

        # Build participant lookup for subscription_id
        rg_to_subscription = {
            p.get('resource_group'): p.get('subscription_id', '')
            for p in participants
            if p.get('resource_group')
        }

        rg_names = [p.get('resource_group') for p in participants if p.get('resource_group')]
        if rg_names:
            logger.info(f"Deleting {len(rg_names)} resource groups...")
            rg_tasks = []
            for p in participants:
                rg_name = p.get('resource_group')
                if not rg_name:
                    continue
                sub_id = p.get('subscription_id') or DEFAULT_SUBSCRIPTION_ID
                client = get_resource_client(credential, sub_id)
                rg_tasks.append(delete_resource_group(client, rg_name))
            rg_results = await asyncio.gather(*rg_tasks, return_exceptions=True)

            for i, rg_result in enumerate(rg_results):
                if isinstance(rg_result, Exception):
                    rg_name = rg_names[i]
                    logger.error(f"Failed to delete RG {rg_name}: {rg_result}")
                    result['errors'].append(f"RG deletion failed: {rg_name}")
                    _save_failure_entity(
                        failures_table,
                        workshop_id=workshop_id,
                        workshop_name=workshop_name,
                        resource_type="resource_group",
                        resource_name=rg_name,
                        subscription_id=rg_to_subscription.get(rg_name, ""),
                        error_message=str(rg_result),
                        failed_at=now_iso,
                    )

        upns = [p.get('upn') for p in participants if p.get('upn')]
        if upns:
            logger.info(f"Deleting {len(upns)} Azure AD users...")
            user_tasks = [delete_user(graph_client, upn) for upn in upns]
            user_results = await asyncio.gather(*user_tasks, return_exceptions=True)

            for i, user_result in enumerate(user_results):
                if isinstance(user_result, Exception):
                    upn = upns[i]
                    logger.error(f"Failed to delete user {upn}: {user_result}")
                    result['errors'].append(f"User deletion failed: {upn}")
                    _save_failure_entity(
                        failures_table,
                        workshop_id=workshop_id,
                        workshop_name=workshop_name,
                        resource_type="user",
                        resource_name=upn,
                        subscription_id="",
                        error_message=str(user_result),
                        failed_at=now_iso,
                    )

        if result['errors']:
            # Partial failure — keep metadata, update status to 'failed'
            try:
                entity = workshops_table.get_entity(
                    partition_key=WORKSHOP_PARTITION_KEY,
                    row_key=workshop_id,
                )
                entity['status'] = 'failed'
                workshops_table.update_entity(entity, mode='merge')
                logger.warning(
                    f"Workshop {workshop_name} status set to 'failed' "
                    f"with {len(result['errors'])} errors"
                )
            except Exception as e:
                logger.error(f"Failed to update workshop status: {e}")
                result['errors'].append(f"Status update failed: {str(e)}")
        else:
            # Full success — delete metadata and passwords
            try:
                workshops_table.delete_entity(
                    partition_key=WORKSHOP_PARTITION_KEY,
                    row_key=workshop_id,
                )
                logger.info(f"Deleted workshop metadata: {workshop_id}")

                try:
                    passwords_table.delete_entity(
                        partition_key=PASSWORD_PARTITION_KEY,
                        row_key=workshop_id,
                    )
                    logger.info(f"Deleted passwords entity: {workshop_id}")
                except Exception as e:
                    logger.warning(f"Failed to delete passwords entity: {e}")

            except Exception as e:
                logger.error(f"Failed to delete workshop metadata: {e}")
                result['errors'].append(f"Metadata deletion failed: {str(e)}")

        result['success'] = len(result['errors']) == 0
        if result['success']:
            logger.info(f"Successfully cleaned up workshop {workshop_name}")

    except Exception as e:
        logger.error(f"Failed to cleanup workshop {workshop_name}: {e}")
        result['errors'].append(str(e))

    return result


def _save_failure_entity(
    failures_table,
    *,
    workshop_id: str,
    workshop_name: str,
    resource_type: str,
    resource_name: str,
    subscription_id: str,
    error_message: str,
    failed_at: str,
) -> None:
    """Save a deletion failure record to Table Storage (sync)."""
    try:
        entity = {
            "PartitionKey": workshop_id,
            "RowKey": str(uuid.uuid4()),
            "workshop_name": workshop_name,
            "resource_type": resource_type,
            "resource_name": resource_name,
            "subscription_id": subscription_id,
            "error_message": error_message[:1000],  # Truncate long messages
            "failed_at": failed_at,
            "status": "pending",
            "retry_count": 0,
        }
        failures_table.upsert_entity(entity)
        logger.info(
            f"Saved deletion failure: {resource_type} '{resource_name}' "
            f"(workshop: {workshop_id})"
        )
    except Exception as e:
        logger.error(f"Failed to save deletion failure record: {e}")


async def delete_resource_group(resource_client: ResourceManagementClient, rg_name: str) -> bool:
    """Delete a resource group"""
    try:
        poller = resource_client.resource_groups.begin_delete(rg_name)
        logger.info(f"Started deletion of resource group: {rg_name}")
        return True
    except Exception as e:
        logger.error(f"Failed to delete resource group {rg_name}: {e}")
        raise


async def delete_user(graph_client: GraphServiceClient, upn: str) -> bool:
    """Delete an Azure AD user"""
    try:
        user = await graph_client.users.by_user_id(upn).get()
        if user:
            await graph_client.users.by_user_id(user.id).delete()
            logger.info(f"Deleted Azure AD user: {upn}")
            return True
        return False
    except Exception as e:
        logger.error(f"Failed to delete user {upn}: {e}")
        raise
