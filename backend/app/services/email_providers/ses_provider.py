import asyncio
import smtplib
from email.header import Header
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid
from email import encoders
import structlog

from app.core.config import Settings, get_settings
from app.services.email_providers.base import BaseEmailProvider
from app.services.email_providers.gmail_provider import mask_email

logger = structlog.get_logger(__name__)


class SESProvider(BaseEmailProvider):
    """Amazon Simple Email Service (SES) SMTP provider implementation.

    Sends transactional emails through Amazon SES SMTP interface using
    STARTTLS (Port 587 / 25) or direct SSL/TLS (Port 465).
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def _get_config(self) -> dict:
        """Resolve SES SMTP configuration parameters from settings."""
        host = (
            getattr(self.settings, "SES_SMTP_HOST", None)
            or getattr(self.settings, "SMTP_HOST", None)
            or ""
        ).strip()
        port = int(
            getattr(self.settings, "SES_SMTP_PORT", None)
            or getattr(self.settings, "SMTP_PORT", 587)
        )
        username = (
            getattr(self.settings, "SES_SMTP_USERNAME", None)
            or getattr(self.settings, "SMTP_USERNAME", None)
            or ""
        ).strip()
        password = (
            getattr(self.settings, "SES_SMTP_PASSWORD", None)
            or getattr(self.settings, "SMTP_PASSWORD", None)
            or ""
        ).strip()
        from_email = (
            getattr(self.settings, "SES_FROM_EMAIL", None)
            or getattr(self.settings, "SMTP_FROM_EMAIL", None)
            or ""
        ).strip()
        from_name = (
            getattr(self.settings, "SMTP_FROM_NAME", None)
            or "AI Resume Screener"
        ).strip()
        use_tls = bool(getattr(self.settings, "SMTP_USE_TLS", True))
        use_ssl = bool(getattr(self.settings, "SMTP_USE_SSL", False) or port == 465)

        return {
            "host": host,
            "port": port,
            "username": username,
            "password": password,
            "from_email": from_email,
            "from_name": from_name,
            "use_tls": use_tls,
            "use_ssl": use_ssl,
        }

    async def test_connection(self) -> dict:
        """Verify SMTP connectivity and authentication with Amazon SES."""
        cfg = self._get_config()
        if not cfg["host"]:
            logger.warning("[SES_PROVIDER] connection test failed: host is not configured")
            return {
                "success": False,
                "error": "SMTP_HOST or SES_SMTP_HOST is not configured in .env",
            }
        if not cfg["username"] or not cfg["password"]:
            logger.warning("[SES_PROVIDER] connection test failed: credentials are missing")
            return {
                "success": False,
                "error": "SES SMTP credentials (username/password) are missing in .env",
            }

        def _test_sync() -> None:
            logger.info(
                "[SES_PROVIDER] connecting to Amazon SES SMTP endpoint for verification",
                host=cfg["host"],
                port=cfg["port"],
                use_ssl=cfg["use_ssl"],
                use_tls=cfg["use_tls"],
            )
            if cfg["use_ssl"]:
                server = smtplib.SMTP_SSL(host=cfg["host"], port=cfg["port"], timeout=15)
            else:
                server = smtplib.SMTP(host=cfg["host"], port=cfg["port"], timeout=15)

            with server:
                server.ehlo()
                if cfg["use_tls"] and not cfg["use_ssl"]:
                    server.starttls()
                    server.ehlo()
                logger.info(
                    "[SES_PROVIDER] authenticating with Amazon SES",
                    host=cfg["host"],
                    username=mask_email(cfg["username"]),
                )
                server.login(cfg["username"], cfg["password"])
                logger.info("[SES_PROVIDER] Amazon SES SMTP authentication successful")

        try:
            await asyncio.to_thread(_test_sync)
            logger.info(
                "[SES_PROVIDER] SMTP connectivity and authentication verified successfully",
                host=cfg["host"],
                port=cfg["port"],
                username=mask_email(cfg["username"]),
                from_email=mask_email(cfg["from_email"]),
            )
            return {
                "success": True,
                "message": f"Successfully connected and authenticated with Amazon SES at {cfg['host']}:{cfg['port']}.",
                "host": cfg["host"],
                "port": cfg["port"],
                "from_email": cfg["from_email"],
            }
        except smtplib.SMTPAuthenticationError as exc:
            err_msg = f"SES SMTP authentication failed. Check SES SMTP username & password in .env: {exc}"
            logger.error("[SES_PROVIDER] authentication error", host=cfg["host"], error=str(exc))
            return {"success": False, "error": err_msg, "host": cfg["host"], "port": cfg["port"]}
        except Exception as exc:
            err_msg = f"Failed to connect to Amazon SES SMTP endpoint: {exc}"
            logger.error("[SES_PROVIDER] connection error", host=cfg["host"], error=str(exc))
            return {"success": False, "error": err_msg, "host": cfg["host"], "port": cfg["port"]}

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
        """Send an email using Amazon SES SMTP endpoint."""
        if not getattr(self.settings, "ENABLE_ASSESSMENT_EMAILS", True):
            logger.info(
                "[SES_PROVIDER] email delivery disabled by ENABLE_ASSESSMENT_EMAILS configuration",
                to_email=mask_email(to_email),
            )
            return False

        cfg = self._get_config()
        if not cfg["host"]:
            logger.warning(
                "[SES_PROVIDER] SMTP_HOST / SES_SMTP_HOST is not configured; skipping email delivery",
                to_email=mask_email(to_email),
            )
            return False

        if not cfg["from_email"]:
            logger.warning(
                "[SES_PROVIDER] SMTP_FROM_EMAIL / SES_FROM_EMAIL is not configured; skipping delivery",
                to_email=mask_email(to_email),
            )
            return False

        if not to_email or not to_email.strip():
            logger.warning("[SES_PROVIDER] missing recipient email address; skipping delivery")
            return False

        # Build RFC-compliant MIME message
        msg = MIMEMultipart("mixed")
        from_display = formataddr((str(Header(cfg["from_name"], "utf-8")), cfg["from_email"]))
        msg["From"] = from_display
        msg["To"] = to_email.strip()
        msg["Subject"] = Header(subject, "utf-8").encode()
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain=cfg["from_email"].split("@")[-1] if "@" in cfg["from_email"] else None)

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

        # Alternative body (text + html)
        body_part = MIMEMultipart("alternative")
        body_part.attach(MIMEText(body_text, "plain", "utf-8"))
        if body_html:
            body_part.attach(MIMEText(body_html, "html", "utf-8"))
        msg.attach(body_part)

        # Attachments
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
            logger.info(
                "[SES_PROVIDER] opening SMTP connection to Amazon SES",
                smtp_host=cfg["host"],
                smtp_port=cfg["port"],
                use_ssl=cfg["use_ssl"],
                use_tls=cfg["use_tls"],
            )
            if cfg["use_ssl"]:
                server = smtplib.SMTP_SSL(host=cfg["host"], port=cfg["port"], timeout=20)
            else:
                server = smtplib.SMTP(host=cfg["host"], port=cfg["port"], timeout=20)

            with server:
                server.ehlo()
                if cfg["use_tls"] and not cfg["use_ssl"]:
                    server.starttls()
                    server.ehlo()
                if cfg["username"] and cfg["password"]:
                    logger.info(
                        "[SES_PROVIDER] authenticating with Amazon SES credentials",
                        username=mask_email(cfg["username"]),
                    )
                    server.login(cfg["username"], cfg["password"])
                logger.info(
                    "[SES_PROVIDER] dispatching MIME message to Amazon SES",
                    from_email=mask_email(cfg["from_email"]),
                    to_email=mask_email(to_email),
                    recipient_count=len(recipients),
                )
                server.send_message(msg, from_addr=cfg["from_email"], to_addrs=recipients)

        try:
            await asyncio.to_thread(_send_sync)
            logger.info(
                "[SES_PROVIDER] email sent successfully via Amazon SES SMTP",
                to_email=mask_email(to_email),
                from_email=mask_email(cfg["from_email"]),
                subject=subject,
                smtp_host=cfg["host"],
            )
            return True
        except smtplib.SMTPAuthenticationError as exc:
            logger.error(
                "[SES_PROVIDER] Amazon SES SMTP authentication failed (check username and password in .env)",
                to_email=mask_email(to_email),
                smtp_host=cfg["host"],
                error=str(exc),
            )
            raise ValueError(f"Amazon SES SMTP authentication failed: {exc}") from exc
        except smtplib.SMTPSenderRefused as exc:
            logger.error(
                "[SES_PROVIDER] Amazon SES sender rejected (ensure From Address is verified in AWS SES console)",
                from_email=mask_email(cfg["from_email"]),
                smtp_host=cfg["host"],
                error=str(exc),
            )
            raise ValueError(f"Amazon SES sender rejected '{cfg['from_email']}': {exc}") from exc
        except smtplib.SMTPRecipientsRefused as exc:
            logger.error(
                "[SES_PROVIDER] Amazon SES recipient rejected (if AWS SES account is in sandbox mode, the recipient email address must be verified)",
                to_email=mask_email(to_email),
                smtp_host=cfg["host"],
                error=str(exc),
            )
            raise ValueError(f"Amazon SES recipient rejected '{to_email}': {exc}") from exc
        except smtplib.SMTPException as exc:
            logger.error(
                "[SES_PROVIDER] Amazon SES SMTP protocol error during email dispatch",
                to_email=mask_email(to_email),
                smtp_host=cfg["host"],
                error=str(exc),
            )
            raise ValueError(f"Amazon SES SMTP error: {exc}") from exc
        except Exception as exc:
            logger.error(
                "[SES_PROVIDER] unexpected exception during Amazon SES email dispatch",
                to_email=mask_email(to_email),
                smtp_host=cfg["host"],
                error=str(exc),
            )
            raise
