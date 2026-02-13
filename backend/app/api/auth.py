"""인증 및 사용자 역할 관리 API 라우터 (PKCE Flow - JWT Bearer Token)."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr

from app.core.deps import (
    get_current_user,
    get_email_service,
    get_role_service,
    require_admin,
)

router = APIRouter(prefix="/auth")


class UserResponse(BaseModel):
    """인증된 사용자 정보 응답."""

    user_id: str
    name: str
    email: str
    tenant_id: str
    role: str


class UpdateRoleRequest(BaseModel):
    """역할 변경 요청."""

    email: EmailStr
    role: str


class AddUserRequest(BaseModel):
    """사용자 추가 요청."""

    email: EmailStr
    role: str = "user"
    name: str = ""


class PortalUserResponse(BaseModel):
    """포털 사용자 정보 응답."""

    user_id: str
    name: str
    email: str
    role: str
    status: str = "active"
    registered_at: str


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(request: Request):
    """현재 인증된 사용자 정보와 역할을 반환한다."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return UserResponse(
        user_id=user.get("user_id", ""),
        name=user.get("name", ""),
        email=user.get("email", ""),
        tenant_id=user.get("tenant_id", ""),
        role=user.get("role", "user"),
    )


@router.get("/users", response_model=list[PortalUserResponse])
async def list_portal_users(
    _admin=Depends(require_admin),
    role_svc=Depends(get_role_service),
):
    """모든 포털 사용자 목록을 조회한다 (Admin 전용)."""
    users = await role_svc.get_all_users()
    return [PortalUserResponse(**u) for u in users]


@router.post("/users", response_model=PortalUserResponse, status_code=201)
async def add_user(
    body: AddUserRequest,
    _admin=Depends(require_admin),
    role_svc=Depends(get_role_service),
):
    """포털 접근 허용 사용자를 추가한다 (Admin 전용).

    Args:
        body: 추가할 사용자 정보 (email, role, name).
    """
    if body.role not in ("admin", "user"):
        raise HTTPException(
            status_code=400, detail="Role must be 'admin' or 'user'"
        )
    user_data = await role_svc.add_user(
        email=body.email, role=body.role, name=body.name
    )
    return PortalUserResponse(**user_data)


class InviteRequest(BaseModel):
    """초대 이메일 발송 요청."""

    email: EmailStr


@router.post("/users/invite", status_code=200)
async def invite_user(
    body: InviteRequest,
    request: Request,
    _admin=Depends(require_admin),
    role_svc=Depends(get_role_service),
    email_svc=Depends(get_email_service),
):
    """등록된 사용자에게 초대 이메일을 발송한다 (Admin 전용).

    사용자가 존재하는지 확인 후 포털 접속 링크가 포함된 초대 이메일을 발송한다.
    신규 초대 및 재발송 모두 이 엔드포인트를 사용한다.

    Args:
        body: 초대할 사용자 이메일.
    """
    normalized = body.email.strip().lower()
    stored_user = await role_svc.storage.get_portal_user(normalized)
    if not stored_user:
        raise HTTPException(
            status_code=404,
            detail=f"User '{body.email}' not found. Add user first.",
        )

    inviter = get_current_user(request)
    inviter_name = inviter.get("name", "") if inviter else ""
    portal_url = request.base_url._url.rstrip("/")

    sent = await email_svc.send_invitation_email(
        email=normalized,
        role=stored_user.get("role", "user"),
        inviter_name=inviter_name,
        portal_url=portal_url,
    )

    if not sent:
        raise HTTPException(
            status_code=502,
            detail="Failed to send invitation email. Check email provider configuration.",
        )

    # 이메일 발송 성공 시 상태를 invited로 갱신
    stored_user["status"] = "invited"
    await role_svc.storage.save_portal_user(stored_user)

    return {"message": f"Invitation email sent to {normalized}"}


@router.delete("/users", status_code=204)
async def remove_user(
    email: str = Query(..., description="삭제할 사용자 이메일"),
    _admin=Depends(require_admin),
    role_svc=Depends(get_role_service),
):
    """포털 접근 허용 사용자를 제거한다 (Admin 전용).

    Args:
        email: 제거할 사용자 이메일.
    """
    await role_svc.remove_user(email)


@router.patch("/users/role", response_model=PortalUserResponse)
async def update_user_role(
    body: UpdateRoleRequest,
    _admin=Depends(require_admin),
    role_svc=Depends(get_role_service),
):
    """사용자의 역할을 변경한다 (Admin 전용).

    Args:
        body: 대상 사용자 email과 새 역할 정보.
    """
    if body.role not in ("admin", "user"):
        raise HTTPException(
            status_code=400, detail="Role must be 'admin' or 'user'"
        )
    updated_user = await role_svc.update_user_role(body.email, body.role)
    return PortalUserResponse(**updated_user)
