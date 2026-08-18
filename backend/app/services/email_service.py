from typing import Any
import httpx
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
    """Service for dispatching transactional emails via Resend HTTP API."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def send_assessment_invitation(
        self,
        candidate_name: str,
        candidate_email: str,
        assessment_link: str,
        requisition_ref: str,
    ) -> None:
        if not self.settings.ENABLE_ASSESSMENT_EMAILS:
            logger.info(
                "[ASSESSMENT_EMAIL] assessment email delivery disabled by configuration",
                candidate_email=mask_email(candidate_email),
            )
            return

        api_key = self.settings.RESEND_API_KEY
        if not api_key:
            logger.warning(
                "[ASSESSMENT_EMAIL] RESEND_API_KEY is not configured; skipping email delivery",
                candidate_email=mask_email(candidate_email),
            )
            return

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
        
        # HTML template
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

        # Plain text template fallback
        text_content = (
            f"Dear {candidate_name},\n\n"
            f"You have been invited to complete a technical assessment for requisition {requisition_ref}.\n\n"
            f"Please use the following link to start your assessment:\n"
            f"{assessment_link}\n\n"
            f"Thank you,\nRecruitment Team"
        )

        payload = {
            "from": self.settings.RESEND_FROM_EMAIL,
            "to": [candidate_email.strip()],
            "subject": subject,
            "html": html_content,
            "text": text_content,
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        logger.info(
            "[ASSESSMENT_EMAIL] dispatching assessment email",
            candidate_email=mask_email(candidate_email),
            requisition_ref=requisition_ref,
        )

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post("https://api.resend.com/emails", json=payload, headers=headers)
                if resp.status_code >= 400:
                    logger.warning(
                        "[ASSESSMENT_EMAIL] resend api returned error status",
                        status_code=resp.status_code,
                        candidate_email=mask_email(candidate_email),
                    )
                    raise RuntimeError(f"Resend API error status {resp.status_code}: {resp.text}")
                logger.info(
                    "[ASSESSMENT_EMAIL] assessment email sent successfully",
                    candidate_email=mask_email(candidate_email),
                    status_code=resp.status_code,
                )
        except Exception as exc:
            logger.warning(
                "[ASSESSMENT_EMAIL] email delivery exception",
                candidate_email=mask_email(candidate_email),
                error=str(exc),
            )
            raise
