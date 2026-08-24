from abc import ABC, abstractmethod


class BaseEmailProvider(ABC):
    """Abstract base class defining interface for email providers."""

    @abstractmethod
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
        """Send an email to the designated recipient.

        Args:
            to_email: Target email address.
            subject: Email subject.
            body_text: Plain text content.
            body_html: Optional HTML content.
            cc: Optional CC recipient(s).
            bcc: Optional BCC recipient(s).
            attachments: Optional list of attachment dicts (e.g. filename, content_type, content_bytes).

        Returns:
            bool: True if sending succeeded, False otherwise.
        """
        pass
