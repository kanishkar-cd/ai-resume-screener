from fastapi import APIRouter, HTTPException, status

from app.schemas.email import SendEmailRequest, SendEmailResponse
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
    summary="Send transactional email using specified provider (Gmail / Outlook)",
    description="Dispatches an email via the selected provider ('gmail' or 'outlook').",
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
            message=f"Email dispatch via '{payload.provider}' provider completed with result: {success}.",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
