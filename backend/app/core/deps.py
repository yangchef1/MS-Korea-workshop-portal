"""
FastAPI dependencies for dependency injection
"""
from typing import Any, Dict, Optional

from fastapi import Request
from app.services.storage import storage_service
from app.services.entra_id import entra_id_service
from app.services.resource_manager import resource_manager_service
from app.services.policy import policy_service
from app.services.cost import cost_service
from app.services.email import email_service


def get_storage_service():
    """Get storage service instance"""
    return storage_service


def get_entra_id_service():
    """Get Entra ID service instance"""
    return entra_id_service


def get_resource_manager_service():
    """Get Resource Manager service instance"""
    return resource_manager_service


def get_policy_service():
    """Get Policy service instance"""
    return policy_service


def get_cost_service():
    """Get Cost Management service instance"""
    return cost_service


def get_email_service():
    """Get Email service instance"""
    return email_service


def get_current_user(request: Request) -> Optional[Dict[str, Any]]:
    """
    Get current authenticated user from request state (set by JWT middleware)
    Returns None if not authenticated
    """
    return getattr(request.state, "user", None)
