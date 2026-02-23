"""FastAPI 의존성 주입 팩토리.

각 서비스 싱글턴 인스턴스를 FastAPI의 ``Depends()``를 통해 제공한다.
"""
from typing import Any, Optional

from fastapi import Request

from app.exceptions import AuthorizationError
from app.services.cost import cost_service
from app.services.email import email_service
from app.services.entra_id import entra_id_service
from app.services.policy import policy_service
from app.services.resource_manager import resource_manager_service
from app.services.role import role_service
from app.services.subscription import subscription_service
from app.services.storage import storage_service


def get_storage_service():
    """StorageService 싱글턴을 반환한다."""
    return storage_service


def get_entra_id_service():
    """EntraIDService 싱글턴을 반환한다."""
    return entra_id_service


def get_resource_manager_service():
    """ResourceManagerService 싱글턴을 반환한다."""
    return resource_manager_service


def get_policy_service():
    """PolicyService 싱글턴을 반환한다."""
    return policy_service


def get_cost_service():
    """CostService 싱글턴을 반환한다."""
    return cost_service


def get_email_service():
    """EmailService 싱글턴을 반환한다."""
    return email_service


def get_role_service():
    """RoleService 싱글턴을 반환한다."""
    return role_service


def get_subscription_service():
    """SubscriptionService 싱글턴을 반환한다."""
    return subscription_service


def get_current_user(request: Request) -> Optional[dict[str, Any]]:
    """JWT 미들웨어가 설정한 현재 인증 사용자를 반환한다.

    Args:
        request: FastAPI 요청 객체.

    Returns:
        인증된 경우 사용자 정보 딕셔너리, 아니면 None.
    """
    return getattr(request.state, "user", None)


def require_admin(request: Request) -> dict[str, Any]:
    """현재 사용자가 Admin 역할인지 검증한다.

    Admin 전용 엔드포인트의 의존성으로 사용한다.

    Args:
        request: FastAPI 요청 객체.

    Returns:
        Admin 사용자 정보 딕셔너리.

    Raises:
        AuthorizationError: 사용자가 Admin이 아닌 경우.
    """
    user = getattr(request.state, "user", None)
    if not user:
        raise AuthorizationError("Authentication required")

    if user.get("role") != "admin":
        raise AuthorizationError(
            "Admin privileges required to access this resource"
        )
    return user
