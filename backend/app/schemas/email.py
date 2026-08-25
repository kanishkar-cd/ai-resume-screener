from pydantic import EmailStr, Field, field_validator
from app.schemas.base import APIModel


class SendEmailRequest(APIModel):
    provider: str = Field(default="gmail", description="Email provider: 'gmail' or 'outlook'")
    to_email: str = Field(..., description="Recipient email address")
    subject: str = Field(..., min_length=1, description="Email subject line")
    body_text: str = Field(..., description="Plain text email body")
    body_html: str | None = Field(default=None, description="HTML email body")
    cc: list[str] | str | None = Field(default=None, description="CC recipient(s)")
    bcc: list[str] | str | None = Field(default=None, description="BCC recipient(s)")

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        v_clean = v.strip().lower()
        if v_clean not in ("gmail", "outlook"):
            raise ValueError(f"Invalid email provider '{v}'. Supported providers: 'gmail', 'outlook'.")
        return v_clean


class SendEmailResponse(APIModel):
    success: bool
    provider: str
    message: str
