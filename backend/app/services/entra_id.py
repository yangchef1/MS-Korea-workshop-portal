"""Microsoft Entra ID user management service.

Authentication: Uses DefaultAzureCredential (OIDC/Managed Identity)
- Local development: Azure CLI credential (az login)
- Production: Managed Identity assigned to App Service
"""
import logging
from functools import lru_cache
from typing import List, Dict, Optional

from msgraph import GraphServiceClient
from msgraph.generated.models.user import User
from msgraph.generated.models.password_profile import PasswordProfile

from app.config import settings
from app.utils.password_generator import generate_password
from app.services.credential import get_azure_credential
from app.exceptions import (
    EntraIDAuthorizationError,
    UserCreationError,
    UserDeletionError,
    UserNotFoundError,
)

logger = logging.getLogger(__name__)


class EntraIDService:
    """Service for managing Microsoft Entra ID users"""

    def __init__(self):
        """Initialize Microsoft Graph client using Azure Identity."""
        try:
            credential = get_azure_credential()
            scopes = ['https://graph.microsoft.com/.default']
            self.client = GraphServiceClient(credentials=credential, scopes=scopes)
            logger.info("Initialized Entra ID service")
        except Exception as e:
            logger.error("Failed to initialize Entra ID client: %s", e)
            raise

    async def create_user(self, alias: str, password: Optional[str] = None) -> Dict:
        """
        Create a new Entra ID user

        Args:
            alias: User alias (username part of UPN)
            password: Temporary password (generated if not provided)

        Returns:
            Dictionary with user details (object_id, upn, alias, password)
        """
        try:
            if not password:
                password = generate_password(settings.password_length)

            upn = f"{alias}@{settings.azure_domain}"
            display_name = f"Workshop User {alias}"

            password_profile = PasswordProfile(
                force_change_password_next_sign_in=True,
                password=password
            )

            user = User(
                account_enabled=True,
                display_name=display_name,
                mail_nickname=alias,
                user_principal_name=upn,
                password_profile=password_profile,
                usage_location="KR"  # Korea
            )

            created_user = await self.client.users.post(user)

            logger.info("Created Entra ID user: %s", upn)

            return {
                'object_id': created_user.id,
                'upn': upn,
                'alias': alias,
                'password': password,
                'display_name': display_name
            }

        except Exception as e:
            logger.error("Failed to create user %s: %s", alias, e)
            error_str = str(e)
            
            # MS Graph SDK APIError 구조에서 에러 코드 추출
            error_code = None
            response_code = None
            if hasattr(e, 'error') and e.error:
                error_code = getattr(e.error, 'code', None)
            if hasattr(e, 'response_status_code'):
                response_code = e.response_status_code
            
            # 403 권한 오류 처리
            if (error_code == 'Authorization_RequestDenied' or 
                response_code == 403 or 
                'Code: 403' in error_str or
                'Insufficient privileges' in error_str):
                raise EntraIDAuthorizationError(
                    f"사용자 '{alias}' 생성 권한이 없습니다. "
                    "애플리케이션에 User.ReadWrite.All 또는 Directory.ReadWrite.All 권한이 필요합니다."
                )
            
            raise UserCreationError(
                f"사용자 '{alias}' 생성 실패: {error_str}",
                user_alias=alias
            )

    async def create_users_bulk(self, aliases: List[str]) -> List[Dict]:
        """
        Create multiple Entra ID users

        Args:
            aliases: List of user aliases

        Returns:
            List of user detail dictionaries
        """
        import asyncio

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
        """
        Delete an Entra ID user

        Args:
            user_principal_name: User's UPN

        Returns:
            True if successful
        """
        try:
            user = await self.client.users.by_user_id(user_principal_name).get()

            if user:
                await self.client.users.by_user_id(user.id).delete()
                logger.info("Deleted Entra ID user: %s", user_principal_name)
                return True

            return False

        except Exception as e:
            logger.error("Failed to delete user %s: %s", user_principal_name, e)
            error_code = getattr(getattr(e, 'error', None), 'code', None)
            
            if error_code == 'Request_ResourceNotFound' or '404' in str(e):
                raise UserNotFoundError(
                    f"User '{user_principal_name}' not found",
                    user_id=user_principal_name
                )
            
            if error_code == 'Authorization_RequestDenied' or '403' in str(e):
                raise EntraIDAuthorizationError(
                    f"Insufficient permissions to delete user '{user_principal_name}'. "
                    "Ensure the application has User.ReadWrite.All permission."
                )
            
            raise UserDeletionError(
                f"Failed to delete user '{user_principal_name}': {str(e)}",
                user_id=user_principal_name
            )

    async def delete_users_bulk(self, user_principal_names: List[str]) -> Dict[str, bool]:
        """
        Delete multiple Entra ID users

        Args:
            user_principal_names: List of UPNs

        Returns:
            Dictionary mapping UPN to deletion success status
        """
        import asyncio

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

    async def get_user(self, user_principal_name: str) -> Optional[Dict]:
        """
        Get user details

        Args:
            user_principal_name: User's UPN

        Returns:
            User details dictionary or None if not found
        """
        try:
            user = await self.client.users.by_user_id(user_principal_name).get()

            if user:
                return {
                    'object_id': user.id,
                    'upn': user.user_principal_name,
                    'display_name': user.display_name,
                    'account_enabled': user.account_enabled
                }

            return None

        except Exception as e:
            logger.warning("User not found: %s", user_principal_name)
            return None


@lru_cache(maxsize=1)
def get_entra_id_service() -> EntraIDService:
    """Get the EntraIDService singleton instance."""
    return EntraIDService()


entra_id_service = get_entra_id_service()
