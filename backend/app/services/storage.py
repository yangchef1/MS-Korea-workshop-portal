"""Azure Table Storage 서비스 (비동기).

워크샵 메타데이터와 ARM 템플릿을 관리한다.
azure.data.tables.aio를 사용하여 진정한 비동기 I/O를 제공한다.

Tables:
- workshops: 워크샵 메타데이터 (PartitionKey="workshop", RowKey=workshop_id)
- passwords: 참가자 비밀번호 CSV (PartitionKey="password", RowKey=workshop_id)
- templates: ARM 템플릿 (PartitionKey="template", RowKey=template_name)
"""
import json
import logging
from functools import lru_cache
from typing import Any

from azure.core.exceptions import ResourceNotFoundError
from azure.data.tables.aio import TableServiceClient
from azure.identity.aio import (
    AzureCliCredential,
    ClientSecretCredential,
    DefaultAzureCredential,
)
from pydantic import ValidationError as PydanticValidationError

from app.config import settings
from app.exceptions import ValidationError as AppValidationError
from app.models import DeletionFailureItem, WorkshopMetadata

logger = logging.getLogger(__name__)

WORKSHOPS_TABLE = "workshops"
PASSWORDS_TABLE = "passwords"
TEMPLATES_TABLE = "templates"
USERS_TABLE = "users"
DELETION_FAILURES_TABLE = "deletionfailures"
PORTAL_SETTINGS_TABLE = "portalsettings"

WORKSHOP_PARTITION_KEY = "workshop"
PASSWORD_PARTITION_KEY = "password"
TEMPLATE_PARTITION_KEY = "template"
USER_PARTITION_KEY = "user"
PORTAL_SETTINGS_PARTITION_KEY = "config"
PORTAL_SETTINGS_ROW_KEY_SUBSCRIPTIONS = "subscriptions"


