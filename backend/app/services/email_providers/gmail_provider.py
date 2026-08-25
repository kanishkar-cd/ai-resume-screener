import asyncio
import smtplib
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders
import structlog

from app.core.config import Settings, get_settings
from app.services.email_providers.base import BaseEmailProvider

logger = structlog.get_logger(__name__)


def mask_email(email: str) -> str:
    """Mask email address for safe log output."""
    if not email or "@" not in email:
        return "***"
    user, domain = email.split("@", 1)
    if len(user) <= 2:
        masked_user = user[0] + "*"
    else:
        masked_user = user[0] + "*" * (len(user) - 2) + user[-1]
    return f"{masked_user}@{domain}"


class GmailProvider(BaseEmailProvider):
    """Gmail / SMTP email provider implementation."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def send_email(
        self,
        to_email: str,
        subject: str,
        body_text: str,
        body_html: str | None = None,
        cc: list[str] | str | None = None,
        bcc: list[str] | str | None = None,
        attachments: list[dict] | None = None,
    ) -> bool:
        """Send an email using Python's built-in smtplib with optional STARTTLS."""
        if not getattr(self.settings, "ENABLE_ASSESSMENT_EMAILS", True):
            logger.info(
                "[GMAIL_PROVIDER] email delivery disabled by configuration",
                to_email=mask_email(to_email),
            )
            return False

        smtp_host = getattr(self.settings, "SMTP_HOST", None)
        if not smtp_host or not smtp_host.strip():
            logger.warning(
                "[GMAIL_PROVIDER] SMTP_HOST is not configured; skipping email delivery",
                to_email=mask_email(to_email),
            )
            return False

        from_email = getattr(self.settings, "SMTP_FROM_EMAIL", "kanishkar@clouddestinations.com")
        if not from_email or not from_email.strip():
            from_email = "kanishkar@clouddestinations.com"

        if not to_email or not to_email.strip():
            logger.warning("[GMAIL_PROVIDER] missing recipient email address; skipping delivery")
            return False

        smtp_port = int(getattr(self.settings, "SMTP_PORT", 587))
        smtp_username = getattr(self.settings, "SMTP_USERNAME", None)
        smtp_password = getattr(self.settings, "SMTP_PASSWORD", None)
        use_tls = bool(getattr(self.settings, "SMTP_USE_TLS", True))

        msg = MIMEMultipart("mixed")
        msg["From"] = from_email.strip()
        msg["To"] = to_email.strip()
        msg["Subject"] = subject

        cc_list: list[str] = []
        if isinstance(cc, str) and cc.strip():
            cc_list = [c.strip() for c in cc.split(",") if c.strip()]
        elif isinstance(cc, list):
            cc_list = [c.strip() for c in cc if c and c.strip()]

        bcc_list: list[str] = []
        if isinstance(bcc, str) and bcc.strip():
            bcc_list = [b.strip() for b in bcc.split(",") if b.strip()]
        elif isinstance(bcc, list):
            bcc_list = [b.strip() for b in bcc if b and b.strip()]

        if cc_list:
            msg["Cc"] = ", ".join(cc_list)

        body_part = MIMEMultipart("alternative")
        body_part.attach(MIMEText(body_text, "plain", "utf-8"))
        if body_html:
            body_part.attach(MIMEText(body_html, "html", "utf-8"))
        msg.attach(body_part)

        if attachments:
            for att in attachments:
                fname = att.get("filename", "attachment.dat")
                content_bytes = att.get("content_bytes")
                content_type = att.get("content_type", "application/octet-stream")
                if content_bytes:
                    maintype, _, subtype = content_type.partition("/")
                    part = MIMEBase(maintype or "application", subtype or "octet-stream")
                    part.set_payload(content_bytes)
                    encoders.encode_base64(part)
                    part.add_header("Content-Disposition", f'attachment; filename="{fname}"')
                    msg.attach(part)

        recipients = [to_email.strip()] + cc_list + bcc_list

        def _send_sync() -> None:
            with smtplib.SMTP(host=smtp_host.strip(), port=smtp_port, timeout=10) as server:
                if use_tls:
                    server.starttls()
                if smtp_username and smtp_password:
                    server.login(smtp_username.strip(), smtp_password)
                server.send_message(msg)

        logger.info(
            "[GMAIL_PROVIDER] dispatching email via SMTP",
            to_email=mask_email(to_email),
            from_email=mask_email(from_email),
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            use_tls=use_tls,
        )

        try:
            await asyncio.to_thread(_send_sync)
            logger.info(
                "[GMAIL_PROVIDER] email sent successfully via SMTP",
                to_email=mask_email(to_email),
            )
            return True
        except smtplib.SMTPException as exc:
            logger.warning(
                "[GMAIL_PROVIDER] SMTP protocol error during email delivery",
                to_email=mask_email(to_email),
                smtp_host=smtp_host,
                error=str(exc),
            )
            raise
        except Exception as exc:
            logger.warning(
                "[GMAIL_PROVIDER] exception during SMTP email delivery",
                to_email=mask_email(to_email),
                error=str(exc),
            )
            raise
