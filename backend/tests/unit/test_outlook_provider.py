from unittest.mock import MagicMock, patch
import pytest
import httpx

from app.core.config import Settings
from app.services.email_providers.outlook_provider import (
    OutlookAuthenticationException,
    OutlookConfigException,
    OutlookProvider,
    OutlookSendMailException,
)
from app.services.email_service import EmailService


def create_test_settings(**kwargs) -> Settings:
    default_kwargs = {
        "ENABLE_ASSESSMENT_EMAILS": True,
        "OUTLOOK_CLIENT_ID": "test-client-id-123",
        "OUTLOOK_CLIENT_SECRET": "test-client-secret-456",
        "OUTLOOK_TENANT_ID": "common",
        "OUTLOOK_SENDER_EMAIL": "kanishkar@clouddestinations.com",
        "OUTLOOK_REFRESH_TOKEN": "test-refresh-token-789",
        "SMTP_HOST": "smtp.gmail.com",
        "SMTP_PORT": 587,
        "SMTP_USERNAME": "kanishkar@clouddestinations.com",
        "SMTP_PASSWORD": "test-gmail-password",
        "SMTP_USE_TLS": True,
        "SMTP_FROM_EMAIL": "kanishkar@clouddestinations.com",
    }
    default_kwargs.update(kwargs)
    return Settings(**default_kwargs)


@pytest.mark.asyncio
async def test_outlook_provider_successful_send():
    """Verify OutlookProvider acquires OAuth token and posts email payload to Graph API."""
    settings = create_test_settings()
    provider = OutlookProvider(settings=settings)

    mock_token_response = MagicMock()
    mock_token_response.status_code = 200
    mock_token_response.json.return_value = {
        "access_token": "mock_access_token_abc",
        "expires_in": 3600,
    }

    mock_send_response = MagicMock()
    mock_send_response.status_code = 202

    async def mock_post(url, **kwargs):
        if "oauth2/v2.0/token" in url:
            return mock_token_response
        elif "graph.microsoft.com" in url:
            assert kwargs["headers"]["Authorization"] == "Bearer mock_access_token_abc"
            payload = kwargs["json"]
            assert payload["message"]["subject"] == "Test Subject"
            assert payload["message"]["toRecipients"][0]["emailAddress"]["address"] == "candidate@example.com"
            return mock_send_response
        raise ValueError(f"Unexpected URL: {url}")

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        result = await provider.send_email(
            to_email="candidate@example.com",
            subject="Test Subject",
            body_text="Plain body",
            body_html="<p>HTML body</p>",
        )
        assert result is True


@pytest.mark.asyncio
async def test_outlook_provider_missing_client_id():
    """Verify exception when OUTLOOK_CLIENT_ID is missing."""
    settings = create_test_settings(OUTLOOK_CLIENT_ID="")
    provider = OutlookProvider(settings=settings)
    with pytest.raises(OutlookConfigException):
        async with httpx.AsyncClient() as client:
            await provider._get_access_token(client)


@pytest.mark.asyncio
async def test_outlook_provider_missing_secret_and_refresh_token():
    """Verify exception when both OUTLOOK_CLIENT_SECRET and OUTLOOK_REFRESH_TOKEN are missing."""
    settings = create_test_settings(OUTLOOK_CLIENT_SECRET="", OUTLOOK_REFRESH_TOKEN="")
    provider = OutlookProvider(settings=settings)
    with pytest.raises(OutlookConfigException):
        async with httpx.AsyncClient() as client:
            await provider._get_access_token(client)


@pytest.mark.asyncio
async def test_outlook_provider_oauth_token_failure():
    """Verify OutlookAuthenticationException when token endpoint returns non-200."""
    settings = create_test_settings()
    provider = OutlookProvider(settings=settings)

    mock_token_response = MagicMock()
    mock_token_response.status_code = 401

    async def mock_post(url, **kwargs):
        return mock_token_response

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        with pytest.raises(OutlookAuthenticationException):
            async with httpx.AsyncClient() as client:
                await provider._get_access_token(client)


