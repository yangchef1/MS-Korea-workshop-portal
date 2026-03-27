"""
Configuration settings for Azure Workshop Portal
"""
from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # MSAL / JWT 검증용 (Microsoft 테넌트)
    azure_tenant_id: str = ""
    azure_client_id: str = ""
    azure_redirect_uri: str = "http://localhost:5173"

    # Service Principal (Azure 리소스 운영 테넌트)
    azure_sp_tenant_id: str = ""
    azure_sp_client_id: str = ""
    azure_sp_client_secret: str = ""
    azure_sp_domain: str = "yourdomain.com"
    azure_subscription_id: str = ""

    # 구독 캐싱/필터링
    subscription_cache_ttl_seconds: int = 60

    # Multi-subscription support: comma-separated list of allowed subscription IDs
    allowed_subscription_ids_raw: str = ""

    # CORS: comma-separated production origins (local origins added automatically)
    allowed_origins: str = ""

    session_secret_key: str = "change-this-secret-key-in-production"

    table_storage_account: str = "workshopstorage"

    use_azure_cli_credential: bool = False

    @field_validator("use_azure_cli_credential", mode="before")
    @classmethod
    def parse_use_azure_cli_credential(cls, value):
        """기존 동작과 동일하게 문자열 'true'만 True로 간주한다."""
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).lower() == "true"

    # Email settings (Azure Communication Services or SMTP)
    email_sender: str | None = None
    acs_connection_string: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None

    app_name: str = "Azure Workshop Management Portal"
    app_version: str = "1.0.0"

    default_services: list[str] = [
        "Microsoft.Compute",
        "Microsoft.Network",
        "Microsoft.Storage",
        "Microsoft.KeyVault",
        "Microsoft.ContainerService",
        "Microsoft.Sql"
    ]

    service_resource_types: dict[str, list[str]] = {
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

    # VM SKU 차단 리소스 충돌 감지용 상수
    VM_RESOURCE_TYPE: str = "Microsoft.Compute/virtualMachines"

    # VM SKU 프리셋: 프리셋 이름 → 허용 SKU 목록
    VM_SKU_PRESETS: dict[str, dict] = {
        "basic-lab": {
            "label": "Basic Lab",
            "description": "소형 VM만 허용 (GPU 차단)",
            "skus": [
                "Standard_B1s",
                "Standard_B1ms",
                "Standard_B2s",
                "Standard_B2ms",
                "Standard_B4ms",
                "Standard_D2s_v3",
                "Standard_D2s_v5",
                "Standard_D4s_v3",
                "Standard_D4s_v5",
                "Standard_D2as_v4",
                "Standard_D2as_v5",
                "Standard_D4as_v4",
                "Standard_D4as_v5",
                "Standard_DS1_v2",
                "Standard_DS2_v2",
            ],
        },
        "ai-ml": {
            "label": "AI/ML Workshop",
            "description": "GPU VM 포함 (대형 인스턴스 제한)",
            "skus": [
                # Basic Lab SKUs
                "Standard_B1s",
                "Standard_B1ms",
                "Standard_B2s",
                "Standard_B2ms",
                "Standard_B4ms",
                "Standard_D2s_v3",
                "Standard_D2s_v5",
                "Standard_D4s_v3",
                "Standard_D4s_v5",
                "Standard_D2as_v4",
                "Standard_D2as_v5",
                "Standard_D4as_v4",
                "Standard_D4as_v5",
                "Standard_DS1_v2",
                "Standard_DS2_v2",
                # GPU SKUs
                "Standard_NC4as_T4_v3",
                "Standard_NC8as_T4_v3",
                "Standard_NC16as_T4_v3",
                "Standard_NC6s_v3",
                "Standard_NC12s_v3",
                "Standard_NC24s_v3",
                "Standard_ND40rs_v2",
                "Standard_NV6ads_A10_v5",
                "Standard_NV12ads_A10_v5",
                "Standard_NV18ads_A10_v5",
            ],
        },
    }

    password_length: int = 16

    default_user_role: str = "Owner"
    resource_group_prefix: str = "rg-workshop"

    # Entra ID Security Group for Conditional Access Policy exclusion
    # Set WORKSHOP_ATTENDEES_GROUP_ID env var per environment.
    # Example: d4ca1936-d99e-4053-9904-bb0afa2e567e
    workshop_attendees_group_id: str = ""

    # Logging: "json" for production (Azure Monitor), "text" for development
    log_format: str = "text"
    log_level: str = "INFO"

    # Azure SDK retry
    azure_retry_total: int = 3
    azure_retry_backoff_factor: float = 1.0

    model_config = {"env_file": ".env", "case_sensitive": False, "extra": "ignore"}

    @property
    def allowed_subscription_ids(self) -> list[str]:
        """Parse ALLOWED_SUBSCRIPTION_IDS into a list; empty means "allow all"."""
        return [
            s.strip()
            for s in self.allowed_subscription_ids_raw.split(",")
            if s.strip()
        ]

    @property
    def deployment_subscription_id(self) -> str:
        """Subscription used for portal deployment (always excluded from assignment)."""
        return self.azure_subscription_id

    def is_valid_subscription(self, subscription_id: str) -> bool:
        """Check whether a subscription ID is in the allowed list (or allow-all when empty)."""
        if not self.allowed_subscription_ids:
            return True
        return subscription_id in self.allowed_subscription_ids


settings = Settings()
