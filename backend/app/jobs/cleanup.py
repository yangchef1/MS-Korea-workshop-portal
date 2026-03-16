"""Container App Job: 만료 워크샵 자동 정리.

function/function_app.py의 timer-based cleanup을 async 버전으로 포팅.
ACA Job에서 ``python -m app.jobs.cleanup``으로 실행된다.
매시간 폴링하며 end_date(KST) + 1h < now(KST)인 워크샵을 정리한다.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

# Workshop dates are stored as naive ISO strings in KST (UTC+9)
_KST = timezone(timedelta(hours=9))

from app.config import settings
from app.exceptions import PolicyNotFoundError
from app.models import DeletionFailureItem
from app.services.cost import cost_service
from app.services.entra_id import entra_id_service
from app.services.policy import policy_service
from app.services.resource_manager import resource_manager_service
from app.services.storage import storage_service
from app.utils.logging import configure_logging

# Policy assignment names (same as in workshop.py)
WORKSHOP_ALLOWED_LOCATIONS_ASSIGNMENT = "workshop-allowed-locations"
WORKSHOP_DENIED_RESOURCES_ASSIGNMENT = "workshop-denied-resources"
WORKSHOP_ALLOWED_VM_SKUS_ASSIGNMENT = "workshop-allowed-vm-skus"

# Also resume workshops stuck in 'cleaning_up' (e.g. after crash)
CLEANABLE_STATUSES = {"active", "cleaning_up"}

logger = logging.getLogger(__name__)


async def cleanup_expired_workshops() -> None:
    """Query all workshops and clean up expired ones.

    Expiration criteria: end_date(KST) + 1h < now(KST).
    Only workshops with status in CLEANABLE_STATUSES are processed.
    """
    run_id = str(uuid.uuid4())[:8]
    logger.info("Starting cleanup job (run_id=%s)", run_id)

    # 1. Fetch all workshops from Table Storage
    all_workshops = await storage_service.list_all_workshops()
    now = datetime.now(_KST)

    # 2. Filter expired workshops: end_date(KST) + 1h < now(KST), status == 'active'
    expired = []
    for ws in all_workshops:
        if ws.get("status", "active") not in CLEANABLE_STATUSES:
            continue
        end_date_str = ws.get("end_date", "")
        if not end_date_str:
            continue
        try:
            end_dt = datetime.fromisoformat(
                end_date_str.replace("Z", "+09:00")
            )
            # Naive datetimes from DB are KST
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=_KST)
            if end_dt + timedelta(hours=1) < now:
                expired.append(ws)
        except (ValueError, TypeError):
            logger.warning(
                "Invalid end_date for workshop %s: %s",
                ws.get("id"),
                end_date_str,
            )

    if not expired:
        logger.info("No expired workshops found. Job complete (run_id=%s)", run_id)
        return

    logger.info(
        "Found %d expired workshop(s) to clean up (run_id=%s)",
        len(expired),
        run_id,
    )

    # 3. Clean up each expired workshop
    successful_count = 0
    for ws in expired:
        fully_succeeded, releasable_ids = await _cleanup_single_workshop(ws)
        if fully_succeeded:
            successful_count += 1

        # Release subscriptions whose resources were fully cleaned up
        if releasable_ids:
            try:
                await storage_service.release_subscriptions(releasable_ids)
                logger.info(
                    "Released %d subscription(s) for workshop %s",
                    len(releasable_ids),
                    ws["id"],
                )
            except Exception as e:
                logger.error(
                    "Failed to release subscriptions for workshop %s: %s",
                    ws["id"],
                    e,
                )

        if not fully_succeeded and releasable_ids:
            # Count locked subscriptions for logging
            all_sub_ids = {p.get("subscription_id") for p in ws.get("participants", []) if p.get("subscription_id")}
            locked_count = len(all_sub_ids) - len(releasable_ids)
            logger.warning(
                "Workshop %s: released %d subscription(s), %d still locked due to cleanup failures",
                ws["id"],
                len(releasable_ids),
                locked_count,
            )

    logger.info(
        "Cleanup job complete: %d/%d workshops fully cleaned (run_id=%s)",
        successful_count,
        len(expired),
        run_id,
    )


async def _cleanup_single_workshop(workshop: dict) -> tuple[bool, list[str]]:
    """Clean up a single expired workshop.

    Returns:
        (fully_succeeded, releasable_subscription_ids) tuple.
        fully_succeeded is True when all resources were cleaned up.
        releasable_subscription_ids contains subscription IDs whose
        policy, resource group, and user deletions all succeeded.
    """
    workshop_id = workshop["id"]
    workshop_name = workshop.get("name", "")
    participants = workshop.get("participants", [])
    now_iso = datetime.now(timezone.utc).isoformat()
    errors: list[str] = []

    logger.info(
        "Cleaning up workshop '%s' (ID: %s) with %d participants",
        workshop_name,
        workshop_id,
        len(participants),
    )

    # Pre-step: Capture snapshots and transition to cleaning_up (skip if already cleaning_up)
    if workshop.get("status") != "cleaning_up":
        from app.services.workshop import _capture_workshop_snapshot
        snapshots = await _capture_workshop_snapshot(
            participants,
            cost_service,
            resource_manager_service,
            start_date=workshop.get("start_date"),
            end_date=workshop.get("end_date"),
        )
        workshop["cost_snapshot"] = snapshots["cost_snapshot"]
        workshop["resource_snapshot"] = snapshots["resource_snapshot"]
        workshop["status"] = "cleaning_up"
        await storage_service.save_workshop_metadata(workshop_id, workshop)
        logger.info("Workshop '%s' transitioned to cleaning_up (snapshot captured)", workshop_name)

    # Step 0: Remove policy assignments (per subscription), track results
    policy_status: dict[str, bool] = {}
    seen_subs: set[str] = set()
    for p in participants:
        sub_id = p.get("subscription_id")
        if sub_id and sub_id not in seen_subs:
            seen_subs.add(sub_id)
            sub_scope = f"/subscriptions/{sub_id}"
            sub_policy_ok = True
            for assignment_name in (
                WORKSHOP_ALLOWED_LOCATIONS_ASSIGNMENT,
                WORKSHOP_DENIED_RESOURCES_ASSIGNMENT,
                WORKSHOP_ALLOWED_VM_SKUS_ASSIGNMENT,
            ):
                try:
                    await policy_service.delete_policy_assignment(
                        scope=sub_scope,
                        assignment_name=assignment_name,
                        subscription_id=sub_id,
                    )
                except PolicyNotFoundError:
                    # Already removed — treat as success
                    pass
                except Exception as e:
                    sub_policy_ok = False
                    error_msg = f"Failed to delete policy '{assignment_name}' on subscription '{sub_id}'"
                    errors.append(error_msg)
                    logger.warning("%s: %s", error_msg, e)
                    await _save_failure(
                        workshop_id=workshop_id,
                        workshop_name=workshop_name,
                        resource_type="policy",
                        resource_name=assignment_name,
                        subscription_id=sub_id,
                        error_message=f"{error_msg}: {e}",
                        failed_at=now_iso,
                    )
            policy_status[sub_id] = sub_policy_ok
            if sub_policy_ok:
                logger.info("Removed policies from subscription %s", sub_id)
            else:
                logger.warning("Partially failed to remove policies from subscription %s", sub_id)

    # Step 1: Delete resource groups
    rg_status: dict[str, bool] = {}
    rg_specs = []
    for p in participants:
        rg_name = p.get("resource_group")
        if rg_name:
            rg_specs.append({
                "name": rg_name,
                "subscription_id": p.get("subscription_id"),
            })

    if rg_specs:
        logger.info("Deleting %d resource group(s)...", len(rg_specs))
        rg_status = await resource_manager_service.delete_resource_groups_bulk(
            rg_specs
        )
        for spec in rg_specs:
            rg_name = spec["name"]
            if not rg_status.get(rg_name, False):
                error_msg = f"Failed to delete resource group '{rg_name}'"
                errors.append(error_msg)
                await _save_failure(
                    workshop_id=workshop_id,
                    workshop_name=workshop_name,
                    resource_type="resource_group",
                    resource_name=rg_name,
                    subscription_id=spec.get("subscription_id", ""),
                    error_message=error_msg,
                    failed_at=now_iso,
                )

    # Step 2: Delete Entra ID users (with object_id optimization)
    user_status: dict[str, bool] = {}
    upns = [p.get("upn") for p in participants if p.get("upn")]
    if upns:
        logger.info("Deleting %d Entra ID user(s)...", len(upns))
        upn_to_object_id = {
            p["upn"]: p["object_id"]
            for p in participants
            if p.get("upn") and p.get("object_id")
        }
        user_status = await entra_id_service.delete_users_bulk(
            upns,
            upn_to_object_id=upn_to_object_id,
        )
        for upn in upns:
            if not user_status.get(upn, False):
                error_msg = f"Failed to delete user '{upn}'"
                errors.append(error_msg)
                await _save_failure(
                    workshop_id=workshop_id,
                    workshop_name=workshop_name,
                    resource_type="user",
                    resource_name=upn,
                    subscription_id="",
                    error_message=error_msg,
                    failed_at=now_iso,
                )

    # Determine which subscriptions can be released (all 3 checks passed)
    from app.services.workshop import _get_releasable_subscription_ids
    releasable_ids = _get_releasable_subscription_ids(
        participants, policy_status, rg_status, user_status,
    )

    # Step 3: Update workshop status or delete metadata
    if errors:
        # Partial failure: keep metadata, set status to 'failed'
        try:
            workshop["status"] = "failed"
            await storage_service.save_workshop_metadata(workshop_id, workshop)
            logger.warning(
                "Workshop '%s' cleanup partially failed with %d error(s)",
                workshop_name,
                len(errors),
            )
        except Exception as e:
            logger.error("Failed to update workshop status: %s", e)
        return False, releasable_ids

    # Full success: mark as completed and strip sensitive data
    try:
        sensitive_fields = ("password", "object_id")
        for participant in participants:
            for field in sensitive_fields:
                participant.pop(field, None)
        workshop["status"] = "completed"
        await storage_service.save_workshop_metadata(workshop_id, workshop)
        logger.info("Successfully cleaned up workshop '%s' — status set to completed", workshop_name)
    except Exception as e:
        logger.error("Failed to update workshop status to completed: %s", e)
        return False, releasable_ids
    return True, releasable_ids


async def _save_failure(
    *,
    workshop_id: str,
    workshop_name: str,
    resource_type: str,
    resource_name: str,
    subscription_id: str,
    error_message: str,
    failed_at: str,
) -> None:
    """Save a deletion failure record to Table Storage."""
    try:
        failure = DeletionFailureItem(
            id=str(uuid.uuid4()),
            workshop_id=workshop_id,
            workshop_name=workshop_name,
            resource_type=resource_type,
            resource_name=resource_name,
            subscription_id=subscription_id,
            error_message=error_message[:1000],
            failed_at=failed_at,
            status="pending",
            retry_count=0,
        )
        await storage_service.save_deletion_failure(failure)
    except Exception as e:
        logger.error("Failed to save deletion failure record: %s", e)


async def main() -> None:
    """Entry point for the Container App Job."""
    configure_logging(log_format=settings.log_format, log_level=settings.log_level)
    try:
        await cleanup_expired_workshops()
    finally:
        # Gracefully close async Azure SDK sessions
        await _close_service_clients()


async def _close_service_clients() -> None:
    """Close async SDK clients to prevent resource warnings."""
    for close_fn in (
        lambda: storage_service.table_service_client.close(),
    ):
        try:
            await close_fn()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
