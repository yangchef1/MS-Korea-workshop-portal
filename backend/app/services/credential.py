"""Azure 인증 정보 헬퍼.

모든 Azure 서비스에 대한 통합된 Credential 관리를 제공한다.
Service Principal 환경변수가 설정되면 ClientSecretCredential을 사용하고,
그렇지 않으면 다음 순서로 자동 처리한다:
- 로컬 개발: Azure CLI credential (``az login``)
- 프로덕션: App Service/Container에 할당된 Managed Identity
"""
import logging

from azure.identity import (
    AzureCliCredential,
    ClientSecretCredential,
    DefaultAzureCredential,
)

from app.config import settings

logger = logging.getLogger(__name__)


def _has_sp_config() -> bool:
    """Service Principal 환경변수가 모두 설정되어 있는지 확인한다."""
    return bool(
        settings.azure_sp_tenant_id
        and settings.azure_sp_client_id
        and settings.azure_sp_client_secret
    )


def get_azure_credential() -> ClientSecretCredential | DefaultAzureCredential | AzureCliCredential:
    """호출 시마다 새 Azure credential 인스턴스를 생성한다.

    우선순위:
    1. Service Principal 환경변수 설정 시 → ClientSecretCredential
    2. USE_AZURE_CLI_CREDENTIAL=true 시 → AzureCliCredential
    3. 그 외 → DefaultAzureCredential (Managed Identity 등)

    Returns:
        Azure credential 객체.

    Raises:
        Exception: credential 생성 실패 시.
    """
    try:
        if _has_sp_config():
            logger.debug("Using ClientSecretCredential (Service Principal)")
            return ClientSecretCredential(
                tenant_id=settings.azure_sp_tenant_id,
                client_id=settings.azure_sp_client_id,
                client_secret=settings.azure_sp_client_secret,
            )

        if settings.use_azure_cli_credential:
            logger.debug("Using AzureCliCredential (local development mode)")
            return AzureCliCredential()

        logger.debug("Using DefaultAzureCredential")
        return DefaultAzureCredential(
            exclude_shared_token_cache_credential=True,
            exclude_visual_studio_code_credential=True,
            exclude_azure_powershell_credential=True,
            exclude_interactive_browser_credential=True,
        )
    except Exception as e:
        logger.error("Failed to create Azure credential: %s", e)
        raise
