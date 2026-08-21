import asyncio
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import structlog

from app.core.config import Settings, get_settings

logger = structlog.get_logger(__name__)


def mask_email(email: str) -> str:
    """Mask email address for safe log output (e.g. j***e@example.com)."""
    if not email or "@" not in email:
        return "***"
    user, domain = email.split("@", 1)
    if len(user) <= 2:
        masked_user = user[0] + "*"
    else:
        masked_user = user[0] + "*" * (len(user) - 2) + user[-1]
    return f"{masked_user}@{domain}"


class EmailService:
    """Service for dispatching transactional emails via Python standard library smtplib."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def send_email(
        self,
        to_email: str,
        subject: str,
        body_text: str,
        body_html: str | None = None,
    ) -> bool:
        """Send an email using Python's built-in smtplib with optional STARTTLS."""
        if not getattr(self.settings, "ENABLE_ASSESSMENT_EMAILS", True):
            logger.info(
                "[EMAIL_SERVICE] email delivery disabled by configuration",
                to_email=mask_email(to_email),
            )
            return False

        smtp_host = getattr(self.settings, "SMTP_HOST", None)
        if not smtp_host or not smtp_host.strip():
            logger.warning(
                "[EMAIL_SERVICE] SMTP_HOST is not configured; skipping email delivery",
                to_email=mask_email(to_email),
            )
            return False

        from_email = getattr(self.settings, "SMTP_FROM_EMAIL", "kanishkar@clouddestinations.com")
        if not from_email or not from_email.strip():
            from_email = "kanishkar@clouddestinations.com"

        if not to_email or not to_email.strip():
            logger.warning("[EMAIL_SERVICE] missing recipient email address; skipping delivery")
            return False

        smtp_port = int(getattr(self.settings, "SMTP_PORT", 587))
        smtp_username = getattr(self.settings, "SMTP_USERNAME", None)
        smtp_password = getattr(self.settings, "SMTP_PASSWORD", None)
        use_tls = bool(getattr(self.settings, "SMTP_USE_TLS", True))

        msg = MIMEMultipart("alternative")
        msg["From"] = from_email.strip()
        msg["To"] = to_email.strip()
        msg["Subject"] = subject

        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        if body_html:
            msg.attach(MIMEText(body_html, "html", "utf-8"))

        def _send_sync() -> None:
            with smtplib.SMTP(host=smtp_host.strip(), port=smtp_port, timeout=10) as server:
                if use_tls:
                    server.starttls()
                if smtp_username and smtp_password:
                    server.login(smtp_username.strip(), smtp_password)
                server.send_message(msg)

        logger.info(
            "[EMAIL_SERVICE] dispatching email via SMTP",
            to_email=mask_email(to_email),
            from_email=mask_email(from_email),
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            use_tls=use_tls,
        )

        try:
            await asyncio.to_thread(_send_sync)
            logger.info(
                "[EMAIL_SERVICE] email sent successfully via SMTP",
                to_email=mask_email(to_email),
            )
            return True
        except smtplib.SMTPException as exc:
            logger.warning(
                "[EMAIL_SERVICE] SMTP protocol error during email delivery",
                to_email=mask_email(to_email),
                smtp_host=smtp_host,
                error=str(exc),
            )
            raise
        except Exception as exc:
            logger.warning(
                "[EMAIL_SERVICE] exception during SMTP email delivery",
                to_email=mask_email(to_email),
                error=str(exc),
            )
            raise

    async def send_assessment_invitation(
        self,
        candidate_name: str,
        candidate_email: str,
        assessment_link: str,
        requisition_ref: str,
    ) -> None:
        """Send a technical assessment invitation email to candidate."""
        if not candidate_email or not candidate_email.strip():
            logger.warning("[ASSESSMENT_EMAIL] missing candidate email address; skipping delivery")
            return

        if not assessment_link or not assessment_link.strip():
            logger.warning(
                "[ASSESSMENT_EMAIL] missing assessment link; skipping delivery",
                candidate_email=mask_email(candidate_email),
            )
            return

        subject = f"Action Required: Technical Assessment Invitation ({requisition_ref})"

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; color: #0f172a; margin: 0; padding: 24px; }}
            .card {{ max-width: 560px; margin: 0 auto; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 16px; padding: 32px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
            .header {{ font-size: 20px; font-weight: 800; color: #0f172a; margin-bottom: 8px; }}
            .subhead {{ font-size: 14px; color: #64748b; margin-bottom: 24px; }}
            .content {{ font-size: 14px; line-height: 1.6; color: #334155; margin-bottom: 24px; }}
            .btn-container {{ text-align: center; margin: 32px 0; }}
            .btn {{ display: inline-block; background-color: #2563eb; color: #ffffff !important; font-weight: 700; font-size: 14px; text-decoration: none; padding: 12px 28px; border-radius: 12px; }}
            .footer {{ font-size: 12px; color: #94a3b8; border-top: 1px solid #f1f5f9; padding-top: 16px; margin-top: 24px; }}
          </style>
        </head>
        <body>
          <div class="card">
            <div class="header">Technical Assessment Invitation</div>
            <div class="subhead">Requisition Ref: {requisition_ref}</div>
            <div class="content">
              <p>Dear {candidate_name},</p>
              <p>Congratulations! You have been selected for the next stage of our technical screening process for requisition <strong>{requisition_ref}</strong>.</p>
              <p>Please complete your assessment by clicking the button below:</p>
            </div>
            <div class="btn-container">
              <a href="{assessment_link}" class="btn" target="_blank">Start Assessment</a>
            </div>
            <div class="content">
              <p style="font-size: 12px; color: #64748b;">If the button above does not work, copy and paste this link into your browser:<br>
              <a href="{assessment_link}" style="color: #2563eb;">{assessment_link}</a></p>
            </div>
            <div class="footer">
              This is an automated invitation message. Please complete your assessment at your earliest convenience.
            </div>
          </div>
        </body>
        </html>
        """

        text_content = (
            f"Dear {candidate_name},\n\n"
            f"You have been invited to complete a technical assessment for requisition {requisition_ref}.\n\n"
            f"Please use the following link to start your assessment:\n"
            f"{assessment_link}\n\n"
            f"Thank you,\nRecruitment Team"
        )

        await self.send_email(
            to_email=candidate_email,
            subject=subject,
            body_text=text_content,
            body_html=html_content,
        )
