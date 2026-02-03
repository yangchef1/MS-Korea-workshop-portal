"""
JWT Token Validation Service for Azure AD (PKCE Flow)
Validates access tokens issued by Azure AD without requiring client secret
"""
import logging
import httpx
from typing import Optional, Dict, Any
from jose import jwt, JWTError
from jose.exceptions import ExpiredSignatureError
from app.config import settings

logger = logging.getLogger(__name__)


class JWTValidationService:
    """Service for validating Azure AD JWT tokens (Single tenant - Microsoft)"""

    def __init__(self):
        self.client_id = settings.azure_client_id
        self.tenant_id = settings.azure_tenant_id
        self.authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        self.jwks_uri = f"{self.authority}/discovery/v2.0/keys"
        self.issuer = f"https://login.microsoftonline.com/{self.tenant_id}/v2.0"
        self._jwks_cache: Optional[Dict] = None

    async def _get_jwks(self) -> Dict:
        """Fetch JSON Web Key Set from Azure AD"""
        if self._jwks_cache is None:
            async with httpx.AsyncClient() as client:
                response = await client.get(self.jwks_uri)
                response.raise_for_status()
                self._jwks_cache = response.json()
        return self._jwks_cache

    def _get_jwks_sync(self) -> Dict:
        """Fetch JSON Web Key Set from Azure AD (synchronous)"""
        if self._jwks_cache is None:
            with httpx.Client() as client:
                response = client.get(self.jwks_uri)
                response.raise_for_status()
                self._jwks_cache = response.json()
        return self._jwks_cache

    def _find_key(self, kid: str, jwks: Dict) -> Optional[Dict]:
        """Find the key matching the key ID in the JWT header"""
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                return key
        return None

    async def validate_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Validate an Azure AD access token
        
        Args:
            token: JWT access token from Azure AD
            
        Returns:
            Token claims if valid, None otherwise
        """
        try:
            unverified_header = jwt.get_unverified_header(token)
            kid = unverified_header.get("kid")
            
            if not kid:
                logger.warning("Token missing key ID (kid)")
                return None
            
            jwks = await self._get_jwks()
            key = self._find_key(kid, jwks)
            
            if not key:
                self._jwks_cache = None
                jwks = await self._get_jwks()
                key = self._find_key(kid, jwks)
                
                if not key:
                    logger.warning(f"Signing key not found for kid: {kid}")
                    return None
            
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self.client_id,
                issuer=self.issuer,
                options={
                    "verify_aud": True,
                    "verify_iss": True,
                    "verify_exp": True,
                }
            )
            
            logger.debug(f"Token validated for user: {claims.get('preferred_username')}")
            return claims
            
        except ExpiredSignatureError:
            logger.warning("Token has expired")
            return None
        except JWTError as e:
            logger.warning(f"JWT validation error: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error validating token: {e}")
            return None

    def validate_token_sync(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Validate an Azure AD access token (synchronous version)
        
        Args:
            token: JWT access token from Azure AD
            
        Returns:
            Token claims if valid, None otherwise
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
                self._jwks_cache = None
                jwks = self._get_jwks_sync()
                key = self._find_key(kid, jwks)
                
                if not key:
                    logger.warning(f"Signing key not found for kid: {kid}")
                    return None
            
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self.client_id,
                issuer=self.issuer,
                options={
                    "verify_aud": True,
                    "verify_iss": True,
                    "verify_exp": True,
                }
            )
            
            logger.debug(f"Token validated for user: {claims.get('preferred_username')}")
            return claims
            
        except ExpiredSignatureError:
            logger.warning("Token has expired")
            return None
        except JWTError as e:
            logger.warning(f"JWT validation error: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error validating token: {e}")
            return None

    def get_user_info_from_claims(self, claims: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract user information from JWT claims
        
        Args:
            claims: Validated JWT claims
            
        Returns:
            User information dictionary
        """
        return {
            "user_id": claims.get("oid") or claims.get("sub"),
            "name": claims.get("name", ""),
            "email": claims.get("preferred_username") or claims.get("email") or claims.get("upn"),
            "tenant_id": claims.get("tid"),
        }

    def validate_user_domain(self, email: str) -> bool:
        """
        Validate that user's email domain is allowed
        Only microsoft.com employees are allowed
        
        Args:
            email: User's email address
            
        Returns:
            True if domain is allowed, False otherwise
        """
        if not email:
            return False
        
        domain = email.split("@")[-1].lower()
        
        allowed_domains = ["microsoft.com"]
        
        return domain in allowed_domains


jwt_service = JWTValidationService()