@pytest.mark.asyncio
async def test_outlook_provider_graph_api_error():
    """Verify OutlookSendMailException when Graph sendMail returns 500 error."""
    settings = create_test_settings()
    provider = OutlookProvider(settings=settings)

    mock_token_response = MagicMock()
    mock_token_response.status_code = 200
    mock_token_response.json.return_value = {"access_token": "mock_token", "expires_in": 3600}

    mock_send_response = MagicMock()
    mock_send_response.status_code = 500

    async def mock_post(url, **kwargs):
        if "oauth2" in url:
            return mock_token_response
        return mock_send_response

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        with pytest.raises(OutlookSendMailException):
            await provider.send_email(
                to_email="candidate@outlook.com",
                subject="Test Subject",
                body_text="Test Body",
            )


# MATRIX TESTS (1. Gmail -> Gmail, 2. Gmail -> Outlook, 3. Outlook -> Gmail, 4. Outlook -> Outlook)

@pytest.mark.asyncio
async def test_matrix_gmail_sender_to_gmail_recipient():
    """1. Gmail sender -> Gmail recipient."""
    settings = create_test_settings()
    service = EmailService(settings=settings)

    mock_smtp_instance = MagicMock()
    mock_smtp_instance.__enter__.return_value = mock_smtp_instance

    with patch("smtplib.SMTP", return_value=mock_smtp_instance):
        result = await service.send_email(
            to_email="candidate@gmail.com",
            subject="Gmail to Gmail Test",
            body_text="Body",
            provider="gmail",
        )
        assert result is True
        mock_smtp_instance.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_matrix_gmail_sender_to_outlook_recipient():
    """2. Gmail sender -> Outlook recipient."""
    settings = create_test_settings()
    service = EmailService(settings=settings)

    mock_smtp_instance = MagicMock()
    mock_smtp_instance.__enter__.return_value = mock_smtp_instance

    with patch("smtplib.SMTP", return_value=mock_smtp_instance):
        result = await service.send_email(
            to_email="candidate@outlook.com",
            subject="Gmail to Outlook Test",
            body_text="Body",
            provider="gmail",
        )
        assert result is True
        mock_smtp_instance.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_matrix_outlook_sender_to_gmail_recipient():
    """3. Outlook sender -> Gmail recipient."""
    settings = create_test_settings()
    service = EmailService(settings=settings)

    mock_token_resp = MagicMock(status_code=200)
    mock_token_resp.json.return_value = {"access_token": "token123", "expires_in": 3600}
    mock_send_resp = MagicMock(status_code=202)

    async def mock_post(url, **kwargs):
        if "oauth2" in url:
            return mock_token_resp
        return mock_send_resp

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        result = await service.send_email(
            to_email="candidate@gmail.com",
            subject="Outlook to Gmail Test",
            body_text="Body",
            provider="outlook",
        )
        assert result is True


@pytest.mark.asyncio
async def test_matrix_outlook_sender_to_outlook_recipient():
    """4. Outlook sender -> Outlook recipient."""
    settings = create_test_settings()
    service = EmailService(settings=settings)

    mock_token_resp = MagicMock(status_code=200)
    mock_token_resp.json.return_value = {"access_token": "token123", "expires_in": 3600}
    mock_send_resp = MagicMock(status_code=202)

    async def mock_post(url, **kwargs):
        if "oauth2" in url:
            return mock_token_resp
        return mock_send_resp

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        result = await service.send_email(
            to_email="candidate@outlook.com",
            subject="Outlook to Outlook Test",
            body_text="Body",
            provider="outlook",
        )
        assert result is True


@pytest.mark.asyncio
async def test_invalid_provider_rejected():
    """7. Invalid provider is rejected with ValidationException."""
    service = EmailService(settings=create_test_settings())
    with pytest.raises(Exception) as exc_info:
        await service.send_email(
            to_email="candidate@example.com",
            subject="Test",
            body_text="Test",
            provider="yahoo",
        )
    assert "Unsupported email provider 'yahoo'" in str(exc_info.value)
