"""
Workshop API routes
"""
import logging
import uuid
import asyncio
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import Response

from pydantic import BaseModel

from app.models import (
    WorkshopResponse,
    WorkshopDetail,
    MessageResponse,
    CostResponse
)
from app.core.deps import (
    get_storage_service,
    get_entra_id_service,
    get_resource_manager_service,
    get_policy_service,
    get_cost_service,
    get_email_service
)
from app.utils.csv_parser import parse_participants_csv, generate_passwords_csv
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workshops", tags=["Workshops"])


class ArmTemplate(BaseModel):
    name: str
    description: str
    path: str


class ResourceType(BaseModel):
    value: str
    label: str
    category: str


@router.get("/templates", response_model=List[ArmTemplate])
async def get_templates(storage=Depends(get_storage_service)):
    """Get available ARM templates for workshop creation"""
    try:
        templates_data = storage.list_arm_templates()
        return [
            ArmTemplate(
                name=t.get('name', ''),
                description=t.get('description', ''),
                path=t.get('path', '')
            )
            for t in templates_data
        ]
    except Exception as e:
        logger.error(f"Failed to get templates: {e}")
        return []


@router.get("/resource-types", response_model=List[ResourceType])
async def get_resource_types(resource_manager=Depends(get_resource_manager_service)):
    """Get available Azure resource types (cached for 24 hours)"""
    try:
        resource_types_data = resource_manager.get_resource_types()
        return [
            ResourceType(
                value=rt.get('value', ''),
                label=rt.get('label', ''),
                category=rt.get('category', '')
            )
            for rt in resource_types_data
        ]
    except Exception as e:
        logger.error(f"Failed to get resource types: {e}")
        return []


@router.get("", response_model=List[WorkshopResponse])
async def list_workshops(
    storage=Depends(get_storage_service),
    cost=Depends(get_cost_service)
):
    """List all active workshops"""
    try:
        workshops = storage.list_all_workshops()

        async def enrich_workshop(workshop):
            # Pass full participant info for per-subscription cost query
            participants = [
                {
                    'resource_group': p.get('resource_group'),
                    'subscription_id': p.get('subscription_id')
                }
                for p in workshop.get('participants', [])
            ]
            
            if participants:
                cost_data = await cost.get_workshop_total_cost(participants, days=30)
                return WorkshopResponse(
                    id=workshop['id'],
                    name=workshop['name'],
                    start_date=workshop['start_date'],
                    end_date=workshop['end_date'],
                    participant_count=len(workshop.get('participants', [])),
                    status=workshop.get('status', 'active'),
                    created_at=workshop.get('created_at', ''),
                    estimated_cost=cost_data.get('total_cost', 0.0),
                    currency=cost_data.get('currency', 'USD')
                )
            else:
                return WorkshopResponse(
                    id=workshop['id'],
                    name=workshop['name'],
                    start_date=workshop['start_date'],
                    end_date=workshop['end_date'],
                    participant_count=len(workshop.get('participants', [])),
                    status=workshop.get('status', 'active'),
                    created_at=workshop.get('created_at', '')
                )

        enriched = await asyncio.gather(*[enrich_workshop(w) for w in workshops])
        return enriched

    except Exception as e:
        logger.error(f"Failed to list workshops: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{workshop_id}", response_model=WorkshopDetail)
