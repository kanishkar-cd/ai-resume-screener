from unittest.mock import MagicMock, patch
import pytest
import smtplib
from app.services.email_service import EmailService


class DummySMTPSettings:
    ENABLE_ASSESSMENT_EMAILS = True
    SMTP_HOST = "smtp.example.com"
    SMTP_PORT = 587
    SMTP_USERNAME = "kanishkar@clouddestinations.com"
    SMTP_PASSWORD = "test_password_123"
    SMTP_USE_TLS = True
    SMTP_USE_SSL = False
    SMTP_FROM_EMAIL = "kanishkar@clouddestinations.com"
    SMTP_FROM_NAME = "AI Resume Screener"
    DEFAULT_EMAIL_PROVIDER = "ses"


@pytest.mark.asyncio
async def test_send_email_smtp_success():
    """Verify that send_email connects via smtplib, enables STARTTLS, logs in, and sends message."""
    settings = DummySMTPSettings()
    email_service = EmailService(settings=settings)

    mock_smtp_instance = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_smtp_instance) as mock_smtp_cls:
        # Enable context manager return
        mock_smtp_instance.__enter__.return_value = mock_smtp_instance

        success = await email_service.send_email(
            to_email="candidate@example.com",
            subject="Test Subject",
            body_text="Test Body",
            body_html="<p>Test Body</p>",
            provider="ses",
        )

        assert success is True
        mock_smtp_cls.assert_called_once_with(host="smtp.example.com", port=587, timeout=20)
        mock_smtp_instance.starttls.assert_called_once()
        mock_smtp_instance.login.assert_called_once_with("kanishkar@clouddestinations.com", "test_password_123")
        mock_smtp_instance.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_send_email_disabled_by_config():
    """Verify that email delivery is skipped when ENABLE_ASSESSMENT_EMAILS is false."""
    class DisabledSettings(DummySMTPSettings):
        ENABLE_ASSESSMENT_EMAILS = False

    email_service = EmailService(settings=DisabledSettings())
    success = await email_service.send_email(
        to_email="candidate@example.com",
        subject="Test",
        body_text="Test",
    )
    assert success is False


@pytest.mark.asyncio
async def test_send_email_missing_host():
    """Verify that email delivery is skipped when SMTP_HOST is not configured."""
    class NoHostSettings(DummySMTPSettings):
        SMTP_HOST = None
        SES_SMTP_HOST = None

    email_service = EmailService(settings=NoHostSettings())
    success = await email_service.send_email(
        to_email="candidate@example.com",
        subject="Test",
        body_text="Test",
    )
    assert success is False


@pytest.mark.asyncio
async def test_send_email_smtp_exception():
    """Verify that SMTP exceptions are caught and raised gracefully."""
    settings = DummySMTPSettings()
    email_service = EmailService(settings=settings)

    mock_smtp_instance = MagicMock()
    mock_smtp_instance.__enter__.return_value = mock_smtp_instance
    mock_smtp_instance.send_message.side_effect = smtplib.SMTPException("SMTP Auth Error")

    with patch("smtplib.SMTP", return_value=mock_smtp_instance):
        with pytest.raises(Exception):
            await email_service.send_email(
                to_email="candidate@example.com",
                subject="Test",
                body_text="Test",
            )
