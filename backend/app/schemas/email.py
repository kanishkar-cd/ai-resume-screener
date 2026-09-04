from pydantic import EmailStr, Field, field_validator
from app.schemas.base import APIModel

ALLOWED_PROVIDERS = ("ses", "smtp", "amazon_ses", "gmail", "outlook")


class SendEmailRequest(APIModel):
    provider: str = Field(default="ses", description="Email provider: 'ses', 'smtp', 'gmail', or 'outlook'")
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
        if v_clean not in ALLOWED_PROVIDERS:
            raise ValueError(f"Invalid email provider '{v}'. Supported providers: {', '.join(ALLOWED_PROVIDERS)}.")
        return v_clean


class SendEmailResponse(APIModel):
    success: bool
    provider: str
    message: str


class TestEmailRequest(APIModel):
    provider: str = Field(default="ses", description="Email provider to test: 'ses', 'smtp', 'gmail', or 'outlook'")
    to_email: str | None = Field(default=None, description="Optional target email address to send test message to")

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        v_clean = v.strip().lower()
        if v_clean not in ALLOWED_PROVIDERS:
            raise ValueError(f"Invalid email provider '{v}'. Supported providers: {', '.join(ALLOWED_PROVIDERS)}.")
        return v_clean


class TestEmailResponse(APIModel):
    success: bool
    provider: str
    message: str
    host: str | None = None
    port: int | None = None
    from_email: str | None = None
    error: str | None = None
