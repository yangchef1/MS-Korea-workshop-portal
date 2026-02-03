"""
Pydantic models for request/response schemas
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict


class ParticipantCreate(BaseModel):
    """Participant data from CSV"""
    email: str
    alias: str


class ParticipantResponse(BaseModel):
    """Participant response with credentials"""
    alias: str
    email: str
    upn: str
    password: str
    subscription_id: str
    resource_group: str
    object_id: str


class PolicySettings(BaseModel):
    """Azure Policy configuration"""
    allowed_regions: List[str] = Field(..., min_items=1)
    allowed_services: List[str] = Field(..., min_items=1)


class WorkshopCreate(BaseModel):
    """Workshop creation request"""
    name: str = Field(..., min_length=3, max_length=100)
    start_date: str  # ISO format date
    end_date: str  # ISO format date
    base_resources_template: str
    policy: PolicySettings


class WorkshopMetadata(BaseModel):
    """Workshop metadata stored in Blob Storage"""
    id: str
    name: str
    start_date: str
    end_date: str
    participants: List[Dict]
    base_resources_template: str
    policy: Dict
    status: str = "active"
    created_at: str
    created_by: Optional[str] = None


class WorkshopResponse(BaseModel):
    """Workshop response"""
    id: str
    name: str
    start_date: str
    end_date: str
    participant_count: int
    status: str
    created_at: str
    estimated_cost: Optional[float] = 0.0
    currency: str = "USD"


class WorkshopDetail(BaseModel):
    """Detailed workshop information"""
    id: str
    name: str
    start_date: str
    end_date: str
    participants: List[Dict]
    base_resources_template: str
    policy: Dict
    status: str
    created_at: str
    total_cost: float = 0.0
    currency: str = "USD"
    cost_breakdown: Optional[List[Dict]] = None


class CostResponse(BaseModel):
    """Cost data response"""
    total_cost: float
    currency: str
    period_days: int
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    breakdown: Optional[List[Dict]] = None


class MessageResponse(BaseModel):
    """Generic message response"""
    message: str
    detail: Optional[str] = None


class ErrorResponse(BaseModel):
    """Error response"""
    error: str
    detail: Optional[str] = None
