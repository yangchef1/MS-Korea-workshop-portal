"""Container App Job: 예약 워크샵 사전 프로비저닝.

ACA Job에서 ``python -m app.jobs.provision``으로 실행된다.
매시간 폴링하며 start_date - 1h <= now(UTC)인 scheduled 워크샵을 프로비저닝한다.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.services.storage import storage_service
from app.services.workshop import WorkshopService
from app.utils.logging import configure_logging

# Only provision workshops in 'scheduled' status
PROVISIONABLE_STATUSES = {"scheduled"}

# Provision workshops whose start_date is within this window from now
PROVISION_WINDOW = timedelta(hours=1)

logger = logging.getLogger(__name__)


async def provision_scheduled_workshops() -> None:
    """Query all workshops and provision scheduled ones approaching start_date.

    Provision criteria: status == 'scheduled' AND start_date - 1h <= now(UTC).
    """
    run_id = str(uuid.uuid4())[:8]
    logger.info("Starting provision job (run_id=%s)", run_id)

    all_workshops = await storage_service.list_all_workshops()
    now = datetime.now(timezone.utc)

    targets = []
    for ws in all_workshops:
        if ws.get("status") not in PROVISIONABLE_STATUSES:
            continue

        start_date_str = ws.get("start_date", "")
        if not start_date_str:
            continue

        try:
            start_dt = datetime.fromisoformat(
                start_date_str.replace("Z", "+00:00")
            )
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)

            if start_dt - PROVISION_WINDOW <= now:
                targets.append(ws)
        except (ValueError, TypeError):
            logger.warning(
                "Invalid start_date for workshop %s: %s",
                ws.get("id"),
                start_date_str,
            )

    if not targets:
        logger.info(
            "No scheduled workshops due for provisioning. Job complete (run_id=%s)",
            run_id,
        )
        return

    logger.info(
        "Found %d scheduled workshop(s) to provision (run_id=%s)",
        len(targets),
        run_id,
    )

    workshop_service = WorkshopService()
    succeeded = 0
    failed = 0

    for ws in targets:
        workshop_id = ws["id"]
        workshop_name = ws.get("name", "")

        try:
            await workshop_service.provision_scheduled_workshop(workshop_id)
            succeeded += 1
            logger.info(
                "Successfully provisioned scheduled workshop '%s' (%s)",
                workshop_name,
                workshop_id,
            )
        except Exception as e:
            failed += 1
            logger.error(
                "Failed to provision scheduled workshop '%s' (%s): %s",
                workshop_name,
                workshop_id,
                e,
            )
            # Mark workshop as failed so it doesn't retry indefinitely
            await _mark_workshop_failed(workshop_id, ws, str(e))

    logger.info(
        "Provision job complete: %d succeeded, %d failed (run_id=%s)",
        succeeded,
        failed,
        run_id,
    )


async def _mark_workshop_failed(
    workshop_id: str,
    workshop: dict,
    error_message: str,
) -> None:
    """Mark a workshop as failed after provisioning failure.

    The workshop's _execute_provisioning already handles rollback internally,
    so this only updates the metadata status.
    """
    try:
        workshop["status"] = "failed"
        await storage_service.save_workshop_metadata(workshop_id, workshop)
        logger.warning(
            "Workshop %s marked as failed: %s",
            workshop_id,
            error_message[:200],
        )
    except Exception as e:
        logger.error(
            "Failed to update workshop %s status to failed: %s",
            workshop_id,
            e,
        )


async def main() -> None:
    """Entry point for the Container App Job."""
    configure_logging(log_format=settings.log_format, log_level=settings.log_level)
    try:
        await provision_scheduled_workshops()
    finally:
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
