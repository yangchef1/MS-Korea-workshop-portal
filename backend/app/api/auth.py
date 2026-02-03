"""
Authentication API routes (PKCE Flow - JWT Bearer Token)
"""
from fastapi import APIRouter, Request, HTTPException

from app.core.deps import get_current_user

router = APIRouter(prefix="/auth")


@router.get("/me")
async def get_current_user_info(request: Request):
    """Get current authenticated user info from JWT token"""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
