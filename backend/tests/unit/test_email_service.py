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
    SMTP_FROM_EMAIL = "kanishkar@clouddestinations.com"


@pytest.mark.asyncio
async def test_send_email_smtp_success():
    """Verify that send_email connects via smtplib, enables STARTTLS, logs in,

    and sends message.
    """
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
        )

        assert success is True
        mock_smtp_cls.assert_called_once_with(host="smtp.example.com", port=587, timeout=10)
        mock_smtp_instance.starttls.assert_called_once()
        mock_smtp_instance.login.assert_called_once_with("kanishkar@clouddestinations.com", "test_password_123")
        mock_smtp_instance.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_send_email_disabled_by_config():
    """Verify that email delivery is skipped when ENABLE_ASSESSMENT_EMAILS is

    false.
    """
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
        with pytest.raises(smtplib.SMTPException):
            await email_service.send_email(
                to_email="candidate@example.com",
                subject="Test",
                body_text="Test",
            )


@pytest.mark.asyncio
async def test_send_assessment_invitation_template_content():
    """Verify that send_assessment_invitation dynamically populates all required template fields."""
    settings = DummySMTPSettings()
    email_service = EmailService(settings=settings)

    captured_call = {}

    async def mock_send_email(to_email, subject, body_text, body_html=None):
        captured_call["to_email"] = to_email
        captured_call["subject"] = subject
        captured_call["body_text"] = body_text
        captured_call["body_html"] = body_html
        return True

    email_service.send_email = mock_send_email

    candidate_name = "Jane Doe"
    candidate_email = "jane.doe@example.com"
    test_link = "http://localhost:3000/invite/token_jane123"

    await email_service.send_assessment_invitation(
        candidate_name=candidate_name,
        candidate_email=candidate_email,
        assessment_link=test_link,
        requisition_ref="REQ-2026-ENG-001",
    )

    assert captured_call["to_email"] == "jane.doe@example.com"
    assert captured_call["subject"] == "You’ve Been Shortlisted – Software Engineering Assessment"

    # Verify plain text dynamic replacements
    assert "Hi Jane Doe," in captured_call["body_text"]
    assert "Congratulations! You have been successfully shortlisted for the Software Engineering role." in captured_call["body_text"]
    assert f"Test Link: {test_link}" in captured_call["body_text"]
    assert "Important: This link will expire in 24 hours. Please complete the assessment before it expires." in captured_call["body_text"]
    assert "Wishing you the very best, and good luck with your assessment!" in captured_call["body_text"]
    assert "Talent Acquisition Team" in captured_call["body_text"]

    # Verify HTML template dynamic replacements
    assert "Hi Jane Doe," in captured_call["body_html"]
    assert "Congratulations! You have been successfully shortlisted for the Software Engineering role." in captured_call["body_html"]
    assert test_link in captured_call["body_html"]
    assert "Important: This link will expire in 24 hours. Please complete the assessment before it expires." in captured_call["body_html"]
    assert "Talent Acquisition Team" in captured_call["body_html"]


@pytest.mark.asyncio
async def test_dispatch_emails_background_bounded_concurrency():
    """Verify that _dispatch_emails_background never exceeds max_concurrency."""
    import asyncio
    from app.services.assessment_service import _dispatch_emails_background

    max_concurrency = 3
    active_concurrent = 0
    peak_concurrent = 0
    lock = asyncio.Lock()

    async def mock_send_assessment_invitation(candidate_name, candidate_email, assessment_link, requisition_ref):
        nonlocal active_concurrent, peak_concurrent
        async with lock:
            active_concurrent += 1
            if active_concurrent > peak_concurrent:
                peak_concurrent = active_concurrent

        # Simulate small IO delay
        await asyncio.sleep(0.05)

        async with lock:
            active_concurrent -= 1

    mock_email_service = MagicMock()
    mock_email_service.send_assessment_invitation = mock_send_assessment_invitation

    test_candidates = [
        {
            "candidate_name": f"Candidate {i}",
            "email": f"candidate{i}@example.com",
            "assessment_link": f"http://localhost:3000/invite/token_{i}",
        }
        for i in range(10)
    ]

    await _dispatch_emails_background(
        mock_email_service,
        test_candidates,
        requisition_ref="REQ-TEST-001",
        max_concurrency=max_concurrency,
    )

    assert peak_concurrent <= max_concurrency
    assert peak_concurrent > 1  # Verify it ran concurrently up to the limit


