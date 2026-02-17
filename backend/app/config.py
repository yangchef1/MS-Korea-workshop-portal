"""
Configuration settings for Azure Workshop Portal
"""
import os
from typing import List, Dict, Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # MSAL / JWT 검증용 (Microsoft 테넌트)
    azure_tenant_id: str = os.getenv("AZURE_TENANT_ID", "")
    azure_client_id: str = os.getenv("AZURE_CLIENT_ID", "")
    azure_redirect_uri: str = os.getenv("AZURE_REDIRECT_URI", "http://localhost:5173")

    # Service Principal (Azure 리소스 운영 테넌트)
    azure_sp_tenant_id: str = os.getenv("AZURE_SP_TENANT_ID", "")
    azure_sp_client_id: str = os.getenv("AZURE_SP_CLIENT_ID", "")
    azure_sp_client_secret: str = os.getenv("AZURE_SP_CLIENT_SECRET", "")
    azure_sp_domain: str = os.getenv("AZURE_SP_DOMAIN", "yourdomain.com")
    azure_sp_subscription_id: str = os.getenv("AZURE_SP_SUBSCRIPTION_ID", "")

    # Multi-subscription support: comma-separated list of allowed subscription IDs
    allowed_subscription_ids_raw: str = os.getenv("ALLOWED_SUBSCRIPTION_IDS", "")

    # CORS: comma-separated production origins (local origins added automatically)
    allowed_origins: str = os.getenv("ALLOWED_ORIGINS", "")

    session_secret_key: str = os.getenv("SESSION_SECRET_KEY", "change-this-secret-key-in-production")

    table_storage_account: str = os.getenv("TABLE_STORAGE_ACCOUNT", "workshopstorage")

    use_azure_cli_credential: bool = os.getenv("USE_AZURE_CLI_CREDENTIAL", "false").lower() == "true"

    # Email settings (Azure Communication Services or SMTP)
    email_sender: Optional[str] = os.getenv("EMAIL_SENDER", None)
    acs_connection_string: Optional[str] = os.getenv("ACS_CONNECTION_STRING", None)
    smtp_host: Optional[str] = os.getenv("SMTP_HOST", None)
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_username: Optional[str] = os.getenv("SMTP_USERNAME", None)
    smtp_password: Optional[str] = os.getenv("SMTP_PASSWORD", None)

    app_name: str = "Azure Workshop Management Portal"
    app_version: str = "1.0.0"

    default_services: List[str] = [
        "Microsoft.Compute",
        "Microsoft.Network",
        "Microsoft.Storage",
        "Microsoft.KeyVault",
        "Microsoft.ContainerService",
        "Microsoft.Sql"
    ]

    service_resource_types: Dict[str, List[str]] = {
        "Microsoft.Compute": [
            "Microsoft.Compute/virtualMachines",
            "Microsoft.Compute/virtualMachines/extensions",
            "Microsoft.Compute/disks",
            "Microsoft.Compute/snapshots",
            "Microsoft.Compute/images",
            "Microsoft.Compute/availabilitySets",
            "Microsoft.Compute/virtualMachineScaleSets",
            "Microsoft.Compute/proximityPlacementGroups",
        ],
        "Microsoft.Network": [
            "Microsoft.Network/virtualNetworks",
            "Microsoft.Network/virtualNetworks/subnets",
            "Microsoft.Network/networkSecurityGroups",
            "Microsoft.Network/publicIPAddresses",
            "Microsoft.Network/networkInterfaces",
            "Microsoft.Network/loadBalancers",
            "Microsoft.Network/applicationGateways",
            "Microsoft.Network/routeTables",
            "Microsoft.Network/natGateways",
            "Microsoft.Network/bastionHosts",
            "Microsoft.Network/privateDnsZones",
            "Microsoft.Network/privateEndpoints",
        ],
        "Microsoft.Storage": [
            "Microsoft.Storage/storageAccounts",
            "Microsoft.Storage/storageAccounts/blobServices",
            "Microsoft.Storage/storageAccounts/blobServices/containers",
            "Microsoft.Storage/storageAccounts/fileServices",
            "Microsoft.Storage/storageAccounts/queueServices",
            "Microsoft.Storage/storageAccounts/tableServices",
        ],
        "Microsoft.KeyVault": [
            "Microsoft.KeyVault/vaults",
            "Microsoft.KeyVault/vaults/secrets",
            "Microsoft.KeyVault/vaults/keys",
            "Microsoft.KeyVault/managedHSMs",
        ],
        "Microsoft.ContainerService": [
            "Microsoft.ContainerService/managedClusters",
            "Microsoft.ContainerService/containerServices",
        ],
        "Microsoft.Sql": [
            "Microsoft.Sql/servers",
            "Microsoft.Sql/servers/databases",
            "Microsoft.Sql/servers/elasticPools",
            "Microsoft.Sql/servers/firewallRules",
            "Microsoft.Sql/managedInstances",
        ],
        "Microsoft.Web": [
            "Microsoft.Web/sites",
            "Microsoft.Web/serverfarms",
            "Microsoft.Web/certificates",
            "Microsoft.Web/staticSites",
        ],
        "Microsoft.ContainerRegistry": [
            "Microsoft.ContainerRegistry/registries",
        ],
        "Microsoft.DBforMySQL": [
            "Microsoft.DBforMySQL/servers",
            "Microsoft.DBforMySQL/flexibleServers",
        ],
        "Microsoft.DBforPostgreSQL": [
            "Microsoft.DBforPostgreSQL/servers",
            "Microsoft.DBforPostgreSQL/flexibleServers",
        ],
        "Microsoft.DocumentDB": [
            "Microsoft.DocumentDB/databaseAccounts",
        ],
    }

    password_length: int = 16

    default_user_role: str = "Contributor"
    resource_group_prefix: str = "rg-workshop"

    # Logging: "json" for production (Azure Monitor), "text" for development
    log_format: str = "text"
    log_level: str = "INFO"

    # Azure SDK retry
    azure_retry_total: int = 3
    azure_retry_backoff_factor: float = 1.0

    model_config = {"env_file": ".env", "case_sensitive": False, "extra": "ignore"}

    @property
    def allowed_subscription_ids(self) -> list[str]:
        """Parse ALLOWED_SUBSCRIPTION_IDS into a list, falling back to the default SP subscription."""
        parsed = [
            s.strip()
            for s in self.allowed_subscription_ids_raw.split(",")
            if s.strip()
        ]
        return parsed if parsed else ([self.azure_sp_subscription_id] if self.azure_sp_subscription_id else [])

    def is_valid_subscription(self, subscription_id: str) -> bool:
        """Check whether a subscription ID is in the allowed list."""
        return subscription_id in self.allowed_subscription_ids


settings = Settings()
