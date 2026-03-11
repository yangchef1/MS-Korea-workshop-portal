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
    upn: str
    password: str
    subscription_id: str
    resource_group: str = ""
    object_id: str


class PolicySettings(BaseModel):
    """Azure Policy 구성."""

    allowed_regions: list[str] = Field(..., min_length=1)
    denied_services: list[str] = Field(default_factory=list)
    allowed_vm_skus: list[str] = Field(default_factory=list)


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
    upn: str
    password: str
    subscription_id: str = ""  # Default empty for backward compatibility; service layer falls back to default sub
    resource_group: str = ""  # Optional: only populated when a per-participant RG is created
    object_id: str


class SubscriptionInfo(BaseModel):
    """구독 표시 정보."""

    subscription_id: str
    display_name: Optional[str] = None


class InvalidParticipant(BaseModel):
    """유효하지 않은 구독이 배정된 참가자 정보."""

    alias: str
    subscription_id: str


class PlannedParticipant(BaseModel):
    """예약 워크샵에 저장되는 사전 참가자 데이터 (CSV 파싱 결과)."""

    email: str
    alias: str


class PolicyData(BaseModel):
    """워크샵 메타데이터에 저장되는 정책 데이터."""

    allowed_regions: list[str] = Field(..., min_length=1)
    denied_services: list[str] = Field(default_factory=list)
    allowed_vm_skus: list[str] = Field(default_factory=list)
    vm_sku_preset: Optional[str] = None


WORKSHOP_VALID_STATUSES = {"active", "completed", "creating", "deleted", "failed", "scheduled"}


class WorkshopCreateInput(BaseModel):
    """워크샵 생성 요청의 입력값을 사전 검증한다.

    Azure 리소스 생성 전에 빠르게 실패하기 위한 경량 검증 모델.
    WorkshopMetadata와 동일한 제약 조건을 공유한다.
    """

    name: str = Field(..., min_length=3, max_length=100)
    start_date: str = Field(..., min_length=1)
    end_date: str = Field(..., min_length=1)
    allowed_regions: list[str] = Field(..., min_length=1)
    denied_services: list[str] = Field(default_factory=list)
    allowed_vm_skus: list[str] = Field(default_factory=list)


class WorkshopMetadata(BaseModel):
    """Table Storage에 저장되는 워크샵 메타데이터.

    Table Storage에는 스키마 검증이 없으므로, 저장 전에 이 모델로
    앱 레벨 검증을 수행한다.
    입력값(name, dates, regions, services)은 WorkshopCreateInput에서
    사전 검증되므로, 여기서는 중복 제약을 두지 않는다.
    """

    id: str = Field(..., min_length=1)
    name: str
    start_date: str
    end_date: str
    participants: list[ParticipantData] = []
    planned_participants: list[PlannedParticipant] = []
    base_resources_template: str
    deployment_region: str = Field(
        default="",
        description="리소스 그룹 및 템플릿 배포 리전. 비어 있으면 allowed_regions[0] 사용.",
    )
    policy: PolicyData
    status: str = "active"
    created_at: str = Field(..., min_length=1)
    created_by: Optional[str] = None
    description: Optional[str] = None
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
    planned_participant_count: int = 0
    status: str
    created_at: str
    estimated_cost: Optional[float] = 0.0
    currency: str = "USD"
    created_by: Optional[str] = None
    description: Optional[str] = None
    allowed_regions: list[str] = Field(default_factory=list)
    deployment_region: str = ""


class WorkshopDetail(BaseModel):
    """워크샵 상세 정보 응답."""

    id: str
    name: str
    start_date: str
    end_date: str
    participants: list[ParticipantData]
    planned_participants: list[PlannedParticipant] = []
    planned_participant_count: int = 0
    base_resources_template: str
    deployment_region: str = ""
    policy: PolicyData
    status: str
    created_at: str
    total_cost: float = 0.0
    currency: str = "USD"
    cost_breakdown: Optional[list[dict]] = None
    survey_url: Optional[str] = None
    available_subscriptions: Optional[list[SubscriptionInfo]] = None
    invalid_participants: Optional[list[InvalidParticipant]] = None


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


class EndDateExtension(BaseModel):
    """워크샵 종료 시간 연장 요청."""

    new_end_date: str = Field(
        ...,
        description="연장할 종료 날짜 (ISO 형식, 예: 2025-01-20T18:00)",
    )

    @field_validator("new_end_date")
    @classmethod
    def validate_date_format(cls, value: str) -> str:
        """날짜 문자열이 ISO 8601 형식인지 검증한다."""
        try:
            datetime.fromisoformat(value)
        except ValueError:
            raise ValueError(
                f"Invalid date format: '{value}'. "
                "Expected ISO 8601 (e.g., '2025-01-20T18:00')"
            )
        return value


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