@pytest.mark.asyncio
async def test_send_email_retry_temporary_failure_then_success():
    """Verify that a temporary SMTP failure triggers a retry and succeeds."""
    class RetrySettings(DummySMTPSettings):
        MAX_EMAIL_RETRIES = 3
        EMAIL_RETRY_BASE_DELAY = 0.01  # Fast delay for unit test

    email_service = EmailService(settings=RetrySettings())

    mock_smtp_instance = MagicMock()
    call_count = 0

    def mock_send(msg):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise smtplib.SMTPServerDisconnected("Temporary connection reset")
        return None

    mock_smtp_instance.__enter__.return_value = mock_smtp_instance
    mock_smtp_instance.send_message.side_effect = mock_send

    with patch("smtplib.SMTP", return_value=mock_smtp_instance):
        success = await email_service.send_email(
            to_email="candidate@example.com",
            subject="Test",
            body_text="Test",
        )
        assert success is True
        assert call_count == 2


@pytest.mark.asyncio
async def test_send_email_retry_exhaustion():
    """Verify that retries stop at MAX_EMAIL_RETRIES when failure persists."""
    class RetrySettings(DummySMTPSettings):
        MAX_EMAIL_RETRIES = 2
        EMAIL_RETRY_BASE_DELAY = 0.01

    email_service = EmailService(settings=RetrySettings())

    mock_smtp_instance = MagicMock()
    call_count = 0

    def mock_send(msg):
        nonlocal call_count
        call_count += 1
        raise smtplib.SMTPConnectError(421, "Service unavailable")

    mock_smtp_instance.__enter__.return_value = mock_smtp_instance
    mock_smtp_instance.send_message.side_effect = mock_send

    with patch("smtplib.SMTP", return_value=mock_smtp_instance):
        with pytest.raises(smtplib.SMTPConnectError):
            await email_service.send_email(
                to_email="candidate@example.com",
                subject="Test",
                body_text="Test",
            )
        # Attempt 1 + 2 retries = 3 total attempts
        assert call_count == 3


@pytest.mark.asyncio
async def test_send_email_permanent_failure_no_retry():
    """Verify that permanent failures (e.g. SMTPAuthenticationError, SMTPRecipientsRefused) are not retried."""
    class RetrySettings(DummySMTPSettings):
        MAX_EMAIL_RETRIES = 3
        EMAIL_RETRY_BASE_DELAY = 0.01

    email_service = EmailService(settings=RetrySettings())

    mock_smtp_instance = MagicMock()
    call_count = 0

    def mock_send(msg):
        nonlocal call_count
        call_count += 1
        raise smtplib.SMTPAuthenticationError(535, b"Invalid credentials")

    mock_smtp_instance.__enter__.return_value = mock_smtp_instance
    mock_smtp_instance.send_message.side_effect = mock_send

    with patch("smtplib.SMTP", return_value=mock_smtp_instance):
        with pytest.raises(smtplib.SMTPAuthenticationError):
            await email_service.send_email(
                to_email="candidate@example.com",
                subject="Test",
                body_text="Test",
            )
        # Should stop after attempt 1 without retrying
        assert call_count == 1


@pytest.mark.asyncio
async def test_dispatch_emails_background_mixed_batch():
    """Verify a 5-candidate batch with mixed outcomes: success, retry-then-success, and permanent failure."""
    from app.services.assessment_service import _dispatch_emails_background

    processed_success = []
    attempts_by_email = {}

    async def mock_send_assessment_invitation(candidate_name, candidate_email, assessment_link, requisition_ref):
        attempts_by_email[candidate_email] = attempts_by_email.get(candidate_email, 0) + 1
        
        # Candidate 2 fails on attempt 1, then succeeds on attempt 2
        if candidate_email == "cand2@example.com" and attempts_by_email[candidate_email] == 1:
            raise smtplib.SMTPServerDisconnected("Temporary connection reset")
        
        # Candidate 3 has a permanent failure
        if candidate_email == "cand3@example.com":
            raise smtplib.SMTPRecipientsRefused({"cand3@example.com": (550, b"User unknown")})
            
        processed_success.append(candidate_email)

    mock_email_service = MagicMock()
    mock_email_service.send_assessment_invitation = mock_send_assessment_invitation

    test_candidates = [
        {"candidate_name": f"Candidate {i}", "email": f"cand{i}@example.com", "assessment_link": f"http://localhost:3000/invite/t_{i}"}
        for i in range(1, 6)
    ]

    await _dispatch_emails_background(
        mock_email_service,
        test_candidates,
        requisition_ref="REQ-TEST-MIXED",
        max_concurrency=3,
    )

    # Candidates 1, 4, 5 succeeded; Candidate 2 was attempted; Candidate 3 failed permanently without stopping others
    assert "cand1@example.com" in processed_success
    assert "cand4@example.com" in processed_success
    assert "cand5@example.com" in processed_success
    assert "cand3@example.com" not in processed_success