async def get_workshop(
    workshop_id: str,
    storage=Depends(get_storage_service),
    cost=Depends(get_cost_service)
):
    """Get workshop details"""
    try:
        metadata = storage.get_workshop_metadata(workshop_id)
        if not metadata:
            raise HTTPException(status_code=404, detail="Workshop not found")

        # Pass full participant info for per-subscription cost query
        participants = [
            {
                'resource_group': p.get('resource_group'),
                'subscription_id': p.get('subscription_id')
            }
            for p in metadata.get('participants', [])
        ]
        cost_data = await cost.get_workshop_total_cost(participants, days=30)

        return WorkshopDetail(
            id=metadata['id'],
            name=metadata['name'],
            start_date=metadata['start_date'],
            end_date=metadata['end_date'],
            participants=metadata.get('participants', []),
            base_resources_template=metadata.get('base_resources_template', ''),
            policy=metadata.get('policy', {}),
            status=metadata.get('status', 'active'),
            created_at=metadata.get('created_at', ''),
            total_cost=cost_data.get('total_cost', 0.0),
            currency=cost_data.get('currency', 'USD'),
            cost_breakdown=cost_data.get('breakdown')
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get workshop: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("", response_model=WorkshopDetail)
async def create_workshop(
    name: str = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...),
    base_resources_template: str = Form(...),
    allowed_regions: str = Form(...),
    allowed_services: str = Form(...),
    participants_file: UploadFile = File(...),
    storage=Depends(get_storage_service),
    entra_id=Depends(get_entra_id_service),
    resource_mgr=Depends(get_resource_manager_service),
    policy=Depends(get_policy_service)
):
    """
    Create a new workshop with per-participant subscription assignment.
    
    CSV format: email,subscription_id
    Each participant must have their own subscription_id in the CSV file.
    Resources are created in the participant's dedicated subscription.
    """
    try:
        workshop_id = str(uuid.uuid4())
        
        # CSV now includes email and subscription_id per participant
        # alias is extracted from email
        participants = await parse_participants_csv(participants_file)
        regions = [r.strip() for r in allowed_regions.split(',')]
        services = [s.strip() for s in allowed_services.split(',')]
        
        logger.info(f"Creating workshop with {len(participants)} participants (per-subscription mode)")

        # Create Entra ID users
        user_results = await entra_id.create_users_bulk([p['alias'] for p in participants])
        if not user_results:
            raise HTTPException(status_code=500, detail="Failed to create users")

        # Map subscription_id and email from CSV to user results
        alias_to_data = {p['alias']: {'subscription_id': p['subscription_id'], 'email': p['email']} for p in participants}
        for user in user_results:
            user_data = alias_to_data.get(user['alias'], {})
            user['subscription_id'] = user_data.get('subscription_id')
            user['email'] = user_data.get('email')

        # Create resource groups in each participant's subscription
        rg_specs = [
            {
                'name': f"{settings.resource_group_prefix}-{workshop_id[:8]}-{user['alias']}",
                'location': regions[0],
                'subscription_id': user['subscription_id'],
                'tags': {
                    'workshop_id': workshop_id,
                    'workshop_name': name,
                    'end_date': end_date,
                    'participant': user['alias']
                }
            }
            for user in user_results
        ]
        rg_results = await resource_mgr.create_resource_groups_bulk(rg_specs)

        async def setup_participant(user, rg_spec):
            try:
                rg = next((r for r in rg_results if r['name'] == rg_spec['name']), None)
                if not rg:
                    return None

                subscription_id = user['subscription_id']

                # Assign RBAC role in participant's subscription
                await resource_mgr.assign_rbac_role(
                    scope=rg['id'],
                    principal_id=user['object_id'],
                    role_name=settings.default_user_role,
                    subscription_id=subscription_id
                )

                # Deploy ARM template if specified
                if base_resources_template and base_resources_template != "none":
                    template = storage.get_arm_template(base_resources_template)
                    if template:
                        await resource_mgr.deploy_arm_template(
                            resource_group_name=rg['name'],
                            template=template,
                            parameters={},
                            subscription_id=subscription_id
                        )

                # Assign policies at subscription level for this participant's subscription
                subscription_scope = f"/subscriptions/{subscription_id}"
                await policy.assign_workshop_policies(
                    scope=subscription_scope,
                    allowed_locations=regions,
                    allowed_resource_types=services,
                    subscription_id=subscription_id
                )

                return {
                    'alias': user['alias'],
                    'email': user.get('email', ''),
                    'upn': user['upn'],
                    'password': user['password'],
                    'subscription_id': subscription_id,
                    'resource_group': rg['name'],
                    'object_id': user['object_id']
                }
            except Exception as e:
                logger.error(f"Failed to setup participant {user['alias']}: {e}")
                return None

        participant_results = await asyncio.gather(
            *[setup_participant(user, rg_spec) for user, rg_spec in zip(user_results, rg_specs)],
            return_exceptions=True
        )
        successful_participants = [p for p in participant_results if p and not isinstance(p, Exception)]

        metadata = {
            'id': workshop_id,
            'name': name,
            'start_date': start_date,
            'end_date': end_date,
            'participants': successful_participants,
            'base_resources_template': base_resources_template,
            'policy': {'allowed_regions': regions, 'allowed_services': services},
            'status': 'active',
            'created_at': datetime.utcnow().isoformat() + 'Z'
        }
        storage.save_workshop_metadata(workshop_id, metadata)
        
        csv_content = generate_passwords_csv(successful_participants)
        storage.save_passwords_csv(workshop_id, csv_content)

        logger.info(f"Workshop created: {workshop_id}")

        return WorkshopDetail(
            id=workshop_id,
            name=name,
            start_date=start_date,
            end_date=end_date,
            participants=successful_participants,
            base_resources_template=base_resources_template,
            policy=metadata['policy'],
            status='active',
            created_at=metadata['created_at'],
            total_cost=0.0,
            currency='USD'
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create workshop: {e}")
        raise HTTPException(status_code=500, detail=f"Workshop creation failed: {str(e)}")


@router.delete("/{workshop_id}", response_model=MessageResponse)
async def delete_workshop(
    workshop_id: str,
    storage=Depends(get_storage_service),
    entra_id=Depends(get_entra_id_service),
    resource_mgr=Depends(get_resource_manager_service)
):
    """Delete a workshop and cleanup all resources (supports per-subscription)"""
    try:
        metadata = storage.get_workshop_metadata(workshop_id)
        if not metadata:
            raise HTTPException(status_code=404, detail="Workshop not found")

        participants = metadata.get('participants', [])

        # Delete resource groups with subscription context
        rg_specs = [
            {
                'name': p.get('resource_group'),
                'subscription_id': p.get('subscription_id')
            }
            for p in participants
        ]
        await resource_mgr.delete_resource_groups_bulk(rg_specs)

        upns = [p.get('upn') for p in participants]
        await entra_id.delete_users_bulk(upns)

        storage.delete_workshop_metadata(workshop_id)

        logger.info(f"Workshop deleted: {workshop_id}")

        return MessageResponse(
            message="Workshop deleted successfully",
            detail=f"Deleted {len(participants)} participants and their resources"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete workshop: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{workshop_id}/passwords", response_class=Response)
async def download_passwords(
    workshop_id: str,
    storage=Depends(get_storage_service)
):
    """Download passwords CSV file"""
    try:
        csv_content = storage.get_passwords_csv(workshop_id)
        if not csv_content:
            raise HTTPException(status_code=404, detail="Passwords file not found")

        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=workshop-{workshop_id}-passwords.csv"}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to download passwords: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{workshop_id}/resources")
async def get_workshop_resources(
    workshop_id: str,
    storage=Depends(get_storage_service),
    resource_mgr=Depends(get_resource_manager_service)
):
    """Get all resources in workshop resource groups (supports per-subscription)"""
    try:
        metadata = storage.get_workshop_metadata(workshop_id)
        if not metadata:
            raise HTTPException(status_code=404, detail="Workshop not found")

        participants = metadata.get('participants', [])
        all_resources = []

        for participant in participants:
            rg_name = participant.get('resource_group')
            subscription_id = participant.get('subscription_id')
            if rg_name:
                resources = await resource_mgr.list_resources_in_group(
                    rg_name,
                    subscription_id=subscription_id
                )
                for resource in resources:
                    resource['participant'] = participant.get('alias', '')
                    resource['resource_group'] = rg_name
                    resource['subscription_id'] = subscription_id
                all_resources.extend(resources)

        return {
            'workshop_id': workshop_id,
            'total_count': len(all_resources),
            'resources': all_resources
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get workshop resources: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{workshop_id}/cost", response_model=CostResponse)
async def get_workshop_cost(
    workshop_id: str,
    use_workshop_period: bool = True,
    storage=Depends(get_storage_service),
    cost=Depends(get_cost_service)
):
    """Get workshop cost details based on workshop period (supports per-subscription)"""
    try:
        metadata = storage.get_workshop_metadata(workshop_id)
        if not metadata:
            raise HTTPException(status_code=404, detail="Workshop not found")

        # Pass full participant info for per-subscription cost query
        participants = [
            {
                'resource_group': p.get('resource_group'),
                'subscription_id': p.get('subscription_id')
            }
            for p in metadata.get('participants', [])
        ]
        
        if use_workshop_period:
            start_date = metadata.get('start_date')
            end_date = metadata.get('end_date')
            cost_data = await cost.get_workshop_total_cost(
                participants, 
                start_date=start_date, 
                end_date=end_date
            )
            cost_data['start_date'] = start_date
            cost_data['end_date'] = end_date
        else:
            cost_data = await cost.get_workshop_total_cost(participants, days=30)

        return CostResponse(**cost_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get workshop cost: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class EmailSendResponse(BaseModel):
    """Response for email send operation"""
    total: int
    sent: int
    failed: int
    results: dict


@router.post("/{workshop_id}/send-credentials", response_model=EmailSendResponse)
async def send_credentials_email(
    workshop_id: str,
    participant_emails: Optional[List[str]] = Query(
        default=None,
        description="Specific participant emails to send to. If not provided, sends to all participants."
    ),
    storage=Depends(get_storage_service),
    email=Depends(get_email_service)
):
    """
    Send credential emails to workshop participants.
    
    - If participant_emails is provided, only send to those specific emails
    - If not provided, send to all participants in the workshop
    """
    try:
        metadata = storage.get_workshop_metadata(workshop_id)
        if not metadata:
            raise HTTPException(status_code=404, detail="Workshop not found")

        workshop_name = metadata.get('name', 'Azure Workshop')
        all_participants = metadata.get('participants', [])
        
        # Filter participants if specific emails provided
        if participant_emails:
            participants_to_send = [
                p for p in all_participants 
                if p.get('email', '').lower() in [e.lower() for e in participant_emails]
            ]
            if not participants_to_send:
                raise HTTPException(
                    status_code=400, 
                    detail="No matching participants found for provided emails"
                )
        else:
            participants_to_send = all_participants
        
        # Check if participants have email addresses
        participants_with_email = [p for p in participants_to_send if p.get('email')]
        if not participants_with_email:
            raise HTTPException(
                status_code=400,
                detail="No participants have email addresses configured"
            )
        
        # Send emails
        results = await email.send_credentials_bulk(participants_with_email, workshop_name)
        
        sent_count = sum(1 for v in results.values() if v)
        failed_count = len(results) - sent_count
        
        logger.info(f"Sent credentials for workshop {workshop_id}: {sent_count} sent, {failed_count} failed")
        
        return EmailSendResponse(
            total=len(results),
            sent=sent_count,
            failed=failed_count,
            results=results
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to send credentials: {e}")
        raise HTTPException(status_code=500, detail=str(e))
