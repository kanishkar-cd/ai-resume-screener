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


def is_retryable_smtp_error(exc: Exception) -> bool:
    """Classify whether an exception during SMTP email delivery is safe to retry."""
    # Permanent authentication failure - do not retry
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return False
    # Permanent recipient rejection (e.g. invalid email address / user unknown)
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return False
    # Permanent sender rejection
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return False
    # Permanent 5xx status codes
    if isinstance(exc, smtplib.SMTPResponseException) and 500 <= getattr(exc, "smtp_code", 0) < 600:
        return False
    # Programming / data / validation errors
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return False
    # Connection/network/timeout/socket/4xx temporary errors are retryable
    if isinstance(
        exc,
        (
            smtplib.SMTPServerDisconnected,
            smtplib.SMTPConnectError,
            smtplib.SMTPException,
            TimeoutError,
            OSError,
            ConnectionError,
        ),
    ):
        return True
    return False


class EmailService:
<<<<<<< Updated upstream
    """Service for dispatching transactional emails via Resend HTTP API."""
=======
    """Service for dispatching transactional emails via Python standard library smtplib with retries."""
>>>>>>> Stashed changes

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

<<<<<<< Updated upstream
=======
    async def send_email(
        self,
        to_email: str,
        subject: str,
        body_text: str,
        body_html: str | None = None,
    ) -> bool:
        """Send an email using Python's built-in smtplib with optional STARTTLS and exponential backoff retries."""
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

        max_retries = int(getattr(self.settings, "MAX_EMAIL_RETRIES", 3))
        base_delay = float(getattr(self.settings, "EMAIL_RETRY_BASE_DELAY", 2.0))
        max_attempts = max(1, max_retries + 1)

        for attempt in range(1, max_attempts + 1):
            logger.info(
                "[EMAIL_SERVICE] dispatching email via SMTP",
                to_email=mask_email(to_email),
                from_email=mask_email(from_email),
                smtp_host=smtp_host,
                smtp_port=smtp_port,
                use_tls=use_tls,
                attempt=attempt,
                max_attempts=max_attempts,
            )

            try:
                await asyncio.to_thread(_send_sync)
                logger.info(
                    "[EMAIL_SERVICE] email sent successfully via SMTP",
                    to_email=mask_email(to_email),
                    attempt=attempt,
                )
                return True
            except Exception as exc:
                retryable = is_retryable_smtp_error(exc)
                if not retryable or attempt >= max_attempts:
                    logger.warning(
                        "[EMAIL_SERVICE] email delivery failed permanently",
                        to_email=mask_email(to_email),
                        attempt=attempt,
                        max_attempts=max_attempts,
                        error_type=type(exc).__name__,
                        error=str(exc),
                        retryable=retryable,
                    )
                    raise

                delay = base_delay * (2 ** (attempt - 1))
                logger.info(
                    "[EMAIL_SERVICE] retrying email delivery after backoff",
                    to_email=mask_email(to_email),
                    attempt=attempt,
                    next_attempt=attempt + 1,
                    delay_seconds=delay,
                    error_type=type(exc).__name__,
                )
                await asyncio.sleep(delay)

        return False

>>>>>>> Stashed changes
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

<<<<<<< Updated upstream
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
=======
        subject = "You’ve Been Shortlisted – Software Engineering Assessment"

        html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; color: #0f172a; margin: 0; padding: 24px; }}
    .card {{ max-width: 580px; margin: 0 auto; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 16px; padding: 36px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
    .greeting {{ font-size: 16px; font-weight: 700; color: #0f172a; margin-bottom: 16px; }}
    .content {{ font-size: 14px; line-height: 1.65; color: #334155; margin-bottom: 20px; }}
    .btn-container {{ text-align: center; margin: 28px 0; }}
    .btn {{ display: inline-block; background-color: #2563eb; color: #ffffff !important; font-weight: 700; font-size: 15px; text-decoration: none; padding: 14px 32px; border-radius: 10px; }}
    .link-fallback {{ font-size: 13px; color: #64748b; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px; word-break: break-all; margin: 16px 0; }}
    .expiry-note {{ font-size: 13px; font-weight: 600; color: #b91c1c; background: #fef2f2; border-left: 4px solid #ef4444; padding: 12px 16px; border-radius: 4px; margin: 20px 0; }}
    .signoff {{ font-size: 14px; line-height: 1.6; color: #334155; margin-top: 24px; border-top: 1px solid #f1f5f9; padding-top: 20px; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="greeting">Hi {candidate_name},</div>
    <div class="content">
      <p>Congratulations! You have been successfully shortlisted for the Software Engineering role.</p>
      <p>Please complete your assessment using the link below:</p>
    </div>
    <div class="btn-container">
      <a href="{assessment_link}" class="btn" target="_blank">Test Link</a>
    </div>
    <div class="link-fallback">
      <strong>Test Link:</strong> <a href="{assessment_link}" style="color: #2563eb;">{assessment_link}</a>
    </div>
    <div class="expiry-note">
      Important: This link will expire in 24 hours. Please complete the assessment before it expires.
    </div>
    <div class="content">
      <p>Wishing you the very best, and good luck with your assessment!</p>
    </div>
    <div class="signoff">
      Best regards,<br>
      <strong>Talent Acquisition Team</strong>
    </div>
  </div>
</body>
</html>"""
>>>>>>> Stashed changes

        # Plain text template fallback
        text_content = (
            f"Hi {candidate_name},\n\n"
            f"Congratulations! You have been successfully shortlisted for the Software Engineering role.\n\n"
            f"Please complete your assessment using the link below:\n\n"
            f"Test Link: {assessment_link}\n\n"
            f"Important: This link will expire in 24 hours. Please complete the assessment before it expires.\n\n"
            f"Wishing you the very best, and good luck with your assessment!\n\n"
            f"Best regards,\n"
            f"Talent Acquisition Team"
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
