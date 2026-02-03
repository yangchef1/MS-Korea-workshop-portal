"""
Azure Credential Helper.

Provides unified credential management for all Azure services.
Uses DefaultAzureCredential which automatically handles:
- Local development: Azure CLI credential (az login)
- Production: Managed Identity assigned to App Service/Container
- GitHub Actions: OIDC token via Federated Credential
"""
import logging
from azure.identity import DefaultAzureCredential, AzureCliCredential

from app.config import settings

logger = logging.getLogger(__name__)


def get_azure_credential():
    """
    Get Azure credential for authenticating to Azure services.
    
    NOTE: This function creates a new credential instance each time.
    DefaultAzureCredential and AzureCliCredential internally handle token
    caching and refresh, so creating new instances is safe and ensures
    fresh credentials after 'az login'.
    
    Uses DefaultAzureCredential which tries the following in order:
    1. Environment variables (AZURE_CLIENT_ID, AZURE_TENANT_ID, etc.)
    2. Managed Identity (when running in Azure)
    3. Azure CLI (when running locally with 'az login')
    4. Visual Studio Code / Azure PowerShell (disabled for consistency)
    
    For local development:
        - Run 'az login' before starting the application
        - Set USE_AZURE_CLI_CREDENTIAL=true in .env to use AzureCliCredential directly
    
    For production (App Service/Container Apps):
        - Enable System-Assigned Managed Identity OR
        - Assign User-Assigned Managed Identity
        - Grant necessary RBAC roles to the identity
    
    Returns:
        Azure credential object
    """
    try:
        if settings.use_azure_cli_credential:
            logger.debug("Using AzureCliCredential for authentication (local development mode)")
            return AzureCliCredential()
        else:
            logger.debug("Using DefaultAzureCredential for authentication")
            return DefaultAzureCredential(
                exclude_shared_token_cache_credential=True,
                exclude_visual_studio_code_credential=True,
                exclude_azure_powershell_credential=True,
                exclude_interactive_browser_credential=True,
            )
        
    except Exception as e:
        logger.error(f"Failed to create Azure credential: {e}")
        raise
