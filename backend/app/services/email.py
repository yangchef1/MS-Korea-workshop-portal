"""Email service for sending workshop credentials to participants.

Supports multiple email providers:
- Azure Communication Services (recommended for Azure environments)
- SMTP (fallback for other environments)
"""
import logging
import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import lru_cache
from typing import List, Dict

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class EmailMessage:
    """Email message structure"""
    to: str
    subject: str
    body_html: str
    body_text: str


class EmailService:
    """Service for sending emails to workshop participants"""

    def __init__(self):
        """Initialize email service based on configuration"""
        self._sender_email = getattr(settings, 'email_sender', None)
        self._smtp_host = getattr(settings, 'smtp_host', None)
        self._smtp_port = getattr(settings, 'smtp_port', 587)
        self._smtp_username = getattr(settings, 'smtp_username', None)
        self._smtp_password = getattr(settings, 'smtp_password', None)
        self._acs_connection_string = getattr(settings, 'acs_connection_string', None)
        
        logger.info("Initialized Email service")

    def _generate_credential_email(
        self,
        participant: Dict,
        workshop_name: str
    ) -> EmailMessage:
        """
        Generate credential email for a participant
        
        Args:
            participant: Participant data with email, upn, password, etc.
            workshop_name: Name of the workshop
            
        Returns:
            EmailMessage with HTML and text content
        """
        email = participant.get('email', '')
        alias = participant.get('alias', '')
        upn = participant.get('upn', '')
        password = participant.get('password', '')
        subscription_id = participant.get('subscription_id', '')
        resource_group = participant.get('resource_group', '')
        
        subject = f"[{workshop_name}] Azure Workshop 계정 정보"
        
        # Use .format() instead of f-string to avoid issues with CSS braces
        body_html = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background: linear-gradient(135deg, #0078d4 0%, #00bcf2 100%); color: white; padding: 30px; text-align: center; border-radius: 8px 8px 0 0; }
        .content { background: #f9f9f9; padding: 30px; border-radius: 0 0 8px 8px; }
        .credential-box { background: white; border: 1px solid #e1e1e1; border-radius: 8px; padding: 20px; margin: 20px 0; }
        .credential-item { margin: 15px 0; }
        .credential-label { font-weight: 600; color: #666; font-size: 12px; text-transform: uppercase; }
        .credential-value { font-family: 'Consolas', monospace; background: #f0f0f0; padding: 10px; border-radius: 4px; margin-top: 5px; word-break: break-all; }
        .warning { background: #fff4ce; border-left: 4px solid #ffc107; padding: 15px; margin: 20px 0; }
        .portal-link { display: inline-block; background: #0078d4; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; margin-top: 20px; }
        .portal-link:hover { background: #106ebe; }
        .footer { text-align: center; margin-top: 30px; color: #666; font-size: 12px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎓 {workshop_name}</h1>
            <p>Azure Workshop 계정 정보</p>
        </div>
        <div class="content">
            <p>안녕하세요, <strong>{alias}</strong>님!</p>
            <p>Azure Workshop에 참가해 주셔서 감사합니다. 아래 계정 정보로 Azure Portal에 로그인하실 수 있습니다.</p>
            
            <div class="credential-box">
                <div class="credential-item">
                    <div class="credential-label">로그인 ID (UPN)</div>
                    <div class="credential-value">{upn}</div>
                </div>
                <div class="credential-item">
                    <div class="credential-label">임시 비밀번호</div>
                    <div class="credential-value">{password}</div>
                </div>
                <div class="credential-item">
                    <div class="credential-label">할당된 Subscription ID</div>
                    <div class="credential-value">{subscription_id}</div>
                </div>
                <div class="credential-item">
                    <div class="credential-label">Resource Group</div>
                    <div class="credential-value">{resource_group}</div>
                </div>
            </div>
            
            <div class="warning">
                <strong>⚠️ 중요:</strong> 첫 로그인 시 비밀번호를 변경해야 합니다. 안전한 비밀번호를 사용해 주세요.
            </div>
            
            <center>
                <a href="https://portal.azure.com" class="portal-link">Azure Portal 접속하기 →</a>
            </center>
            
            <div class="footer">
                <p>문의사항이 있으시면 워크샵 진행자에게 연락해 주세요.</p>
                <p>© Microsoft Azure Workshop Portal</p>
            </div>
        </div>
    </div>
</body>
</html>
""".format(
            workshop_name=workshop_name,
            alias=alias,
            upn=upn,
            password=password,
            subscription_id=subscription_id,
            resource_group=resource_group
        )
        
        body_text = f"""
{workshop_name} - Azure Workshop 계정 정보

안녕하세요, {alias}님!

Azure Workshop에 참가해 주셔서 감사합니다. 아래 계정 정보로 Azure Portal에 로그인하실 수 있습니다.

=== 계정 정보 ===
로그인 ID (UPN): {upn}
임시 비밀번호: {password}
할당된 Subscription ID: {subscription_id}
Resource Group: {resource_group}

⚠️ 중요: 첫 로그인 시 비밀번호를 변경해야 합니다.

Azure Portal: https://portal.azure.com

문의사항이 있으시면 워크샵 진행자에게 연락해 주세요.
"""
        
        return EmailMessage(
            to=email,
            subject=subject,
            body_html=body_html,
            body_text=body_text
        )

    async def send_email_smtp(self, message: EmailMessage) -> bool:
        """Send email via SMTP.
        
        Args:
            message: EmailMessage to send
            
        Returns:
            True if sent successfully
        """
        if not all([
            self._smtp_host, self._smtp_username,
            self._smtp_password, self._sender_email
        ]):
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
        """Send email via Azure Communication Services.
        
        Args:
            message: EmailMessage to send
            
        Returns:
            True if sent successfully
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
        participant: Dict,
        workshop_name: str
    ) -> bool:
        """Send credential email to a participant.
        
        Args:
            participant: Participant data
            workshop_name: Workshop name
            
        Returns:
            True if sent successfully
        """
        message = self._generate_credential_email(participant, workshop_name)
        
        if self._acs_connection_string:
            return await self.send_email_acs(message)
        elif self._smtp_host:
            return await self.send_email_smtp(message)
        else:
            logger.error("No email provider configured (ACS or SMTP)")
            return False

    async def send_credentials_bulk(
        self,
        participants: List[Dict],
        workshop_name: str
    ) -> Dict[str, bool]:
        """
        Send credential emails to multiple participants
        
        Args:
            participants: List of participant data
            workshop_name: Workshop name
            
        Returns:
            Dictionary mapping email to send status
        """
        import asyncio
        
        results = {}
        
        for participant in participants:
            email = participant.get('email', '')
            success = await self.send_credentials_email(participant, workshop_name)
            results[email] = success
            
            # Small delay to avoid rate limiting
            await asyncio.sleep(0.5)
        
        successful = sum(1 for v in results.values() if v)
        logger.info(
            "Sent %d/%d credential emails for workshop: %s",
            successful, len(participants), workshop_name
        )
        
        return results


@lru_cache(maxsize=1)
def get_email_service() -> EmailService:
    """Get the EmailService singleton instance."""
    return EmailService()


email_service = get_email_service()
