"""JWT Bearer 토큰 인증 미들웨어 (PKCE Flow)."""
import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.services.jwt_validator import jwt_service
from app.services.role import role_service

logger = logging.getLogger(__name__)

PUBLIC_PATH_PREFIXES = (
    "/health",
    "/static",
    "/assets",
    "/favicon.ico",
    "/vite.svg",
    "/docs",
    "/openapi.json",
    "/redoc",
)


class AuthMiddleware(BaseHTTPMiddleware):
    """API 라우트에 JWT Bearer 토큰 인증을 적용하는 미들웨어.

    프론트엔드는 MSAL (PKCE flow)을 통해 인증을 수행한다.
    인증 성공 후 Table Storage에서 사용자 역할을 조회하여 부여한다.
    """

    async def dispatch(self, request: Request, call_next):
        """요청을 가로채어 인증을 검증한다."""
        path = request.url.path

        if self._is_public_path(path) or not path.startswith("/api/"):
            return await call_next(request)

        auth_header = request.headers.get("Authorization")

        if not auth_header or not auth_header.startswith("Bearer "):
            logger.info("Missing or invalid Authorization header for %s", path)
            return JSONResponse(
                status_code=401,
                content={"detail": "Not authenticated"},
            )

        token = auth_header.split(" ", 1)[1]
        claims = await jwt_service.validate_token(token)

        if not claims:
            logger.warning("Invalid token for %s", path)
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired token"},
            )

        user_info = jwt_service.get_user_info_from_claims(claims)

        if not jwt_service.validate_user_domain(user_info.get("email")):
            logger.warning(
                "User %s domain not allowed", user_info.get("email")
            )
            return JSONResponse(
                status_code=403,
                content={"detail": "Access denied: Your domain is not authorized"},
            )

        # Table Storage 기반 접근 제어 + 역할 조회 (화이트리스트 통합)
        try:
            role = await role_service.get_or_assign_role(user_info)
        except Exception as e:
            logger.error("Failed to resolve user role: %s", e)
            role = None

        if not role:
            logger.warning(
                "User %s is not registered in the portal",
                user_info.get("email"),
            )
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "Access denied: You are not authorized to use this portal"
                },
            )

        user_info["role"] = role

        request.state.user = user_info
        request.state.token_claims = claims

        return await call_next(request)

    @staticmethod
    def _is_public_path(path: str) -> bool:
        """경로가 공개 경로 목록에 포함되는지 확인한다."""
        return any(path.startswith(prefix) for prefix in PUBLIC_PATH_PREFIXES)