class StorageService:
    """Azure Table Storage를 사용하여 워크샵 데이터를 관리하는 비동기 서비스.

    azure.data.tables.aio의 네이티브 비동기 클라이언트를 사용하여
    스레드풀 자원 소모 없이 Non-blocking I/O를 제공한다.
    """

    _tables_initialized: bool = False

    def __init__(self) -> None:
        """Azure Identity를 사용하여 비동기 Table Storage 클라이언트를 초기화한다."""
        try:
            account_url = (
                f"https://{settings.table_storage_account}.table.core.windows.net"
            )
            credential = self._create_credential()

            self.table_service_client = TableServiceClient(
                endpoint=account_url,
                credential=credential,
                retry_total=settings.azure_retry_total,
                retry_backoff_factor=settings.azure_retry_backoff_factor,
            )

            logger.info("Initialized async Table Storage service")
        except Exception as e:
            logger.error("Failed to initialize Table Storage client: %s", e)
            raise

    @staticmethod
    def _create_credential() -> ClientSecretCredential | DefaultAzureCredential | AzureCliCredential:
        """설정에 따라 적절한 비동기 Azure credential을 생성한다."""
        if settings.azure_sp_tenant_id and settings.azure_sp_client_id and settings.azure_sp_client_secret:
            return ClientSecretCredential(
                tenant_id=settings.azure_sp_tenant_id,
                client_id=settings.azure_sp_client_id,
                client_secret=settings.azure_sp_client_secret,
            )
        if settings.use_azure_cli_credential:
            return AzureCliCredential()
        return DefaultAzureCredential(
            exclude_shared_token_cache_credential=True,
            exclude_visual_studio_code_credential=True,
            exclude_azure_powershell_credential=True,
            exclude_interactive_browser_credential=True,
        )

    async def _ensure_tables_exist(self) -> None:
        """필요한 테이블이 존재하지 않으면 생성한다 (lazy 초기화)."""
        if StorageService._tables_initialized:
            return
        for table_name in (
            WORKSHOPS_TABLE,
            PASSWORDS_TABLE,
            TEMPLATES_TABLE,
            USERS_TABLE,
            DELETION_FAILURES_TABLE,
            PORTAL_SETTINGS_TABLE,
        ):
            try:
                await self.table_service_client.create_table_if_not_exists(table_name)
                logger.info("Ensured table exists: %s", table_name)
            except Exception as e:
                logger.warning("Table check failed for '%s': %s", table_name, e)
        StorageService._tables_initialized = True

    # ------------------------------------------------------------------
    # Workshop metadata
    # ------------------------------------------------------------------

    async def save_workshop_metadata(self, workshop_id: str, metadata: dict[str, Any]) -> bool:
        """워크샵 메타데이터를 테이블 엔티티로 저장한다.

        Table Storage에는 스키마 검증이 없으므로, 저장 전에
        Pydantic 모델로 앱 레벨 검증을 수행한다.

        Args:
            workshop_id: 워크샵 고유 식별자.
            metadata: 워크샵 메타데이터 딕셔너리.

        Returns:
            성공 시 True.

        Raises:
            AppValidationError: 메타데이터가 스키마 검증에 실패한 경우.
        """
        self._validate_workshop_metadata(metadata)
        await self._ensure_tables_exist()

        try:
            table_client = self.table_service_client.get_table_client(WORKSHOPS_TABLE)
            entity = _workshop_to_entity(workshop_id, metadata)
            await table_client.upsert_entity(entity)
            logger.info("Saved workshop metadata: %s", workshop_id)
            return True
        except Exception as e:
            logger.error("Failed to save workshop metadata: %s", e)
            raise

    @staticmethod
    def _validate_workshop_metadata(metadata: dict[str, Any]) -> None:
        """Pydantic 모델을 사용하여 메타데이터를 검증한다.

        Args:
            metadata: 검증할 워크샵 메타데이터.

        Raises:
            AppValidationError: 검증 실패 시.
        """
        try:
            WorkshopMetadata.model_validate(metadata)
        except PydanticValidationError as e:
            error_details = [
                f"{err['loc']}: {err['msg']}" for err in e.errors()
            ]
            raise AppValidationError(
                f"Workshop metadata validation failed: {'; '.join(error_details)}"
            ) from e

    async def get_workshop_metadata(self, workshop_id: str) -> dict[str, Any] | None:
        """워크샵 메타데이터를 조회한다.

        Args:
            workshop_id: 워크샵 고유 식별자.

        Returns:
            워크샵 메타데이터 딕셔너리. 존재하지 않으면 None.
        """

        await self._ensure_tables_exist()

        try:
            table_client = self.table_service_client.get_table_client(WORKSHOPS_TABLE)
            entity = await table_client.get_entity(
                partition_key=WORKSHOP_PARTITION_KEY,
                row_key=workshop_id,
            )
            return _entity_to_workshop(entity)
        except ResourceNotFoundError:
            logger.warning("Workshop not found: %s", workshop_id)
            return None
        except Exception as e:
            logger.error("Failed to retrieve workshop metadata: %s", e)
            raise

    async def list_all_workshops(self) -> list[dict[str, Any]]:
        """모든 워크샵 메타데이터를 조회한다.

        Returns:
            created_at 내림차순으로 정렬된 워크샵 메타데이터 목록.
        """

        await self._ensure_tables_exist()

        try:
            table_client = self.table_service_client.get_table_client(WORKSHOPS_TABLE)
            query_filter = f"PartitionKey eq '{WORKSHOP_PARTITION_KEY}'"
            workshops = [
                _entity_to_workshop(e)
                async for e in table_client.query_entities(query_filter)
            ]
            workshops.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            return workshops
        except Exception as e:
            logger.error("Failed to list workshops: %s", e)
            raise

    async def delete_workshop_metadata(self, workshop_id: str) -> bool:
        """워크샵 메타데이터와 관련 비밀번호를 삭제한다.

        Args:
            workshop_id: 워크샵 고유 식별자.

        Returns:
            성공 시 True.
        """

        await self._ensure_tables_exist()

        try:
            workshops_client = self.table_service_client.get_table_client(
                WORKSHOPS_TABLE
            )
            await workshops_client.delete_entity(
                partition_key=WORKSHOP_PARTITION_KEY,
                row_key=workshop_id,
            )

            try:
                passwords_client = self.table_service_client.get_table_client(
                    PASSWORDS_TABLE
                )
                await passwords_client.delete_entity(
                    partition_key=PASSWORD_PARTITION_KEY,
                    row_key=workshop_id,
                )
            except ResourceNotFoundError:
                pass

            logger.info("Deleted workshop: %s", workshop_id)
            return True
        except Exception as e:
            logger.error("Failed to delete workshop: %s", e)
            raise

    # ------------------------------------------------------------------
    # Passwords CSV
    # ------------------------------------------------------------------

    async def save_passwords_csv(self, workshop_id: str, csv_content: str) -> bool:
        """참가자 비밀번호 CSV를 테이블 엔티티로 저장한다.

        Args:
            workshop_id: 워크샵 고유 식별자.
            csv_content: CSV 문자열.

        Returns:
            성공 시 True.
        """

        await self._ensure_tables_exist()

        try:
            table_client = self.table_service_client.get_table_client(PASSWORDS_TABLE)
            entity = {
                "PartitionKey": PASSWORD_PARTITION_KEY,
                "RowKey": workshop_id,
                "csv_content": csv_content,
            }
            await table_client.upsert_entity(entity)
            logger.info("Saved passwords CSV: %s", workshop_id)
            return True
        except Exception as e:
            logger.error("Failed to save passwords CSV: %s", e)
            raise

    async def get_passwords_csv(self, workshop_id: str) -> str | None:
        """비밀번호 CSV를 조회한다.

        Args:
            workshop_id: 워크샵 고유 식별자.

        Returns:
            CSV 문자열. 존재하지 않으면 None.
        """

        await self._ensure_tables_exist()

        try:
            table_client = self.table_service_client.get_table_client(PASSWORDS_TABLE)
            entity = await table_client.get_entity(
                partition_key=PASSWORD_PARTITION_KEY,
                row_key=workshop_id,
            )
            return entity.get("csv_content", "")
        except ResourceNotFoundError:
            logger.warning("Passwords CSV not found: %s", workshop_id)
            return None
        except Exception as e:
            logger.error("Failed to retrieve passwords CSV: %s", e)
            raise

    # ------------------------------------------------------------------
    # Portal Users (role management)
    # ------------------------------------------------------------------

    async def save_portal_user(self, user_data: dict[str, Any]) -> bool:
        """포털 사용자 정보를 저장 또는 업데이트한다.

        이메일(lowercase)을 RowKey로 사용하여 화이트리스트 조회를 지원한다.

        Args:
            user_data: 사용자 정보 (email, name, user_id, role, registered_at).

        Returns:
            성공 시 True.
        """
        await self._ensure_tables_exist()

        try:
            table_client = self.table_service_client.get_table_client(USERS_TABLE)
            email = user_data.get("email", "").strip().lower()
            entity = {
                "PartitionKey": USER_PARTITION_KEY,
                "RowKey": email,
                "user_id": user_data.get("user_id", ""),
                "name": user_data.get("name", ""),
                "role": user_data.get("role", "user"),
                "status": user_data.get("status", "active"),
                "registered_at": user_data.get("registered_at", ""),
            }
            await table_client.upsert_entity(entity)
            logger.info("Saved portal user: %s", email)
            return True
        except Exception as e:
            logger.error("Failed to save portal user: %s", e)
            raise

    async def get_portal_user(self, email: str) -> dict[str, Any] | None:
        """포털 사용자 정보를 이메일로 조회한다.

        Args:
            email: 사용자 이메일.

        Returns:
            사용자 정보 딕셔너리. 존재하지 않으면 None.
        """
        await self._ensure_tables_exist()

        try:
            table_client = self.table_service_client.get_table_client(USERS_TABLE)
            entity = await table_client.get_entity(
                partition_key=USER_PARTITION_KEY,
                row_key=email.strip().lower(),
            )
            return {
                "user_id": entity.get("user_id", ""),
                "name": entity.get("name", ""),
                "email": entity["RowKey"],
                "role": entity.get("role", "user"),
                "status": entity.get("status", "active"),
                "registered_at": entity.get("registered_at", ""),
            }
        except ResourceNotFoundError:
            return None
        except Exception as e:
            logger.error("Failed to get portal user: %s", e)
            raise

    async def delete_portal_user(self, email: str) -> bool:
        """포털 사용자를 삭제한다.

        Args:
            email: 삭제할 사용자 이메일.

        Returns:
            성공 시 True.
        """
        await self._ensure_tables_exist()

        try:
            table_client = self.table_service_client.get_table_client(USERS_TABLE)
            await table_client.delete_entity(
                partition_key=USER_PARTITION_KEY,
                row_key=email.strip().lower(),
            )
            logger.info("Deleted portal user: %s", email)
            return True
        except Exception as e:
            logger.error("Failed to delete portal user: %s", e)
            raise

    async def list_portal_users(self) -> list[dict[str, Any]]:
        """모든 포털 사용자를 조회한다.

        Returns:
            등록일 내림차순으로 정렬된 사용자 목록.
        """
        await self._ensure_tables_exist()

        try:
            table_client = self.table_service_client.get_table_client(USERS_TABLE)
            query_filter = f"PartitionKey eq '{USER_PARTITION_KEY}'"
            users = [
                {
                    "user_id": e.get("user_id", ""),
                    "name": e.get("name", ""),
                    "email": e["RowKey"],
                    "role": e.get("role", "user"),
                    "status": e.get("status", "active"),
                    "registered_at": e.get("registered_at", ""),
                }
                async for e in table_client.query_entities(query_filter)
            ]
            users.sort(
                key=lambda x: x.get("registered_at", ""), reverse=True
            )
            return users
        except Exception as e:
            logger.error("Failed to list portal users: %s", e)
            raise

    # ------------------------------------------------------------------
    # Portal settings (subscriptions allow/deny)
    # ------------------------------------------------------------------

    async def get_portal_subscription_settings(self) -> dict[str, list[str]]:
        """구독 허용/제외 설정을 조회한다.

        Returns:
            allow_list와 deny_list를 포함하는 딕셔너리. 설정이 없으면 빈 리스트를 반환한다.
        """
        await self._ensure_tables_exist()

        try:
            table_client = self.table_service_client.get_table_client(PORTAL_SETTINGS_TABLE)
            entity = await table_client.get_entity(
                partition_key=PORTAL_SETTINGS_PARTITION_KEY,
                row_key=PORTAL_SETTINGS_ROW_KEY_SUBSCRIPTIONS,
            )
            return {
                "allow_list": json.loads(entity.get("allow_list_json", "[]")),
                "deny_list": json.loads(entity.get("deny_list_json", "[]")),
            }
        except ResourceNotFoundError:
            return {"allow_list": [], "deny_list": []}
        except Exception as e:
            logger.error("Failed to get portal subscription settings: %s", e)
            raise

    async def save_portal_subscription_settings(
        self, allow_list: list[str], deny_list: list[str]
    ) -> dict[str, list[str]]:
        """구독 허용/제외 설정을 저장한다.

        Args:
            allow_list: 허용 구독 ID 목록(빈 리스트면 전체 허용).
            deny_list: 제외 구독 ID 목록.

        Returns:
            저장된 allow_list와 deny_list.
        """
        await self._ensure_tables_exist()

        try:
            table_client = self.table_service_client.get_table_client(PORTAL_SETTINGS_TABLE)
            entity = {
                "PartitionKey": PORTAL_SETTINGS_PARTITION_KEY,
                "RowKey": PORTAL_SETTINGS_ROW_KEY_SUBSCRIPTIONS,
                "allow_list_json": json.dumps(allow_list),
                "deny_list_json": json.dumps(deny_list),
            }
            await table_client.upsert_entity(entity)
            logger.info("Saved portal subscription settings (allow=%d, deny=%d)", len(allow_list), len(deny_list))
            return {"allow_list": allow_list, "deny_list": deny_list}
        except Exception as e:
            logger.error("Failed to save portal subscription settings: %s", e)
            raise

    # ------------------------------------------------------------------
    # Templates
    # ------------------------------------------------------------------

    async def create_template(
        self,
        name: str,
        description: str,
        template_content: str,
        template_type: str = "arm",
        compiled_arm_content: str | None = None,
    ) -> dict[str, str]:
        """새 인프라 템플릿을 생성한다.

        Args:
            name: 템플릿 이름 (RowKey로 사용).
            description: 템플릿 설명.
            template_content: 템플릿 콘텐츠 문자열.
            template_type: 템플릿 유형 (arm, bicep).
            compiled_arm_content: Bicep 프리컴파일 ARM JSON 문자열.

        Returns:
            생성된 템플릿 정보 딕셔너리.

        Raises:
            ConflictError: 동일 이름의 템플릿이 이미 존재하는 경우.
        """
        from app.exceptions import ConflictError

        await self._ensure_tables_exist()

        table_client = self.table_service_client.get_table_client(TEMPLATES_TABLE)

        # Check for duplicate name
        try:
            await table_client.get_entity(
                partition_key=TEMPLATE_PARTITION_KEY,
                row_key=name,
            )
            raise ConflictError(f"Template '{name}' already exists")
        except ResourceNotFoundError:
            pass  # Expected – template does not exist yet

        entity = {
            "PartitionKey": TEMPLATE_PARTITION_KEY,
            "RowKey": name,
            "description": description,
            "path": name,
            "template_type": template_type,
            "template_content": template_content,
        }
        if compiled_arm_content:
            entity["compiled_arm_content"] = compiled_arm_content

        await table_client.create_entity(entity)
        logger.info("Created template: %s (type=%s)", name, template_type)

        return {
            "name": name,
            "description": description,
            "path": name,
            "template_type": template_type,
        }

    async def list_templates(self) -> list[dict[str, str]]:
        """사용 가능한 인프라 템플릿 목록을 조회한다.

        Returns:
            템플릿 정보 딕셔너리 목록.
        """

        await self._ensure_tables_exist()

        try:
            table_client = self.table_service_client.get_table_client(TEMPLATES_TABLE)
            query_filter = f"PartitionKey eq '{TEMPLATE_PARTITION_KEY}'"
            templates = [
                {
                    "name": e["RowKey"],
                    "description": e.get("description", ""),
                    "path": e.get("path", e["RowKey"]),
                    "template_type": e.get("template_type", "arm"),
                }
                async for e in table_client.query_entities(query_filter)
            ]
            return sorted(templates, key=lambda x: x["name"])
        except Exception as e:
            logger.error("Failed to list templates: %s", e)
            raise

    async def get_template(self, template_name: str) -> dict[str, Any] | None:
        """배포용 ARM 템플릿 JSON dict를 조회한다.

        ARM 유형이면 template_content를 파싱하고,
        Bicep 유형이면 프리컴파일된 compiled_arm_content를 반환한다.

        Args:
            template_name: 템플릿 파일명 (RowKey로 사용).

        Returns:
            파싱된 ARM 템플릿 JSON dict. 존재하지 않으면 None.
        """

        await self._ensure_tables_exist()

        try:
            table_client = self.table_service_client.get_table_client(TEMPLATES_TABLE)
            entity = await table_client.get_entity(
                partition_key=TEMPLATE_PARTITION_KEY,
                row_key=template_name,
            )
            template_type = entity.get("template_type", "arm")

            if template_type == "bicep":
                compiled = entity.get("compiled_arm_content")
                if not compiled:
                    logger.warning(
                        "Bicep template '%s' has no compiled ARM content",
                        template_name,
                    )
                    return None
                return json.loads(compiled)

            return json.loads(entity.get("template_content", "{}"))
        except ResourceNotFoundError:
            logger.warning("Template not found: %s", template_name)
            return None
        except Exception as e:
            logger.error("Failed to retrieve template: %s", e)
            raise

    async def get_template_detail(self, template_name: str) -> dict[str, Any] | None:
        """템플릿 메타데이터와 콘텐츠를 함께 조회한다.

        Args:
            template_name: 템플릿 이름 (RowKey).

        Returns:
            name, description, template_content를 포함하는 딕셔너리. 없으면 None.
        """
        await self._ensure_tables_exist()

        try:
            table_client = self.table_service_client.get_table_client(TEMPLATES_TABLE)
            entity = await table_client.get_entity(
                partition_key=TEMPLATE_PARTITION_KEY,
                row_key=template_name,
            )
            return {
                "name": entity["RowKey"],
                "description": entity.get("description", ""),
                "path": entity.get("path", entity["RowKey"]),
                "template_type": entity.get("template_type", "arm"),
                "template_content": entity.get("template_content", "{}"),
            }
        except ResourceNotFoundError:
            return None
        except Exception as e:
            logger.error("Failed to get template detail '%s': %s", template_name, e)
            raise

    async def update_template(
        self,
        template_name: str,
        description: str | None = None,
        template_content: str | None = None,
        template_type: str | None = None,
        compiled_arm_content: str | None = None,
    ) -> dict[str, str]:
        """기존 템플릿의 메타데이터 또는 콘텐츠를 업데이트한다.

        Args:
            template_name: 업데이트할 템플릿 이름 (RowKey).
            description: 새 설명. None이면 변경하지 않음.
            template_content: 새 콘텐츠 문자열. None이면 변경하지 않음.
            template_type: 새 템플릿 유형. None이면 변경하지 않음.
            compiled_arm_content: Bicep 프리컴파일 ARM JSON. None이면 변경하지 않음.

        Returns:
            업데이트된 템플릿 정보 딕셔너리.

        Raises:
            EntityNotFoundError: 템플릿이 존재하지 않는 경우.
        """
        from app.exceptions import EntityNotFoundError

        await self._ensure_tables_exist()

        table_client = self.table_service_client.get_table_client(TEMPLATES_TABLE)

        try:
            entity = await table_client.get_entity(
                partition_key=TEMPLATE_PARTITION_KEY,
                row_key=template_name,
            )
        except ResourceNotFoundError:
            raise EntityNotFoundError(
                f"Template '{template_name}' not found"
            )

        if description is not None:
            entity["description"] = description
        if template_content is not None:
            entity["template_content"] = template_content
        if template_type is not None:
            entity["template_type"] = template_type
        if compiled_arm_content is not None:
            entity["compiled_arm_content"] = compiled_arm_content

        await table_client.update_entity(entity, mode="merge")
        logger.info("Updated template: %s", template_name)

        return {
            "name": entity["RowKey"],
            "description": entity.get("description", ""),
            "path": entity.get("path", entity["RowKey"]),
            "template_type": entity.get("template_type", "arm"),
        }

    async def delete_template(self, template_name: str) -> None:
        """인프라 템플릿을 삭제한다.

        Args:
            template_name: 삭제할 템플릿 이름 (RowKey).

        Raises:
            EntityNotFoundError: 템플릿이 존재하지 않는 경우.
        """
        from app.exceptions import EntityNotFoundError

        await self._ensure_tables_exist()

        table_client = self.table_service_client.get_table_client(TEMPLATES_TABLE)

        try:
            await table_client.get_entity(
                partition_key=TEMPLATE_PARTITION_KEY,
                row_key=template_name,
            )
        except ResourceNotFoundError:
            raise EntityNotFoundError(
                f"Template '{template_name}' not found"
            )

        await table_client.delete_entity(
            partition_key=TEMPLATE_PARTITION_KEY,
            row_key=template_name,
        )
        logger.info("Deleted template: %s", template_name)


    # ------------------------------------------------------------------
    # Deletion failures
    # ------------------------------------------------------------------

    async def save_deletion_failure(self, failure: DeletionFailureItem) -> bool:
        """삭제 실패 항목을 저장한다.

        Args:
            failure: 삭제 실패 항목.

        Returns:
            성공 시 True.
        """
        await self._ensure_tables_exist()

        try:
            table_client = self.table_service_client.get_table_client(
                DELETION_FAILURES_TABLE
            )
            entity = _failure_to_entity(failure)
            await table_client.upsert_entity(entity)
            logger.info(
                "Saved deletion failure: %s (workshop: %s)",
                failure.id,
                failure.workshop_id,
            )
            return True
        except Exception as e:
            logger.error("Failed to save deletion failure: %s", e)
            raise

    async def list_deletion_failures_by_workshop(
        self, workshop_id: str
    ) -> list[DeletionFailureItem]:
        """워크샵별 삭제 실패 항목을 조회한다.

        PK=workshop_id 단일 파티션 쿼리로 최적화된다.

        Args:
            workshop_id: 워크샵 고유 식별자.

        Returns:
            삭제 실패 항목 목록 (failed_at 내림차순).
        """
        await self._ensure_tables_exist()

        try:
            table_client = self.table_service_client.get_table_client(
                DELETION_FAILURES_TABLE
            )
            query_filter = f"PartitionKey eq '{workshop_id}'"
            failures = [
                _entity_to_failure(e)
                async for e in table_client.query_entities(query_filter)
            ]
            failures.sort(
                key=lambda x: x.get("failed_at", ""), reverse=True
            )
            return failures
        except Exception as e:
            logger.error(
                "Failed to list deletion failures for workshop %s: %s",
                workshop_id,
                e,
            )
            raise

    async def update_deletion_failure(
        self, failure_id: str, workshop_id: str, updates: dict[str, Any]
    ) -> bool:
        """삭제 실패 항목을 부분 업데이트한다.

        Args:
            failure_id: 실패 항목 ID (RowKey).
            workshop_id: 워크샵 ID (PartitionKey).
            updates: 업데이트할 필드 딕셔너리.

        Returns:
            성공 시 True.
        """
        await self._ensure_tables_exist()

        try:
            table_client = self.table_service_client.get_table_client(
                DELETION_FAILURES_TABLE
            )
            entity = {
                "PartitionKey": workshop_id,
                "RowKey": failure_id,
                **updates,
            }
            await table_client.update_entity(entity, mode="merge")
            logger.info("Updated deletion failure: %s", failure_id)
            return True
        except Exception as e:
            logger.error("Failed to update deletion failure %s: %s", failure_id, e)
            raise

    async def delete_deletion_failure(
        self, failure_id: str, workshop_id: str
    ) -> bool:
        """삭제 실패 항목을 제거한다.

        Args:
            failure_id: 실패 항목 ID (RowKey).
            workshop_id: 워크샵 ID (PartitionKey).

        Returns:
            성공 시 True.
        """
        await self._ensure_tables_exist()

        try:
            table_client = self.table_service_client.get_table_client(
                DELETION_FAILURES_TABLE
            )
            await table_client.delete_entity(
                partition_key=workshop_id,
                row_key=failure_id,
            )
            logger.info("Deleted deletion failure: %s", failure_id)
            return True
        except Exception as e:
            logger.error("Failed to delete deletion failure %s: %s", failure_id, e)
            raise


