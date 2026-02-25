"""인프라 템플릿 관리 API 라우터 (Admin 전용).

인프라 템플릿(ARM, Bicep)의 조회, 수정, 삭제 엔드포인트를 제공한다.
Bicep 템플릿은 저장 시 ARM JSON으로 프리컴파일되어 배포 시 즉시 사용 가능하다.
"""
import logging
from enum import Enum
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.deps import get_storage_service, require_admin
from app.exceptions import InvalidInputError
from app.services.resource_manager import compile_bicep_to_arm

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/templates", tags=["Templates"])


class TemplateType(str, Enum):
    """인프라 템플릿 유형."""

    ARM = "arm"
    BICEP = "bicep"


class TemplateListItem(BaseModel):
    """템플릿 목록 항목."""

    name: str
    description: str
    path: str
    template_type: TemplateType = TemplateType.ARM


class TemplateDetail(BaseModel):
    """템플릿 상세 정보 (콘텐츠 포함)."""

    name: str
    description: str
    path: str
    template_type: TemplateType = TemplateType.ARM
    template_content: str


class TemplateCreateRequest(BaseModel):
    """템플릿 생성 요청."""

    name: str
    description: str = ""
    template_type: TemplateType = TemplateType.ARM
    template_content: str


class TemplateUpdateRequest(BaseModel):
    """템플릿 수정 요청."""

    description: Optional[str] = None
    template_type: Optional[TemplateType] = None
    template_content: Optional[str] = None


class TemplateUpdateResponse(BaseModel):
    """템플릿 수정 응답."""

    name: str
    description: str
    path: str
    template_type: TemplateType = TemplateType.ARM


@router.get("", response_model=list[TemplateListItem])
async def list_templates(
    storage=Depends(get_storage_service),
):
    """등록된 인프라 템플릿 목록을 조회한다."""
    templates_data = await storage.list_templates()
    return [
        TemplateListItem(
            name=t.get("name", ""),
            description=t.get("description", ""),
            path=t.get("path", ""),
            template_type=t.get("template_type", TemplateType.ARM),
        )
        for t in templates_data
    ]


@router.post("", response_model=TemplateListItem, status_code=201)
async def create_template(
    body: TemplateCreateRequest,
    _admin=Depends(require_admin),
    storage=Depends(get_storage_service),
):
    """새 인프라 템플릿을 생성한다 (Admin 전용).

    Bicep 템플릿은 ARM JSON으로 프리컴파일하여 함께 저장한다.

    Args:
        body: 템플릿 이름, 설명, 유형, 콘텐츠.
    """
    compiled_arm = None
    if body.template_type == TemplateType.BICEP:
        compiled_arm = await compile_bicep_to_arm(body.template_content)

    created = await storage.create_template(
        name=body.name,
        description=body.description,
        template_content=body.template_content,
        template_type=body.template_type.value,
        compiled_arm_content=compiled_arm,
    )
    return TemplateListItem(**created)


@router.get("/{template_name}", response_model=TemplateDetail)
async def get_template(
    template_name: str,
    _admin=Depends(require_admin),
    storage=Depends(get_storage_service),
):
    """인프라 템플릿 상세 정보를 조회한다 (Admin 전용).

    Args:
        template_name: 조회할 템플릿 이름.
    """
    from app.exceptions import NotFoundError

    detail = await storage.get_template_detail(template_name)
    if not detail:
        raise NotFoundError(f"Template '{template_name}' not found")

    return TemplateDetail(**detail)


@router.patch("/{template_name}", response_model=TemplateUpdateResponse)
async def update_template(
    template_name: str,
    body: TemplateUpdateRequest,
    _admin=Depends(require_admin),
    storage=Depends(get_storage_service),
):
    """인프라 템플릿을 수정한다 (Admin 전용).

    Bicep 템플릿은 콘텐츠 변경 시 ARM JSON으로 재컴파일한다.

    Args:
        template_name: 수정할 템플릿 이름.
        body: 수정할 필드 (description, template_type, template_content).
    """
    compiled_arm = None
    effective_type = body.template_type.value if body.template_type else None

    # Bicep 컴파일 필요 여부: 유형이 bicep이고 콘텐츠가 변경된 경우
    needs_compile = False
    if effective_type == "bicep" and body.template_content:
        needs_compile = True
    elif effective_type is None and body.template_content:
        # 유형 미변경 + 콘텐츠 변경: 기존 유형이 bicep인지 확인 필요
        detail = await storage.get_template_detail(template_name)
        if detail and detail.get("template_type") == "bicep":
            needs_compile = True

    if needs_compile:
        compiled_arm = await compile_bicep_to_arm(body.template_content)

    updated = await storage.update_template(
        template_name=template_name,
        description=body.description,
        template_content=body.template_content,
        template_type=effective_type,
        compiled_arm_content=compiled_arm,
    )
    return TemplateUpdateResponse(**updated)


@router.delete("/{template_name}", status_code=204)
async def delete_template(
    template_name: str,
    _admin=Depends(require_admin),
    storage=Depends(get_storage_service),
):
    """인프라 템플릿을 삭제한다 (Admin 전용).

    Args:
        template_name: 삭제할 템플릿 이름.
    """
    await storage.delete_template(template_name)
