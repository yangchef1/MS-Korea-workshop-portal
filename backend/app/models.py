"""API 요청/응답에 사용되는 Pydantic 모델."""
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class UserRole(str, Enum):
    """포털 사용자 역할."""

    ADMIN = "admin"
    USER = "user"


class UserStatus(str, Enum):
    """포털 사용자 상태."""

    ACTIVE = "active"
    PENDING = "pending"
    INVITED = "invited"


class PortalUser(BaseModel):
    """Table Storage에 저장되는 포털 사용자 정보."""

    user_id: str
    name: str
    email: str
    role: UserRole = UserRole.USER
    status: UserStatus = UserStatus.ACTIVE
    registered_at: str


class ParticipantCreate(BaseModel):
    """참가자 데이터 (CSV 파싱 결과)."""

    email: str
    alias: str


class ParticipantResponse(BaseModel):
    """자격 증명이 포함된 참가자 응답."""

    alias: str
    email: str
    upn: str
    password: str
    subscription_id: str
    resource_group: str
    object_id: str


class PolicySettings(BaseModel):
    """Azure Policy 구성."""

    allowed_regions: list[str] = Field(..., min_length=1)
    allowed_services: list[str] = Field(..., min_length=1)


class WorkshopCreate(BaseModel):
    """워크샵 생성 요청."""

    name: str = Field(..., min_length=3, max_length=100)
    start_date: str = Field(..., description="ISO 형식 날짜 (예: 2025-01-15T09:00)")
    end_date: str = Field(..., description="ISO 형식 날짜 (예: 2025-01-15T18:00)")
    base_resources_template: str
    policy: PolicySettings
    survey_url: Optional[str] = Field(
        default=None,
        description="M365 Forms 만족도 조사 URL",
    )

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_date_format(cls, value: str) -> str:
        """날짜 문자열이 ISO 8601 형식인지 검증한다."""
        try:
            datetime.fromisoformat(value)
        except ValueError:
            raise ValueError(
                f"Invalid date format: '{value}'. "
                "Expected ISO 8601 (e.g., '2025-01-15T09:00')"
            )
        return value

    @model_validator(mode="after")
    def validate_date_range(self) -> "WorkshopCreate":
        """end_date가 start_date 이후인지 검증한다."""
        start = datetime.fromisoformat(self.start_date)
        end = datetime.fromisoformat(self.end_date)
        if end <= start:
            raise ValueError("end_date must be after start_date")
        return self


class ParticipantData(BaseModel):
    """워크샵 메타데이터에 저장되는 참가자 데이터."""

    alias: str
    email: str
    upn: str
    password: str
    subscription_id: str = ""  # Default empty for backward compatibility; service layer falls back to default sub
    resource_group: str
    object_id: str


class PolicyData(BaseModel):
    """워크샵 메타데이터에 저장되는 정책 데이터."""

    allowed_regions: list[str] = Field(..., min_length=1)
    allowed_services: list[str] = Field(..., min_length=1)


WORKSHOP_VALID_STATUSES = {"active", "completed", "deleted", "failed"}


class WorkshopMetadata(BaseModel):
    """Table Storage에 저장되는 워크샵 메타데이터.

    Table Storage에는 스키마 검증이 없으므로, 저장 전에 이 모델로
    앱 레벨 검증을 수행한다.
    """

    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=3, max_length=100)
    start_date: str = Field(..., min_length=1)
    end_date: str = Field(..., min_length=1)
    participants: list[ParticipantData] = []
    base_resources_template: str
    policy: PolicyData
    status: str = "active"
    created_at: str = Field(..., min_length=1)
    created_by: Optional[str] = None
    survey_url: Optional[str] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        """status 값이 허용된 상태 중 하나인지 검증한다."""
        if value not in WORKSHOP_VALID_STATUSES:
            raise ValueError(
                f"Invalid status '{value}'. "
                f"Must be one of: {WORKSHOP_VALID_STATUSES}"
            )
        return value


class WorkshopResponse(BaseModel):
    """워크샵 목록 조회 응답."""

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
    """워크샵 상세 정보 응답."""

    id: str
    name: str
    start_date: str
    end_date: str
    participants: list[ParticipantData]
    base_resources_template: str
    policy: PolicyData
    status: str
    created_at: str
    total_cost: float = 0.0
    currency: str = "USD"
    cost_breakdown: Optional[list[dict]] = None
    survey_url: Optional[str] = None


class CostResponse(BaseModel):
    """비용 데이터 응답."""

    total_cost: float
    currency: str
    period_days: int
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    breakdown: Optional[list[dict]] = None


class MessageResponse(BaseModel):
    """단순 메시지 응답."""

    message: str
    detail: Optional[str] = None


class SurveyUrlUpdate(BaseModel):
    """만족도 조사 URL 업데이트 요청."""

    survey_url: str = Field(
        ...,
        min_length=1,
        description="M365 Forms 만족도 조사 URL",
    )


class ErrorResponse(BaseModel):
    """에러 응답."""

    error: str
    detail: Optional[str] = None


# ------------------------------------------------------------------
# Deletion failure tracking
# ------------------------------------------------------------------

DELETION_FAILURE_RESOURCE_TYPES = {"resource_group", "user"}
DELETION_FAILURE_STATUSES = {"pending", "resolved"}


class DeletionFailureItem(BaseModel):
    """삭제 실패 항목."""

    id: str = Field(..., min_length=1)
    workshop_id: str = Field(..., min_length=1)
    workshop_name: str = ""
    resource_type: str = Field(
        ..., description="resource_group 또는 user"
    )
    resource_name: str = Field(..., min_length=1)
    subscription_id: Optional[str] = None
    error_message: str = ""
    failed_at: str = Field(..., min_length=1)
    status: str = "pending"
    retry_count: int = 0

    @field_validator("resource_type")
    @classmethod
    def validate_resource_type(cls, value: str) -> str:
        """resource_type 값이 허용된 유형인지 검증한다."""
        if value not in DELETION_FAILURE_RESOURCE_TYPES:
            raise ValueError(
                f"Invalid resource_type '{value}'. "
                f"Must be one of: {DELETION_FAILURE_RESOURCE_TYPES}"
            )
        return value

    @field_validator("status")
    @classmethod
    def validate_failure_status(cls, value: str) -> str:
        """status 값이 허용된 상태인지 검증한다."""
        if value not in DELETION_FAILURE_STATUSES:
            raise ValueError(
                f"Invalid status '{value}'. "
                f"Must be one of: {DELETION_FAILURE_STATUSES}"
            )
        return value


class DeletionFailureListResponse(BaseModel):
    """삭제 실패 목록 응답."""

    items: list[DeletionFailureItem] = []
    total_count: int = 0