# ------------------------------------------------------------------
# Entity ↔ Dict conversion helpers
# ------------------------------------------------------------------


def _workshop_to_entity(workshop_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
    """워크샵 메타데이터 dict를 Table Storage 엔티티로 변환한다.

    Table Storage는 플랫 프로퍼티 타입만 지원하므로,
    복합 필드(participants, policy)는 JSON 문자열로 직렬화한다.
    """
    return {
        "PartitionKey": WORKSHOP_PARTITION_KEY,
        "RowKey": workshop_id,
        "name": metadata.get("name", ""),
        "start_date": metadata.get("start_date", ""),
        "end_date": metadata.get("end_date", ""),
        "base_resources_template": metadata.get("base_resources_template", ""),
        "status": metadata.get("status", "active"),
        "created_at": metadata.get("created_at", ""),
        "created_by": metadata.get("created_by", ""),
        "survey_url": metadata.get("survey_url", ""),
        # JSON-serialized complex fields
        "participants_json": json.dumps(
            metadata.get("participants", []), default=str
        ),
        "policy_json": json.dumps(metadata.get("policy", {}), default=str),
    }


def _entity_to_workshop(entity: dict[str, Any]) -> dict[str, Any]:
    """Table Storage 엔티티를 워크샵 메타데이터 dict로 변환한다."""
    return {
        "id": entity["RowKey"],
        "name": entity.get("name", ""),
        "start_date": entity.get("start_date", ""),
        "end_date": entity.get("end_date", ""),
        "base_resources_template": entity.get("base_resources_template", ""),
        "status": entity.get("status", "active"),
        "created_at": entity.get("created_at", ""),
        "created_by": entity.get("created_by"),
        "survey_url": entity.get("survey_url", ""),
        "participants": json.loads(entity.get("participants_json", "[]")),
        "policy": json.loads(entity.get("policy_json", "{}")),
    }


def _failure_to_entity(failure: DeletionFailureItem) -> dict[str, Any]:
    """DeletionFailureItem을 Table Storage 엔티티로 변환한다."""
    return {
        "PartitionKey": failure.workshop_id,
        "RowKey": failure.id,
        "workshop_name": failure.workshop_name,
        "resource_type": failure.resource_type,
        "resource_name": failure.resource_name,
        "subscription_id": failure.subscription_id or "",
        "error_message": failure.error_message,
        "failed_at": failure.failed_at,
        "status": failure.status,
        "retry_count": failure.retry_count,
    }


def _entity_to_failure(entity: dict[str, Any]) -> dict[str, Any]:
    """Table Storage 엔티티를 삭제 실패 항목 dict로 변환한다."""
    return {
        "id": entity["RowKey"],
        "workshop_id": entity["PartitionKey"],
        "workshop_name": entity.get("workshop_name", ""),
        "resource_type": entity.get("resource_type", ""),
        "resource_name": entity.get("resource_name", ""),
        "subscription_id": entity.get("subscription_id") or None,
        "error_message": entity.get("error_message", ""),
        "failed_at": entity.get("failed_at", ""),
        "status": entity.get("status", "pending"),
        "retry_count": int(entity.get("retry_count", 0)),
    }


# ------------------------------------------------------------------
# Singleton
# ------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_storage_service() -> StorageService:
    """StorageService 싱글턴 인스턴스를 반환한다."""
    return StorageService()


storage_service = get_storage_service()
