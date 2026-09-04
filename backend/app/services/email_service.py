import structlog

from app.core.config import Settings, get_settings
from app.core.exceptions import ValidationException
from app.services.email_providers.base import BaseEmailProvider
from app.services.email_providers.gmail_provider import GmailProvider, mask_email
from app.services.email_providers.outlook_provider import OutlookProvider
from app.services.email_providers.ses_provider import SESProvider

logger = structlog.get_logger(__name__)


class EmailService:
    """Manager service for dispatching emails using configured providers (Amazon SES / SMTP / Gmail / Outlook)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        ses_provider = SESProvider(settings=self.settings)
        self.providers: dict[str, BaseEmailProvider] = {
            "ses": ses_provider,
            "smtp": ses_provider,
            "amazon_ses": ses_provider,
            "gmail": GmailProvider(settings=self.settings),
            "outlook": OutlookProvider(settings=self.settings),
        }

    def get_provider(self, provider_name: str | None = None) -> BaseEmailProvider:
        """Retrieve the specified email provider instance."""
        p_name = (provider_name or getattr(self.settings, "DEFAULT_EMAIL_PROVIDER", "ses")).strip().lower()
        if p_name not in self.providers:
            raise ValidationException(
                f"Unsupported email provider '{provider_name}'. Supported providers: ses, smtp, gmail, outlook."
            )
        return self.providers[p_name]

    async def test_connection(self, provider: str = "ses") -> dict:
        """Test SMTP connection and authentication with the specified provider."""
        provider_instance = self.get_provider(provider)
        if hasattr(provider_instance, "test_connection"):
            return await provider_instance.test_connection()
        return {
            "success": True,
            "message": f"Provider '{provider}' loaded successfully.",
        }

    async def send_email(
        self,
        to_email: str,
        subject: str,
        body_text: str,
        body_html: str | None = None,
        provider: str = "ses",
        cc: list[str] | str | None = None,
        bcc: list[str] | str | None = None,
        attachments: list[dict] | None = None,
    ) -> bool:
        """Send an email using the designated provider (ses, smtp, gmail, or outlook)."""
        provider_instance = self.get_provider(provider)
        return await provider_instance.send_email(
            to_email=to_email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            cc=cc,
            bcc=bcc,
            attachments=attachments,
        )

    async def send_assessment_invitation(
        self,
        candidate_name: str,
        candidate_email: str,
        assessment_link: str,
        requisition_ref: str,
        provider: str = "ses",
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
            provider=provider,
        )
