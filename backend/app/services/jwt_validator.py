"""Azure AD JWT 토큰 검증 서비스 (PKCE Flow).

Azure AD가 발급한 access token을 client secret 없이 검증한다.
"""
import logging
import time
from typing import Any, Optional

import httpx
from jose import jwt, JWTError
from jose.exceptions import ExpiredSignatureError

from app.config import settings

logger = logging.getLogger(__name__)

# JWKS 키 회전에 대비하여 재시도 1회 허용
_MAX_KEY_FETCH_RETRIES = 1
_JWT_ALGORITHM = "RS256"
_ALLOWED_DOMAINS = frozenset({"microsoft.com"})
# JWKS 캐시 TTL: 보안을 위해 주기적으로 갱신한다
_JWKS_CACHE_TTL = 86400  # 24시간


class JWTValidationService:
    """Azure AD JWT 토큰 검증 서비스 (Single tenant - Microsoft)."""

    def __init__(self) -> None:
        self.client_id = settings.azure_client_id
        self.tenant_id = settings.azure_tenant_id
        self.authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        self.jwks_uri = f"{self.authority}/discovery/v2.0/keys"
        self.issuer = f"https://login.microsoftonline.com/{self.tenant_id}/v2.0"
        self._jwks_cache: Optional[dict] = None
        self._jwks_cache_time: float = 0

    # ------------------------------------------------------------------
    # JWKS fetching
    # ------------------------------------------------------------------

    async def _get_jwks(self, force_refresh: bool = False) -> dict:
        """Azure AD에서 JSON Web Key Set을 조회한다.

        TTL 기반 캐시를 사용하여 키 로테이션 시에도 주기적으로 갱신한다.

        Args:
            force_refresh: 캐시를 무시하고 새로 조회할지 여부.

        Returns:
            JWKS 딕셔너리.
        """
        cache_expired = (time.monotonic() - self._jwks_cache_time) >= _JWKS_CACHE_TTL
        if self._jwks_cache is None or force_refresh or cache_expired:
            async with httpx.AsyncClient() as client:
                response = await client.get(self.jwks_uri)
                response.raise_for_status()
                self._jwks_cache = response.json()
                self._jwks_cache_time = time.monotonic()
        return self._jwks_cache

    def _get_jwks_sync(self, force_refresh: bool = False) -> dict:
        """Azure AD에서 JSON Web Key Set을 동기적으로 조회한다.

        TTL 기반 캐시를 사용하여 키 로테이션 시에도 주기적으로 갱신한다.

        Args:
            force_refresh: 캐시를 무시하고 새로 조회할지 여부.

        Returns:
            JWKS 딕셔너리.
        """
        cache_expired = (time.monotonic() - self._jwks_cache_time) >= _JWKS_CACHE_TTL
        if self._jwks_cache is None or force_refresh or cache_expired:
            with httpx.Client() as client:
                response = client.get(self.jwks_uri)
                response.raise_for_status()
                self._jwks_cache = response.json()
                self._jwks_cache_time = time.monotonic()
        return self._jwks_cache

    @staticmethod
    def _find_key(kid: str, jwks: dict) -> Optional[dict]:
        """JWT 헤더의 kid와 일치하는 키를 찾는다."""
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                return key
        return None

    # ------------------------------------------------------------------
    # Token validation (core logic)
    # ------------------------------------------------------------------

    def _decode_token(self, token: str, key: dict) -> dict[str, Any]:
        """JWT를 디코딩하고 클레임을 반환한다."""
        return jwt.decode(
            token,
            key,
            algorithms=[_JWT_ALGORITHM],
            audience=self.client_id,
            issuer=self.issuer,
            options={
                "verify_aud": True,
                "verify_iss": True,
                "verify_exp": True,
            },
        )

    async def validate_token(self, token: str) -> Optional[dict[str, Any]]:
        """Azure AD access token을 검증한다.

        Args:
            token: Azure AD의 JWT access token.

        Returns:
            유효한 경우 토큰 클레임, 그렇지 않으면 None.
        """
        try:
            unverified_header = jwt.get_unverified_header(token)
            kid = unverified_header.get("kid")

            if not kid:
                logger.warning("Token missing key ID (kid)")
                return None

            # 키 조회 후 없으면 캐시 갱신 후 재시도
            jwks = await self._get_jwks()
            key = self._find_key(kid, jwks)

            if not key:
                jwks = await self._get_jwks(force_refresh=True)
                key = self._find_key(kid, jwks)
                if not key:
                    logger.warning("Signing key not found for kid: %s", kid)
                    return None

            claims = self._decode_token(token, key)
            logger.debug(
                "Token validated for user: %s",
                claims.get("preferred_username"),
            )
            return claims

        except ExpiredSignatureError:
            logger.warning("Token has expired")
            return None
        except JWTError as e:
            logger.warning("JWT validation error: %s", e)
            return None
        except Exception as e:
            logger.error("Unexpected error validating token: %s", e)
            return None

    def validate_token_sync(self, token: str) -> Optional[dict[str, Any]]:
        """Azure AD access token을 동기적으로 검증한다.

        Args:
            token: Azure AD의 JWT access token.

        Returns:
            유효한 경우 토큰 클레임, 그렇지 않으면 None.
        """
        try:
            unverified_header = jwt.get_unverified_header(token)
            kid = unverified_header.get("kid")

            if not kid:
                logger.warning("Token missing key ID (kid)")
                return None

            jwks = self._get_jwks_sync()
            key = self._find_key(kid, jwks)

            if not key:
                jwks = self._get_jwks_sync(force_refresh=True)
                key = self._find_key(kid, jwks)
                if not key:
                    logger.warning("Signing key not found for kid: %s", kid)
                    return None

            claims = self._decode_token(token, key)
            logger.debug(
                "Token validated for user: %s",
                claims.get("preferred_username"),
            )
            return claims

        except ExpiredSignatureError:
            logger.warning("Token has expired")
            return None
        except JWTError as e:
            logger.warning("JWT validation error: %s", e)
            return None
        except Exception as e:
            logger.error("Unexpected error validating token: %s", e)
            return None

    # ------------------------------------------------------------------
    # Claim helpers
    # ------------------------------------------------------------------

    @staticmethod
    def get_user_info_from_claims(claims: dict[str, Any]) -> dict[str, Any]:
        """JWT 클레임에서 사용자 정보를 추출한다.

        Args:
            claims: 검증된 JWT 클레임.

        Returns:
            사용자 정보 딕셔너리.
        """
        return {
            "user_id": claims.get("oid") or claims.get("sub"),
            "name": claims.get("name", ""),
            "email": (
                claims.get("preferred_username")
                or claims.get("email")
                or claims.get("upn")
            ),
            "tenant_id": claims.get("tid"),
        }

    @staticmethod
    def validate_user_domain(email: str) -> bool:
        """사용자 이메일 도메인이 허용 목록에 있는지 검증한다.

        Args:
            email: 사용자 이메일 주소.

        Returns:
            허용된 도메인이면 True.
        """
        if not email:
            return False
        domain = email.split("@")[-1].lower()
        return domain in _ALLOWED_DOMAINS


jwt_service = JWTValidationService()
