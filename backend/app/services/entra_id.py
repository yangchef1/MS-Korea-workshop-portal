"""Microsoft Entra ID 사용자 관리 서비스.

Authentication: DefaultAzureCredential (OIDC/Managed Identity)
"""
import asyncio
import logging
from functools import lru_cache
from typing import Optional

from msgraph import GraphServiceClient
from msgraph.generated.models.password_profile import PasswordProfile
from msgraph.generated.models.user import User

from app.config import settings
from app.exceptions import (
    EntraIDAuthorizationError,
    UserCreationError,
    UserDeletionError,
    UserNotFoundError,
)
from app.services.credential import get_azure_credential
from app.utils.password_generator import generate_password

logger = logging.getLogger(__name__)

# MS Graph 에러 코드 상수
_ERROR_CODE_AUTHORIZATION_DENIED = "Authorization_RequestDenied"
_ERROR_CODE_RESOURCE_NOT_FOUND = "Request_ResourceNotFound"
_HTTP_FORBIDDEN = 403
_HTTP_NOT_FOUND = 404

# Entra ID 사용자 기본 설정
_DEFAULT_USAGE_LOCATION = "KR"
_GRAPH_SCOPE = "https://graph.microsoft.com/.default"


class EntraIDService:
    """Microsoft Entra ID 사용자를 관리하는 서비스."""

    def __init__(self) -> None:
        """Microsoft Graph 클라이언트를 초기화한다."""
        try:
            credential = get_azure_credential()
            self.client = GraphServiceClient(
                credentials=credential,
                scopes=[_GRAPH_SCOPE],
            )
            logger.info("Initialized Entra ID service")
        except Exception as e:
            logger.error("Failed to initialize Entra ID client: %s", e)
            raise

    @staticmethod
    def _extract_graph_error(exc: Exception) -> tuple[Optional[str], Optional[int]]:
        """MS Graph SDK 예외에서 에러 코드와 HTTP 상태를 추출한다.

        Args:
            exc: MS Graph SDK 예외.

        Returns:
            (error_code, response_status_code) 튜플.
        """
        error_code = getattr(getattr(exc, "error", None), "code", None)
        response_code = getattr(exc, "response_status_code", None)
        return error_code, response_code

    @staticmethod
    def _is_authorization_error(
        error_code: Optional[str],
        response_code: Optional[int],
        error_str: str,
    ) -> bool:
        """권한 거부 에러인지 판별한다."""
        return (
            error_code == _ERROR_CODE_AUTHORIZATION_DENIED
            or response_code == _HTTP_FORBIDDEN
            or f"Code: {_HTTP_FORBIDDEN}" in error_str
            or "Insufficient privileges" in error_str
        )

    async def create_user(self, alias: str, password: Optional[str] = None) -> dict:
        """새 Entra ID 사용자를 생성한다.

        Args:
            alias: 사용자 alias (UPN의 username 파트).
            password: 임시 비밀번호 (미지정 시 자동 생성).

        Returns:
            사용자 정보 딕셔너리 (object_id, upn, alias, password).

        Raises:
            EntraIDAuthorizationError: Graph API 권한이 부족한 경우.
            UserCreationError: 사용자 생성에 실패한 경우.
        """
        if not password:
            password = generate_password(settings.password_length)

        upn = f"{alias}@{settings.azure_sp_domain}"
        display_name = f"Workshop User {alias}"

        try:
            user = User(
                account_enabled=True,
                display_name=display_name,
                mail_nickname=alias,
                user_principal_name=upn,
                password_profile=PasswordProfile(
                    force_change_password_next_sign_in=True,
                    password=password,
                ),
                usage_location=_DEFAULT_USAGE_LOCATION,
            )
            created_user = await self.client.users.post(user)

            logger.info("Created Entra ID user: %s", upn)
            return {
                "object_id": created_user.id,
                "upn": upn,
                "alias": alias,
                "password": password,
                "display_name": display_name,
            }
        except Exception as e:
            logger.error("Failed to create user %s: %s", alias, e)
            error_code, response_code = self._extract_graph_error(e)

            if self._is_authorization_error(error_code, response_code, str(e)):
                raise EntraIDAuthorizationError(
                    f"사용자 '{alias}' 생성 권한이 없습니다. "
                    "애플리케이션에 User.ReadWrite.All 또는 "
                    "Directory.ReadWrite.All 권한이 필요합니다."
                )

            raise UserCreationError(
                f"사용자 '{alias}' 생성 실패: {e}",
                user_alias=alias,
            )

    async def create_users_bulk(self, aliases: list[str]) -> list[dict]:
        """여러 Entra ID 사용자를 동시에 생성한다.

        Args:
            aliases: 사용자 alias 목록.

        Returns:
            성공적으로 생성된 사용자 정보 딕셔너리 리스트.
        """
        tasks = [self.create_user(alias) for alias in aliases]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        users = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error("Failed to create user %s: %s", aliases[i], result)
            else:
                users.append(result)

        return users

    async def delete_user(self, user_principal_name: str) -> bool:
        """Entra ID 사용자를 삭제한다.

        Args:
            user_principal_name: 사용자 UPN.

        Returns:
            성공 시 True.

        Raises:
            UserNotFoundError: 사용자를 찾을 수 없는 경우.
            EntraIDAuthorizationError: 삭제 권한이 없는 경우.
            UserDeletionError: 삭제에 실패한 경우.
        """
        try:
            user = await self.client.users.by_user_id(user_principal_name).get()
            if not user:
                return False

            await self.client.users.by_user_id(user.id).delete()
            logger.info("Deleted Entra ID user: %s", user_principal_name)
            return True
        except Exception as e:
            logger.error("Failed to delete user %s: %s", user_principal_name, e)
            error_code, _ = self._extract_graph_error(e)

            if (
                error_code == _ERROR_CODE_RESOURCE_NOT_FOUND
                or str(_HTTP_NOT_FOUND) in str(e)
            ):
                raise UserNotFoundError(
                    f"User '{user_principal_name}' not found",
                    user_id=user_principal_name,
                )

            if (
                error_code == _ERROR_CODE_AUTHORIZATION_DENIED
                or str(_HTTP_FORBIDDEN) in str(e)
            ):
                raise EntraIDAuthorizationError(
                    f"Insufficient permissions to delete user "
                    f"'{user_principal_name}'. "
                    "Ensure the application has User.ReadWrite.All permission."
                )

            raise UserDeletionError(
                f"Failed to delete user '{user_principal_name}': {e}",
                user_id=user_principal_name,
            )

    async def delete_users_bulk(
        self, user_principal_names: list[str]
    ) -> dict[str, bool]:
        """여러 Entra ID 사용자를 동시에 삭제한다.

        Args:
            user_principal_names: UPN 목록.

        Returns:
            UPN을 키로, 삭제 성공 여부를 값으로 가진 딕셔너리.
        """
        tasks = [self.delete_user(upn) for upn in user_principal_names]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        status = {}
        for i, result in enumerate(results):
            upn = user_principal_names[i]
            if isinstance(result, Exception):
                logger.error("Failed to delete user %s: %s", upn, result)
                status[upn] = False
            else:
                status[upn] = result

        return status

    async def get_user(self, user_principal_name: str) -> Optional[dict]:
        """사용자 정보를 조회한다.

        Args:
            user_principal_name: 사용자 UPN.

        Returns:
            사용자 정보 딕셔너리 또는 찾지 못한 경우 None.
        """
        try:
            user = await self.client.users.by_user_id(user_principal_name).get()
            if not user:
                return None

            return {
                "object_id": user.id,
                "upn": user.user_principal_name,
                "display_name": user.display_name,
                "account_enabled": user.account_enabled,
            }
        except Exception:
            logger.warning("User not found: %s", user_principal_name)
            return None


@lru_cache(maxsize=1)
def get_entra_id_service() -> EntraIDService:
    """Get the EntraIDService singleton instance."""
    return EntraIDService()


entra_id_service = get_entra_id_service()
