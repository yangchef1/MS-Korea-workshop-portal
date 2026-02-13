"""워크샵 참가자에게 자격 증명을 전송하는 이메일 서비스.

지원 제공자:
- Azure Communication Services (Azure 환경 권장)
- SMTP (기타 환경 대체)
"""
import asyncio
import logging
import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import settings

logger = logging.getLogger(__name__)

# Rate limiting 지연 (초)
_SEND_DELAY_SECONDS = 0.5

# Jinja2 템플릿 환경 (모듈 레벨에서 한 번만 초기화)
_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_jinja_env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=select_autoescape(["html"]),
)


@dataclass
class EmailMessage:
    """이메일 메시지 구조체."""

    to: str
    subject: str
    body_html: str
    body_text: str


class EmailService:
    """워크샵 참가자에게 이메일을 전송하는 서비스."""

    def __init__(self) -> None:
        """설정에 기반하여 이메일 서비스를 초기화한다."""
        self._sender_email = settings.email_sender
        self._smtp_host = settings.smtp_host
        self._smtp_port = settings.smtp_port
        self._smtp_username = settings.smtp_username
        self._smtp_password = settings.smtp_password
        self._acs_connection_string = settings.acs_connection_string

        logger.info("Initialized Email service")

    def _generate_credential_email(
        self,
        participant: dict,
        workshop_name: str,
    ) -> EmailMessage:
        """참가자용 자격 증명 이메일을 생성한다.

        Jinja2 템플릿 파일(credential_email.html, credential_email.txt)을
        사용하여 이메일 본문을 렌더링한다.

        Args:
            participant: email, upn, password 등을 포함한 참가자 데이터.
            workshop_name: 워크샵 이름.

        Returns:
            HTML 및 텍스트 본문을 포함한 EmailMessage.
        """
        template_context = {
            "workshop_name": workshop_name,
            "alias": participant.get("alias", ""),
            "email": participant.get("email", ""),
            "upn": participant.get("upn", ""),
            "password": participant.get("password", ""),
            "subscription_id": participant.get("subscription_id", ""),
            "resource_group": participant.get("resource_group", ""),
            # Optional branding / layout variables (Jinja2 default filters handle missing)
            "logo_url": participant.get("logo_url", ""),
            "logo_alt": participant.get("logo_alt", ""),
            "logo_width": participant.get("logo_width", ""),
            "header_bg_color": participant.get("header_bg_color", ""),
            "cta_color": participant.get("cta_color", ""),
            "cta_url": participant.get("cta_url", ""),
            "cta_text": participant.get("cta_text", ""),
            "contact_text": participant.get("contact_text", ""),
            "contact_email": participant.get("contact_email", ""),
            "disclaimer": participant.get("disclaimer", ""),
            "copyright": participant.get("copyright", ""),
        }

        html_template = _jinja_env.get_template("credential_email.html")
        text_template = _jinja_env.get_template("credential_email.txt")

        return EmailMessage(
            to=template_context["email"],
            subject=f"[{workshop_name}] Azure Workshop 계정 정보",
            body_html=html_template.render(**template_context),
            body_text=text_template.render(**template_context),
        )

    async def send_email_smtp(self, message: EmailMessage) -> bool:
        """SMTP를 통해 이메일을 전송한다.

        Args:
            message: 전송할 EmailMessage.

        Returns:
            전송 성공 시 True.
        """
        required_fields = [
            self._smtp_host,
            self._smtp_username,
            self._smtp_password,
            self._sender_email,
        ]
        if not all(required_fields):
            logger.error("SMTP configuration is incomplete")
            return False
        
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = message.subject
            msg['From'] = self._sender_email
            msg['To'] = message.to
            
            part1 = MIMEText(message.body_text, 'plain', 'utf-8')
            part2 = MIMEText(message.body_html, 'html', 'utf-8')
            
            msg.attach(part1)
            msg.attach(part2)
            
            with smtplib.SMTP(self._smtp_host, self._smtp_port) as server:
                server.starttls()
                server.login(self._smtp_username, self._smtp_password)
                server.sendmail(self._sender_email, message.to, msg.as_string())
            
            logger.info("Email sent via SMTP to %s", message.to)
            return True
            
        except Exception as e:
            logger.error("Failed to send email via SMTP to %s: %s", message.to, e)
            return False

    async def send_email_acs(self, message: EmailMessage) -> bool:
        """Azure Communication Services를 통해 이메일을 전송한다.

        Args:
            message: 전송할 EmailMessage.

        Returns:
            전송 성공 시 True.
        """
        if not self._acs_connection_string:
            logger.error("ACS connection string is not configured")
            return False
        
        try:
            from azure.communication.email import EmailClient
            
            client = EmailClient.from_connection_string(self._acs_connection_string)
            
            email_message = {
                "senderAddress": self._sender_email,
                "recipients": {
                    "to": [{"address": message.to}]
                },
                "content": {
                    "subject": message.subject,
                    "plainText": message.body_text,
                    "html": message.body_html
                }
            }
            
            poller = client.begin_send(email_message)
            result = poller.result()
            
            logger.info(
                "Email sent via ACS to %s, message_id: %s",
                message.to, result.get('id')
            )
            return True
            
        except ImportError:
            logger.error("azure-communication-email package is not installed")
            return False
        except Exception as e:
            logger.error("Failed to send email via ACS to %s: %s", message.to, e)
            return False

    async def send_credentials_email(
        self,
        participant: dict,
        workshop_name: str,
    ) -> bool:
        """참가자에게 자격 증명 이메일을 전송한다.

        ACS가 설정되어 있으면 ACS를, 그 다음 SMTP를 시도한다.

        Args:
            participant: 참가자 데이터.
            workshop_name: 워크샵 이름.

        Returns:
            전송 성공 시 True.
        """
        message = self._generate_credential_email(participant, workshop_name)
        return await self._send_email(message)

    async def send_invitation_email(
        self,
        email: str,
        role: str,
        inviter_name: str,
        portal_url: str,
    ) -> bool:
        """포털 초대 이메일을 전송한다.

        Args:
            email: 초대할 사용자 이메일.
            role: 부여된 역할 ("admin" 또는 "user").
            inviter_name: 초대하는 관리자 이름.
            portal_url: 포털 접속 URL.

        Returns:
            전송 성공 시 True.
        """
        role_label = "관리자" if role == "admin" else "사용자"
        template_context = {
            "email": email,
            "role_label": role_label,
            "inviter_name": inviter_name or "관리자",
            "portal_url": portal_url,
        }

        html_template = _jinja_env.get_template("invitation_email.html")
        text_template = _jinja_env.get_template("invitation_email.txt")

        message = EmailMessage(
            to=email,
            subject="[Azure Workshop Portal] 포털 초대",
            body_html=html_template.render(**template_context),
            body_text=text_template.render(**template_context),
        )
        return await self._send_email(message)

    async def _send_email(self, message: EmailMessage) -> bool:
        """설정된 제공자(ACS 또는 SMTP)를 통해 이메일을 전송한다.

        Args:
            message: 전송할 EmailMessage.

        Returns:
            전송 성공 시 True.
        """
        if self._acs_connection_string:
            return await self.send_email_acs(message)
        elif self._smtp_host:
            return await self.send_email_smtp(message)
        else:
            logger.error("No email provider configured (ACS or SMTP)")
            return False

    async def send_credentials_bulk(
        self,
        participants: list[dict],
        workshop_name: str,
    ) -> dict[str, bool]:
        """여러 참가자에게 자격 증명 이메일을 순차 전송한다.

        Rate limiting을 위해 각 전송 사이에 지연을 둔다.

        Args:
            participants: 참가자 데이터 목록.
            workshop_name: 워크샵 이름.

        Returns:
            이메일 주소를 키로, 전송 성공 여부를 값으로 가진 딕셔너리.
        """
        results = {}

        for participant in participants:
            email = participant.get("email", "")
            success = await self.send_credentials_email(participant, workshop_name)
            results[email] = success
            await asyncio.sleep(_SEND_DELAY_SECONDS)

        successful = sum(1 for v in results.values() if v)
        logger.info(
            "Sent %d/%d credential emails for workshop: %s",
            successful, len(participants), workshop_name
        )
        
        return results


@lru_cache(maxsize=1)
def get_email_service() -> EmailService:
    """EmailService 싱글턴 인스턴스를 반환한다."""
    return EmailService()


email_service = get_email_service()
