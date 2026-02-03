"""
Authentication middleware for JWT Bearer token validation (PKCE Flow)
"""
import logging
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from app.services.jwt_validator import jwt_service

logger = logging.getLogger(__name__)

PUBLIC_PATHS = [
    "/health",
    "/static",
    "/assets",
    "/favicon.ico",
    "/vite.svg",
    "/docs",
    "/openapi.json",
    "/redoc",
]


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware to enforce JWT Bearer token authentication on API routes
    Frontend handles authentication via MSAL (PKCE flow)
    """
    
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        
        if self._is_public_path(path):
            return await call_next(request)
        
        if not path.startswith("/api/"):
            return await call_next(request)
        
        auth_header = request.headers.get("Authorization")
        
        if not auth_header or not auth_header.startswith("Bearer "):
            logger.info(f"Missing or invalid Authorization header for {path}")
            return JSONResponse(
                status_code=401,
                content={"detail": "Not authenticated"}
            )
        
        token = auth_header.split(" ", 1)[1]
        
        claims = await jwt_service.validate_token(token)
        
        if not claims:
            logger.warning(f"Invalid token for {path}")
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired token"}
            )
        
        user_info = jwt_service.get_user_info_from_claims(claims)
        
        if not jwt_service.validate_user_domain(user_info.get("email")):
            logger.warning(f"User {user_info.get('email')} domain not allowed")
            return JSONResponse(
                status_code=403,
                content={"detail": "Access denied: Your domain is not authorized"}
            )
        
        request.state.user = user_info
        request.state.token_claims = claims
        
        response = await call_next(request)
        return response
    
    def _is_public_path(self, path: str) -> bool:
        """Check if path is in public paths list"""
        for public_path in PUBLIC_PATHS:
            if path.startswith(public_path):
                return True
        return False
