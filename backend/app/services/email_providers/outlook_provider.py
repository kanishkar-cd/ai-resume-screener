import base64
import time
import httpx
import structlog

from app.core.config import Settings, get_settings
from app.core.exceptions import AppException
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


class OutlookConfigException(AppException):
    """Exception raised when Outlook configuration or environment variables are missing."""

    status_code = 500
    default_message = "Outlook integration is missing required configuration."


class OutlookAuthenticationException(AppException):
    """Exception raised when Microsoft OAuth authentication fails."""

    status_code = 502
    default_message = "Failed to authenticate with Microsoft Graph API."


class OutlookSendMailException(AppException):
    """Exception raised when sending mail via Microsoft Graph API fails."""

    status_code = 502
    default_message = "Microsoft Graph API error while sending email."



class OutlookProvider(BaseEmailProvider):
    """Microsoft Outlook / Microsoft 365 email provider using Graph API and OAuth 2.0."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    async def _get_access_token(self, client: httpx.AsyncClient) -> str:
        """Obtain a valid access token using Microsoft OAuth 2.0 flow."""
        now = time.time()
        if self._access_token and now < (self._token_expires_at - 60):
            return self._access_token

        client_id = getattr(self.settings, "OUTLOOK_CLIENT_ID", None)
        client_secret = getattr(self.settings, "OUTLOOK_CLIENT_SECRET", None)
        tenant_id = getattr(self.settings, "OUTLOOK_TENANT_ID", "common") or "common"
        refresh_token = getattr(self.settings, "OUTLOOK_REFRESH_TOKEN", None)

        if not client_id or not client_id.strip():
            logger.warning("[OUTLOOK_PROVIDER] OUTLOOK_CLIENT_ID is not configured")
            raise OutlookConfigException("OUTLOOK_CLIENT_ID environment variable is missing.")

        token_url = f"https://login.microsoftonline.com/{tenant_id.strip()}/oauth2/v2.0/token"

        if refresh_token and refresh_token.strip():
            data = {
                "client_id": client_id.strip(),
                "grant_type": "refresh_token",
                "refresh_token": refresh_token.strip(),
                "scope": "https://graph.microsoft.com/.default offline_access Mail.Send",
            }
            if client_secret and client_secret.strip():
                data["client_secret"] = client_secret.strip()
        elif client_secret and client_secret.strip():
            data = {
                "client_id": client_id.strip(),
                "client_secret": client_secret.strip(),
                "grant_type": "client_credentials",
                "scope": "https://graph.microsoft.com/.default",
            }
        else:
            logger.warning("[OUTLOOK_PROVIDER] Neither OUTLOOK_CLIENT_SECRET nor OUTLOOK_REFRESH_TOKEN is set")
            raise OutlookConfigException("OUTLOOK_CLIENT_SECRET or OUTLOOK_REFRESH_TOKEN must be configured.")

        try:
            response = await client.post(token_url, data=data, timeout=10.0)
            if response.status_code != 200:
                logger.error(
                    "[OUTLOOK_PROVIDER] OAuth token endpoint request failed",
                    status_code=response.status_code,
                )
                raise OutlookAuthenticationException(
                    f"Microsoft OAuth token acquisition failed with status {response.status_code}."
                )

            token_data = response.json()
            access_token = token_data.get("access_token")
            expires_in = int(token_data.get("expires_in", 3600))

            if not access_token:
                raise OutlookAuthenticationException("OAuth response did not contain an access token.")

            self._access_token = access_token
            self._token_expires_at = now + expires_in
            return access_token

        except httpx.HTTPError as exc:
            logger.error("[OUTLOOK_PROVIDER] Network error during token request", error=str(exc))
            raise OutlookAuthenticationException(f"Network failure requesting OAuth token: {str(exc)}") from exc

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
        """Send an email using Microsoft Graph sendMail endpoint."""
        if not getattr(self.settings, "ENABLE_ASSESSMENT_EMAILS", True):
            logger.info(
                "[OUTLOOK_PROVIDER] email delivery disabled by configuration",
                to_email=mask_email(to_email),
            )
            return False

        sender_email = getattr(self.settings, "OUTLOOK_SENDER_EMAIL", "kanishkar@clouddestinations.com")
        if not sender_email or not sender_email.strip():
            sender_email = "kanishkar@clouddestinations.com"

        if not to_email or not to_email.strip():
            logger.warning("[OUTLOOK_PROVIDER] missing recipient email address; skipping delivery")
            return False

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

        to_recipients = [{"emailAddress": {"address": to_email.strip()}}]
        cc_recipients = [{"emailAddress": {"address": addr}} for addr in cc_list]
        bcc_recipients = [{"emailAddress": {"address": addr}} for addr in bcc_list]

        message_body = {
            "contentType": "HTML" if body_html else "Text",
            "content": body_html if body_html else body_text,
        }

        graph_attachments = []
        if attachments:
            for att in attachments:
                fname = att.get("filename", "attachment.dat")
                c_bytes = att.get("content_bytes", b"")
                c_type = att.get("content_type", "application/octet-stream")
                b64_content = base64.b64encode(c_bytes).decode("utf-8") if isinstance(c_bytes, bytes) else str(c_bytes)
                graph_attachments.append({
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": fname,
                    "contentType": c_type,
                    "contentBytes": b64_content,
                })

        message_payload = {
            "message": {
                "subject": subject,
                "body": message_body,
                "toRecipients": to_recipients,
                "ccRecipients": cc_recipients,
                "bccRecipients": bcc_recipients,
                "attachments": graph_attachments,
            },
            "saveToSentItems": True,
        }

        async with httpx.AsyncClient() as client:
            access_token = await self._get_access_token(client)

            # Use sendMail endpoint for user or /me
            send_url = f"https://graph.microsoft.com/v1.0/users/{sender_email.strip()}/sendMail"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }

            logger.info(
                "[OUTLOOK_PROVIDER] dispatching email via Microsoft Graph API",
                to_email=mask_email(to_email),
                sender_email=mask_email(sender_email),
            )

            try:
                response = await client.post(send_url, json=message_payload, headers=headers, timeout=15.0)
                if response.status_code in (202, 200, 204):
                    logger.info(
                        "[OUTLOOK_PROVIDER] email sent successfully via Microsoft Graph API",
                        to_email=mask_email(to_email),
                    )
                    return True
                elif response.status_code in (401, 403):
                    # Access token might have been invalidated, reset token cache
                    self._access_token = None
                    logger.error(
                        "[OUTLOOK_PROVIDER] Microsoft Graph authorization failure",
                        status_code=response.status_code,
                    )
                    raise OutlookAuthenticationException(
                        f"Microsoft Graph API authorization failed (status {response.status_code})."
                    )
                else:
                    logger.error(
                        "[OUTLOOK_PROVIDER] Microsoft Graph API sendMail failed",
                        status_code=response.status_code,
                    )
                    raise OutlookSendMailException(
                        f"Microsoft Graph sendMail failed with status code {response.status_code}."
                    )

            except httpx.HTTPError as exc:
                logger.error("[OUTLOOK_PROVIDER] network error during Graph sendMail", error=str(exc))
                raise OutlookSendMailException(f"Network error sending mail via Microsoft Graph: {str(exc)}") from exc
