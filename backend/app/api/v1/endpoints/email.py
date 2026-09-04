from fastapi import APIRouter, HTTPException, status

from app.schemas.email import (
    SendEmailRequest,
    SendEmailResponse,
    TestEmailRequest,
    TestEmailResponse,
)
from app.schemas.error import ErrorResponsePayload
from app.services.email_service import EmailService

router = APIRouter()

ERRORS = {
    400: {"model": ErrorResponsePayload, "description": "Invalid email payload or unsupported provider."},
    500: {"model": ErrorResponsePayload, "description": "Email dispatch error or configuration error."},
    502: {"model": ErrorResponsePayload, "description": "Email provider upstream API failure."},
}


@router.post(
    "/send",
    response_model=SendEmailResponse,
    status_code=status.HTTP_200_OK,
    summary="Send transactional email using specified provider (Amazon SES / SMTP / Gmail / Outlook)",
    description="Dispatches an email via the selected provider ('ses', 'smtp', 'gmail', or 'outlook').",
    responses=ERRORS,
)
async def send_email_endpoint(
    payload: SendEmailRequest,
) -> SendEmailResponse:
    email_service = EmailService()
    try:
        success = await email_service.send_email(
            to_email=payload.to_email,
            subject=payload.subject,
            body_text=payload.body_text,
            body_html=payload.body_html,
            provider=payload.provider,
            cc=payload.cc,
            bcc=payload.bcc,
        )
        return SendEmailResponse(
            success=success,
            provider=payload.provider,
            message=f"Email dispatch via '{payload.provider}' completed successfully.",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Email dispatch failed: {exc}",
        ) from exc


@router.post(
    "/test",
    response_model=TestEmailResponse,
    status_code=status.HTTP_200_OK,
    summary="Test Amazon SES / SMTP connection and optionally send a test message",
    description="Tests SMTP connection, STARTTLS/SSL, and authentication with Amazon SES.",
    responses=ERRORS,
)
async def test_email_endpoint(
    payload: TestEmailRequest = TestEmailRequest(),
) -> TestEmailResponse:
    email_service = EmailService()
    try:
        # First verify connectivity & credentials
        conn_res = await email_service.test_connection(provider=payload.provider)
        if not conn_res.get("success"):
            return TestEmailResponse(
                success=False,
                provider=payload.provider,
                message="SMTP connection or authentication failed.",
                error=conn_res.get("error"),
                host=conn_res.get("host"),
                port=conn_res.get("port"),
                from_email=conn_res.get("from_email"),
            )

        # If a recipient email is provided, send a live test message
        if payload.to_email and payload.to_email.strip():
            test_subject = "Amazon SES SMTP Integration Test — AI Resume Screener"
            test_body_text = (
                "Hello,\n\n"
                "This is a verified test email sent via Amazon SES SMTP integration from AI Resume Screener.\n"
                "Your SMTP host, port, encryption, username, and verified from address are working correctly.\n\n"
                "— AI Resume Screener Team"
            )
            test_body_html = """
            <div style="font-family: sans-serif; max-width: 500px; padding: 24px; border: 1px solid #e2e8f0; border-radius: 12px; background: #ffffff;">
                <h2 style="color: #0f172a; margin-top: 0;">Amazon SES SMTP Integration Test</h2>
                <p style="color: #334155; line-height: 1.6;">This is a verified test email sent via <strong>Amazon SES SMTP</strong> from <strong>AI Resume Screener</strong>.</p>
                <div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 12px 16px; margin: 20px 0;">
                    <span style="color: #166534; font-weight: bold;">✔ Connection, Authentication &amp; Delivery Verified</span>
                </div>
                <p style="color: #64748b; font-size: 13px;">Credentials and from-address have been verified successfully.</p>
            </div>
            """
            await email_service.send_email(
                to_email=payload.to_email.strip(),
                subject=test_subject,
                body_text=test_body_text,
                body_html=test_body_html,
                provider=payload.provider,
            )
            return TestEmailResponse(
                success=True,
                provider=payload.provider,
                message=f"Connection verified and test email successfully sent to '{payload.to_email}'.",
                host=conn_res.get("host"),
                port=conn_res.get("port"),
                from_email=conn_res.get("from_email"),
            )

        return TestEmailResponse(
            success=True,
            provider=payload.provider,
            message=conn_res.get("message", "SMTP connection and authentication verified successfully."),
            host=conn_res.get("host"),
            port=conn_res.get("port"),
            from_email=conn_res.get("from_email"),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        return TestEmailResponse(
            success=False,
            provider=payload.provider,
            message="Test failed with exception.",
            error=str(exc),
        )
