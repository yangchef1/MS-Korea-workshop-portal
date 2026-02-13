"""포털 사용자 역할 관리 서비스.

허용된 사용자 목록과 역할을 Table Storage에서 관리한다.
"""
import logging
from datetime import UTC, datetime
from typing import Any, Optional

from app.exceptions import NotFoundError
from app.models import UserRole, UserStatus

logger = logging.getLogger(__name__)


class RoleService:
    """포털 사용자 역할을 관리하는 서비스.

    허용된 사용자 목록과 역할을 Table Storage에서 관리한다.

    Attributes:
        _storage: StorageService 인스턴스 (lazy-loaded).
    """

    def __init__(self) -> None:
        self._storage = None

    @property
    def storage(self):
        """StorageService 싱글턴을 lazy-load한다."""
        if self._storage is None:
            from app.services.storage import storage_service

            self._storage = storage_service
        return self._storage

    async def get_or_assign_role(
        self, user_info: dict[str, Any]
    ) -> Optional[str]:
        """사용자의 역할을 Table Storage에서 조회한다.

        등록된 사용자는 저장된 역할을 반환하고,
        미등록 사용자는 None을 반환하여 접근을 거부한다.
        최초 로그인 시 JWT에서 가져온 이름과 user_id를 보충 저장한다.

        Args:
            user_info: JWT에서 추출한 사용자 정보 (user_id, name, email).

        Returns:
            사용자 역할 문자열 ("admin" 또는 "user"), 미등록 시 None.
        """
        email = (user_info.get("email") or "").strip().lower()
        if not email:
            return None

        stored_user = await self.storage.get_portal_user(email)
        if not stored_user:
            return None

        # 최초 로그인 시 JWT에서 가져온 이름·OID를 보충 저장
        needs_update = False
        if not stored_user.get("user_id") and user_info.get("user_id"):
            stored_user["user_id"] = user_info["user_id"]
            needs_update = True
        if not stored_user.get("name") and user_info.get("name"):
            stored_user["name"] = user_info["name"]
            needs_update = True

        # 미활성 사용자가 처음 로그인하면 active로 전환
        if stored_user.get("status") in (
            UserStatus.INVITED.value,
            UserStatus.PENDING.value,
        ):
            stored_user["status"] = UserStatus.ACTIVE.value
            needs_update = True
            logger.info("Activated user: %s", email)

        if needs_update:
            try:
                await self.storage.save_portal_user(stored_user)
            except Exception as e:
                logger.error("Failed to update user profile: %s", e)

        return stored_user.get("role", UserRole.USER.value)

    async def add_user(
        self, email: str, role: str = "user", name: str = ""
    ) -> dict[str, Any]:
        """포털 접근 허용 사용자를 추가한다.

        Args:
            email: 사용자 이메일.
            role: 역할 ("admin" 또는 "user").
            name: 사용자 이름 (선택).

        Returns:
            저장된 사용자 정보.
        """
        user_data = {
            "user_id": "",
            "name": name,
            "email": email.strip().lower(),
            "role": role,
            "status": UserStatus.PENDING.value,
            "registered_at": datetime.now(UTC).isoformat(),
        }
        await self.storage.save_portal_user(user_data)
        logger.info("Added portal user: %s (role: %s)", email, role)
        return user_data

    async def remove_user(self, email: str) -> None:
        """포털 접근 허용 사용자를 제거한다.

        Args:
            email: 제거할 사용자 이메일.

        Raises:
            NotFoundError: 사용자를 찾을 수 없는 경우.
        """
        normalized = email.strip().lower()
        stored_user = await self.storage.get_portal_user(normalized)
        if not stored_user:
            raise NotFoundError(
                f"Portal user '{email}' not found",
                resource_type="PortalUser",
            )
        await self.storage.delete_portal_user(normalized)
        logger.info("Removed portal user: %s", email)

    async def get_all_users(self) -> list[dict[str, Any]]:
        """모든 포털 사용자를 조회한다."""
        return await self.storage.list_portal_users()

    async def update_user_role(
        self, email: str, new_role: str
    ) -> dict[str, Any]:
        """사용자의 역할을 변경한다.

        Args:
            email: 대상 사용자 이메일.
            new_role: 새 역할 ("admin" 또는 "user").

        Returns:
            업데이트된 사용자 정보.

        Raises:
            NotFoundError: 사용자를 찾을 수 없는 경우.
        """
        normalized = email.strip().lower()
        stored_user = await self.storage.get_portal_user(normalized)
        if not stored_user:
            raise NotFoundError(
                f"Portal user '{email}' not found",
                resource_type="PortalUser",
            )

        stored_user["role"] = new_role
        await self.storage.save_portal_user(stored_user)
        logger.info("Updated role for user %s to %s", email, new_role)
        return stored_user


role_service = RoleService()
