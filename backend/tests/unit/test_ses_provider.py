from unittest.mock import MagicMock, patch
import pytest
import smtplib

from app.services.email_service import EmailService
from app.services.email_providers.ses_provider import SESProvider


class DummySESSettings:
    ENABLE_ASSESSMENT_EMAILS = True
    SMTP_HOST = "email-smtp.us-east-1.amazonaws.com"
    SMTP_PORT = 587
    SMTP_USERNAME = "AKIAIOSFODNN7EXAMPLE"
    SMTP_PASSWORD = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    SMTP_USE_TLS = True
    SMTP_USE_SSL = False
    SMTP_FROM_EMAIL = "verified-sender@example.com"
    SMTP_FROM_NAME = "AI Resume Screener"
    DEFAULT_EMAIL_PROVIDER = "ses"


@pytest.mark.asyncio
async def test_ses_provider_send_email_starttls_success():
    """Verify that SESProvider connects via SMTP with STARTTLS, logs in, and sends message."""
    settings = DummySESSettings()
    provider = SESProvider(settings=settings)

    mock_smtp_instance = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_smtp_instance) as mock_smtp_cls:
        mock_smtp_instance.__enter__.return_value = mock_smtp_instance

        success = await provider.send_email(
            to_email="candidate@example.com",
            subject="Technical Assessment Invitation",
            body_text="Please start your technical assessment.",
            body_html="<p>Please start your technical assessment.</p>",
        )

        assert success is True
        mock_smtp_cls.assert_called_once_with(host="email-smtp.us-east-1.amazonaws.com", port=587, timeout=20)
        mock_smtp_instance.starttls.assert_called_once()
        mock_smtp_instance.login.assert_called_once_with(
            "AKIAIOSFODNN7EXAMPLE",
            "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        )
        mock_smtp_instance.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_ses_provider_send_email_ssl_port_465():
    """Verify that SESProvider uses SMTP_SSL when port is 465 or use_ssl is enabled."""
    class SSLSettings(DummySESSettings):
        SMTP_PORT = 465
        SMTP_USE_SSL = True

    settings = SSLSettings()
    provider = SESProvider(settings=settings)

    mock_ssl_instance = MagicMock()
    with patch("smtplib.SMTP_SSL", return_value=mock_ssl_instance) as mock_ssl_cls:
        mock_ssl_instance.__enter__.return_value = mock_ssl_instance

        success = await provider.send_email(
            to_email="candidate@example.com",
            subject="SSL Assessment",
            body_text="SSL Body",
        )

        assert success is True
        mock_ssl_cls.assert_called_once_with(host="email-smtp.us-east-1.amazonaws.com", port=465, timeout=20)
        mock_ssl_instance.login.assert_called_once()
        mock_ssl_instance.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_ses_provider_test_connection_success():
    """Verify that test_connection performs EHLO, STARTTLS, and login successfully."""
    settings = DummySESSettings()
    provider = SESProvider(settings=settings)

    mock_smtp_instance = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_smtp_instance):
        mock_smtp_instance.__enter__.return_value = mock_smtp_instance

        result = await provider.test_connection()
        assert result["success"] is True
        assert "Successfully connected and authenticated" in result["message"]
        mock_smtp_instance.starttls.assert_called_once()
        mock_smtp_instance.login.assert_called_once()


@pytest.mark.asyncio
async def test_ses_provider_test_connection_auth_error():
    """Verify that authentication failures return structured error details."""
    settings = DummySESSettings()
    provider = SESProvider(settings=settings)

    mock_smtp_instance = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_smtp_instance):
        mock_smtp_instance.__enter__.return_value = mock_smtp_instance
        mock_smtp_instance.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Authentication Credentials Invalid")

        result = await provider.test_connection()
        assert result["success"] is False
        assert "SES SMTP authentication failed" in result["error"]


@pytest.mark.asyncio
async def test_email_service_dispatches_via_ses():
    """Verify that EmailService defaults to SES and dispatches correctly."""
    settings = DummySESSettings()
    email_service = EmailService(settings=settings)

    mock_smtp_instance = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_smtp_instance):
        mock_smtp_instance.__enter__.return_value = mock_smtp_instance

        success = await email_service.send_email(
            to_email="applicant@example.com",
            subject="Your Application",
            body_text="Welcome to the team",
            provider="ses",
        )

        assert success is True
        mock_smtp_instance.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_email_service_send_assessment_invitation():
    """Verify that send_assessment_invitation formats HTML and calls send_email."""
    settings = DummySESSettings()
    email_service = EmailService(settings=settings)

    mock_smtp_instance = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_smtp_instance):
        mock_smtp_instance.__enter__.return_value = mock_smtp_instance

        await email_service.send_assessment_invitation(
            candidate_name="Jane Doe",
            candidate_email="jane.doe@example.com",
            assessment_link="https://app.cdrecruit.com/assessment/xyz123",
            requisition_ref="REQ-2026-SWE",
            provider="ses",
        )

        mock_smtp_instance.send_message.assert_called_once()
