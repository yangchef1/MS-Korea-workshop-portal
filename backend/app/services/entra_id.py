"""Microsoft Entra ID 사용자 관리 서비스.

Authentication: DefaultAzureCredential (OIDC/Managed Identity)
"""
import asyncio
import logging
from functools import lru_cache
from typing import Optional

# Entra ID replication delay can cause 404 when deleting a just-created user.
# Retry with exponential backoff to handle eventual consistency.
_DELETE_MAX_RETRIES = 3
_DELETE_INITIAL_DELAY_SECONDS = 2.0

from msgraph import GraphServiceClient
from msgraph.generated.models.password_profile import PasswordProfile
from msgraph.generated.models.reference_create import ReferenceCreate
from msgraph.generated.models.user import User

from app.config import settings
from app.exceptions import (
    EntraIDAuthorizationError,
    GroupMembershipError,
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
_HTTP_CONFLICT = 409

# MS Graph directory object base URL
_GRAPH_DIRECTORY_OBJECTS_URL = "https://graph.microsoft.com/v1.0/directoryObjects"

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

    async def create_user(
        self,
        alias: str,
        password: Optional[str] = None,
        account_enabled: bool = True,
    ) -> dict:
        """새 Entra ID 사용자를 생성한다.

        Args:
            alias: 사용자 alias (UPN의 username 파트).
            password: 임시 비밀번호 (미지정 시 자동 생성).
            account_enabled: 계정 활성화 여부. False면 비활성 상태로 생성.

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
                account_enabled=account_enabled,
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

    async def create_users_bulk(
        self,
        aliases: list[str],
        account_enabled: bool = True,
    ) -> list[dict]:
        """여러 Entra ID 사용자를 동시에 생성한다.

        Args:
            aliases: 사용자 alias 목록.
            account_enabled: 계정 활성화 여부. False면 비활성 상태로 생성.

        Returns:
            성공적으로 생성된 사용자 정보 딕셔너리 리스트.
        """
        tasks = [self.create_user(alias, account_enabled=account_enabled) for alias in aliases]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        users = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error("Failed to create user %s: %s", aliases[i], result)
            else:
                users.append(result)

        return users

    async def delete_user(
        self,
        user_principal_name: str,
        object_id: Optional[str] = None,
    ) -> bool:
        """Entra ID 사용자를 삭제한다.

        object_id가 제공되면 UPN 조회를 건너뛰고 바로 삭제한다.
        Entra ID 복제 지연으로 인한 404에 대비해 재시도 로직을 포함한다.

        Args:
            user_principal_name: 사용자 UPN (로깅/식별용).
            object_id: 사용자 Object ID. 제공 시 UPN 조회를 생략한다.

        Returns:
            성공 시 True.

        Raises:
            UserNotFoundError: 재시도 후에도 사용자를 찾을 수 없는 경우.
            EntraIDAuthorizationError: 삭제 권한이 없는 경우.
            UserDeletionError: 삭제에 실패한 경우.
        """
        last_exception: Optional[Exception] = None

        for attempt in range(_DELETE_MAX_RETRIES):
            try:
                if object_id:
                    # object_id가 있으면 GET 조회 없이 바로 삭제
                    await self.client.users.by_user_id(object_id).delete()
                else:
                    # object_id가 없으면 UPN으로 조회 후 삭제
                    user = await self.client.users.by_user_id(
                        user_principal_name,
                    ).get()
                    if not user:
                        return False
                    await self.client.users.by_user_id(user.id).delete()

                logger.info("Deleted Entra ID user: %s", user_principal_name)
                return True

            except Exception as e:
                error_code, _ = self._extract_graph_error(e)

                # 권한 에러는 재시도해도 소용없으므로 즉시 raise
                if self._is_authorization_error(error_code, None, str(e)):
                    logger.error(
                        "Failed to delete user %s: %s", user_principal_name, e,
                    )
                    raise EntraIDAuthorizationError(
                        f"Insufficient permissions to delete user "
                        f"'{user_principal_name}'. "
                        "Ensure the application has User.ReadWrite.All permission."
                    )

                # 404 (복제 지연 가능) → 재시도
                is_not_found = (
                    error_code == _ERROR_CODE_RESOURCE_NOT_FOUND
                    or str(_HTTP_NOT_FOUND) in str(e)
                )
                if is_not_found and attempt < _DELETE_MAX_RETRIES - 1:
                    delay = _DELETE_INITIAL_DELAY_SECONDS * (2 ** attempt)
                    logger.warning(
                        "User %s not found (attempt %d/%d), "
                        "retrying in %.1fs (replication delay)",
                        user_principal_name,
                        attempt + 1,
                        _DELETE_MAX_RETRIES,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    last_exception = e
                    continue

                # 최종 404 → 이미 삭제된 것으로 간주 (idempotent)
                if is_not_found:
                    logger.warning(
                        "User %s not found after %d retries; "
                        "treating as already deleted",
                        user_principal_name,
                        _DELETE_MAX_RETRIES,
                    )
                    return True

                # 기타 에러
                logger.error(
                    "Failed to delete user %s: %s", user_principal_name, e,
                )
                raise UserDeletionError(
                    f"Failed to delete user '{user_principal_name}': {e}",
                    user_id=user_principal_name,
                )

        # _DELETE_MAX_RETRIES 모두 소진 (이론적으로 도달하지 않음)
        raise UserDeletionError(
            f"Failed to delete user '{user_principal_name}' "
            f"after {_DELETE_MAX_RETRIES} retries: {last_exception}",
            user_id=user_principal_name,
        )

    async def delete_users_bulk(
        self,
        user_principal_names: list[str],
        upn_to_object_id: Optional[dict[str, str]] = None,
    ) -> dict[str, bool]:
        """여러 Entra ID 사용자를 동시에 삭제한다.

        Args:
            user_principal_names: UPN 목록.
            upn_to_object_id: UPN → Object ID 매핑. 제공 시 UPN 조회를 생략하고
                Object ID로 직접 삭제하여 Entra ID 복제 지연 문제를 회피한다.

        Returns:
            UPN을 키로, 삭제 성공 여부를 값으로 가진 딕셔너리.
        """
        id_map = upn_to_object_id or {}
        tasks = [
            self.delete_user(upn, object_id=id_map.get(upn))
            for upn in user_principal_names
        ]
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

    async def enable_user(self, user_id: str) -> bool:
        """비활성 Entra ID 사용자를 활성화한다.

        Args:
            user_id: 사용자 Object ID 또는 UPN.

        Returns:
            성공 시 True.

        Raises:
            EntraIDAuthorizationError: 권한이 부족한 경우.
            UserCreationError: 사용자 업데이트에 실패한 경우.
        """
        try:
            await self.client.users.by_user_id(user_id).patch(
                User(account_enabled=True)
            )
            logger.info("Enabled Entra ID user: %s", user_id)
            return True
        except Exception as e:
            error_code, response_code = self._extract_graph_error(e)
            if self._is_authorization_error(error_code, response_code, str(e)):
                raise EntraIDAuthorizationError(
                    f"사용자 '{user_id}' 활성화 권한이 없습니다."
                )
            logger.error("Failed to enable user %s: %s", user_id, e)
            raise UserCreationError(
                f"사용자 '{user_id}' 활성화 실패: {e}",
                user_alias=user_id,
            )

    async def enable_users_bulk(self, user_ids: list[str]) -> list[str]:
        """여러 Entra ID 사용자를 동시에 활성화한다.

        Args:
            user_ids: Object ID 또는 UPN 목록.

        Returns:
            성공적으로 활성화된 user_id 리스트.
        """
        tasks = [self.enable_user(uid) for uid in user_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        enabled = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "Failed to enable user %s: %s", user_ids[i], result,
                )
            else:
                enabled.append(user_ids[i])

        return enabled

    async def add_user_to_group(
        self,
        user_object_id: str,
        group_id: str,
    ) -> bool:
        """Entra ID 보안 그룹에 사용자를 추가한다.

        이미 그룹에 속한 사용자를 다시 추가하면 멱등하게 True를 반환한다.

        Args:
            user_object_id: 사용자 Object ID.
            group_id: 대상 보안 그룹 Object ID.

        Returns:
            성공 시 True.

        Raises:
            EntraIDAuthorizationError: 그룹 관리 권한이 부족한 경우.
            GroupMembershipError: 그룹 멤버 추가에 실패한 경우.
        """
        try:
            request_body = ReferenceCreate(
                odata_id=f"{_GRAPH_DIRECTORY_OBJECTS_URL}/{user_object_id}",
            )
            await self.client.groups.by_group_id(group_id).members.ref.post(
                request_body,
            )
            logger.info(
                "Added user %s to group %s", user_object_id, group_id,
            )
            return True
        except Exception as e:
            error_code, response_code = self._extract_graph_error(e)

            # Already a member — treat as success (idempotent)
            if response_code == _HTTP_CONFLICT:
                logger.info(
                    "User %s already in group %s, skipping",
                    user_object_id,
                    group_id,
                )
                return True

            if self._is_authorization_error(error_code, response_code, str(e)):
                raise EntraIDAuthorizationError(
                    f"사용자 '{user_object_id}'를 그룹 '{group_id}'에 추가할 권한이 없습니다. "
                    "애플리케이션에 GroupMember.ReadWrite.All 권한이 필요합니다."
                )

            logger.error(
                "Failed to add user %s to group %s: %s",
                user_object_id,
                group_id,
                e,
            )
            raise GroupMembershipError(
                f"사용자 '{user_object_id}'를 그룹 '{group_id}'에 추가 실패: {e}",
                group_id=group_id,
            )

    async def add_users_to_group_bulk(
        self,
        user_object_ids: list[str],
        group_id: str,
    ) -> list[str]:
        """여러 사용자를 Entra ID 보안 그룹에 동시에 추가한다.

        Args:
            user_object_ids: 사용자 Object ID 목록.
            group_id: 대상 보안 그룹 Object ID.

        Returns:
            성공적으로 추가된 user_object_id 리스트.
        """
        tasks = [
            self.add_user_to_group(uid, group_id) for uid in user_object_ids
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        added: list[str] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "Failed to add user %s to group %s: %s",
                    user_object_ids[i],
                    group_id,
                    result,
                )
            else:
                added.append(user_object_ids[i])

        return added

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
