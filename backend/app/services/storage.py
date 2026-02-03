"""Azure Blob Storage service for workshop metadata and templates.

Authentication: Uses DefaultAzureCredential (OIDC/Managed Identity)
- Local development: Azure CLI credential (az login)
- Production: Managed Identity assigned to App Service
"""
import asyncio
import json
import logging
from functools import lru_cache
from typing import List, Optional, Dict

from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceNotFoundError

from app.config import settings
from app.services.credential import get_azure_credential

logger = logging.getLogger(__name__)


class StorageService:
    """Service for managing workshop data in Azure Blob Storage."""

    def __init__(self):
        """Initialize Blob Storage client using Azure Identity."""
        try:
            account_url = f"https://{settings.blob_storage_account}.blob.core.windows.net"
            credential = get_azure_credential()
            
            self.blob_service_client = BlobServiceClient(
                account_url=account_url,
                credential=credential
            )

            self.container_name = settings.blob_container_name
            self._ensure_container_exists()
            logger.info("Initialized Storage service")
        except Exception as e:
            logger.error("Failed to initialize Blob Storage client: %s", e)
            raise

    def _ensure_container_exists(self) -> None:
        """Create container if it doesn't exist."""
        try:
            container_client = self.blob_service_client.get_container_client(
                self.container_name
            )
            if not container_client.exists():
                container_client.create_container()
                logger.info("Created container: %s", self.container_name)
        except Exception as e:
            logger.warning("Container check failed: %s", e)

    async def save_workshop_metadata(self, workshop_id: str, metadata: Dict) -> bool:
        """Save workshop metadata as JSON.

        Args:
            workshop_id: Unique workshop identifier
            metadata: Workshop metadata dictionary

        Returns:
            True if successful
        """
        def _save():
            blob_name = f"workshops/{workshop_id}.json"
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name,
                blob=blob_name
            )
            json_data = json.dumps(metadata, indent=2, default=str)
            blob_client.upload_blob(json_data, overwrite=True)

        try:
            await asyncio.to_thread(_save)
            logger.info("Saved workshop metadata: %s", workshop_id)
            return True

        except Exception as e:
            logger.error("Failed to save workshop metadata: %s", e)
            raise

    async def get_workshop_metadata(self, workshop_id: str) -> Optional[Dict]:
        """Retrieve workshop metadata.

        Args:
            workshop_id: Unique workshop identifier

        Returns:
            Workshop metadata dictionary or None if not found
        """
        def _get():
            blob_name = f"workshops/{workshop_id}.json"
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name,
                blob=blob_name
            )
            blob_data = blob_client.download_blob().readall()
            return json.loads(blob_data)

        try:
            return await asyncio.to_thread(_get)

        except ResourceNotFoundError:
            logger.warning("Workshop not found: %s", workshop_id)
            return None
        except Exception as e:
            logger.error("Failed to retrieve workshop metadata: %s", e)
            raise

    async def list_all_workshops(self) -> List[Dict]:
        """List all workshop metadata.

        Returns:
            List of workshop metadata dictionaries
        """
        def _list():
            container_client = self.blob_service_client.get_container_client(
                self.container_name
            )
            workshops = []
            for blob in container_client.list_blobs(name_starts_with="workshops/"):
                if blob.name.endswith(".json"):
                    blob_client = container_client.get_blob_client(blob.name)
                    blob_data = blob_client.download_blob().readall()
                    metadata = json.loads(blob_data)
                    workshops.append(metadata)
            workshops.sort(key=lambda x: x.get('created_at', ''), reverse=True)
            return workshops

        try:
            return await asyncio.to_thread(_list)

        except Exception as e:
            logger.error("Failed to list workshops: %s", e)
            raise

    async def delete_workshop_metadata(self, workshop_id: str) -> bool:
        """Delete workshop metadata and passwords.

        Args:
            workshop_id: Unique workshop identifier

        Returns:
            True if successful
        """
        def _delete():
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name,
                blob=f"workshops/{workshop_id}.json"
            )
            blob_client.delete_blob()

            try:
                passwords_blob = self.blob_service_client.get_blob_client(
                    container=self.container_name,
                    blob=f"workshops/{workshop_id}-passwords.csv"
                )
                passwords_blob.delete_blob()
            except ResourceNotFoundError:
                pass

        try:
            await asyncio.to_thread(_delete)
            logger.info("Deleted workshop: %s", workshop_id)
            return True

        except Exception as e:
            logger.error("Failed to delete workshop: %s", e)
            raise

    async def save_passwords_csv(self, workshop_id: str, csv_content: str) -> bool:
        """Save participant passwords as CSV.

        Args:
            workshop_id: Unique workshop identifier
            csv_content: CSV content string

        Returns:
            True if successful
        """
        def _save():
            blob_name = f"workshops/{workshop_id}-passwords.csv"
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name,
                blob=blob_name
            )
            blob_client.upload_blob(csv_content, overwrite=True)

        try:
            await asyncio.to_thread(_save)
            logger.info("Saved passwords CSV: %s", workshop_id)
            return True

        except Exception as e:
            logger.error("Failed to save passwords CSV: %s", e)
            raise

    async def get_passwords_csv(self, workshop_id: str) -> Optional[str]:
        """Retrieve passwords CSV.

        Args:
            workshop_id: Unique workshop identifier

        Returns:
            CSV content string or None if not found
        """
        def _get():
            blob_name = f"workshops/{workshop_id}-passwords.csv"
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name,
                blob=blob_name
            )
            return blob_client.download_blob().readall().decode('utf-8')

        try:
            return await asyncio.to_thread(_get)

        except ResourceNotFoundError:
            logger.warning("Passwords CSV not found: %s", workshop_id)
            return None
        except Exception as e:
            logger.error("Failed to retrieve passwords CSV: %s", e)
            raise

    async def list_arm_templates(self) -> List[Dict]:
        """List available ARM templates.

        Returns:
            List of template info dictionaries
        """
        def _list():
            container_client = self.blob_service_client.get_container_client(
                self.container_name
            )
            templates = []
            for blob in container_client.list_blobs(name_starts_with="templates/"):
                if blob.name.endswith(".json"):
                    filename = blob.name.split('/')[-1]
                    templates.append({
                        'name': filename,
                        'description': '',
                        'path': blob.name
                    })
            return sorted(templates, key=lambda x: x['name'])

        try:
            return await asyncio.to_thread(_list)

        except Exception as e:
            logger.error("Failed to list ARM templates: %s", e)
            raise

    async def get_arm_template(self, template_name: str) -> Optional[Dict]:
        """Retrieve ARM template content.

        Args:
            template_name: Template filename

        Returns:
            ARM template JSON or None if not found
        """
        def _get():
            blob_name = f"templates/{template_name}"
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name,
                blob=blob_name
            )
            blob_data = blob_client.download_blob().readall()
            return json.loads(blob_data)

        try:
            return await asyncio.to_thread(_get)

        except ResourceNotFoundError:
            logger.warning("ARM template not found: %s", template_name)
            return None
        except Exception as e:
            logger.error("Failed to retrieve ARM template: %s", e)
            raise


@lru_cache(maxsize=1)
def get_storage_service() -> StorageService:
    """Get the StorageService singleton instance."""
    return StorageService()


storage_service = get_storage_service()
