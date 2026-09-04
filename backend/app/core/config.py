import socket
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

from app.core.constants import AppEnv

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Validated application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=(BACKEND_ROOT.parent / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    APP_NAME: str = "AI Resume Screener API"
    APP_ENV: AppEnv = AppEnv.DEVELOPMENT
    DEBUG: bool = False
    API_V1_STR: str = "/api/v1"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres_password"
    POSTGRES_DB: str = "resume_screener_db"
    DATABASE_URL: str | None = None

    # Redis settings for ephemeral caching and pipeline progress state
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str | None = None
    REDIS_DB: int = 0
    REDIS_URL: str | None = None
    REDIS_ENABLED: bool = True
    REDIS_CACHE_TTL_SECONDS: int = 300

    CORS_ORIGINS: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
    )

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: object) -> object:
        if isinstance(v, str):
            v_str = v.strip()
            if v_str.startswith("[") and v_str.endswith("]"):
                import json
                try:
                    parsed = json.loads(v_str)
                    if isinstance(parsed, list):
                        return [str(item).strip() for item in parsed]
                except Exception:
                    pass
            return [origin.strip() for origin in v_str.split(",") if origin.strip()]
        if not v:
            return [
                "http://localhost:5173",
                "http://127.0.0.1:5173",
                "http://localhost:3000",
                "http://127.0.0.1:3000",
                "*",
            ]
        return v

    STORAGE_DIR: Path = BACKEND_ROOT / "storage"
    MAX_UPLOAD_SIZE_BYTES: int = 25 * 1024 * 1024
    ALLOWED_RESUME_EXTENSIONS: list[str] = Field(
        default_factory=lambda: [".pdf", ".docx"]
    )
    ALLOWED_RESUME_MIME_TYPES: list[str] = Field(
        default_factory=lambda: [
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ]
    )

    ENABLE_AI_INSIGHTS: bool = False
    GROQ_API_KEY: str | None = None
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    GROQ_MODEL: str = "openai/gpt-oss-20b"
    GROQ_TIMEOUT_SECONDS: float = 30.0
    GROQ_MAX_RETRIES: int = 1
    GROQ_TPM_LIMIT: int = Field(default=8000, ge=100)
    GROQ_TPM_SAFETY_MARGIN: float = Field(default=0.125, ge=0.0, le=0.5)
    GROQ_ESTIMATED_OUTPUT_TOKENS: int = Field(default=350, ge=50, le=4096)

    CEREBRAS_API_KEY: str | None = None
    CEREBRAS_BASE_URL: str = "https://api.cerebras.ai/v1"
    CEREBRAS_MODEL: str = "gpt-oss-120b"
    CEREBRAS_TIMEOUT_SECONDS: float = 30.0
    CEREBRAS_MAX_RETRIES: int = 1
    CEREBRAS_TPM_LIMIT: int = Field(default=60000, ge=100)
    CEREBRAS_TPM_SAFETY_MARGIN: float = Field(default=0.10, ge=0.0, le=0.5)

    MAX_CONCURRENT_RESUMES: int = Field(default=3, ge=1, le=10)

    ENABLE_OCR_FALLBACK: bool = False
    OCR_ENGINE: str = "easyocr"
    OCR_LANGUAGES: str | list[str] = Field(default_factory=lambda: ["en"])
    OCR_DPI: int = 200


    ENABLE_HYBRID_MATCHING: bool = True
    HYBRID_MATCHING_LLM_CONFIDENCE_THRESHOLD: float = Field(default=0.80, ge=0, le=1)
    HYBRID_MATCHING_KEYWORD_OVERLAP_THRESHOLD: float = Field(default=0.15, ge=0, le=1)
    HYBRID_MATCHING_MAX_EVIDENCE_PER_REQUIREMENT: int = Field(default=5, ge=1, le=50)
    HYBRID_MATCHING_CACHE_SIZE: int = Field(default=512, ge=1, le=10000)

    AFFINDA_API_KEY: str | None = None
    AFFINDA_API_BASE_URL: str = "https://api.affinda.com"
    AFFINDA_WORKSPACE_ID: str | None = None
    AFFINDA_RESUME_DOCUMENT_TYPE_ID: str | None = None
    AFFINDA_JD_DOCUMENT_TYPE_ID: str | None = None
    AFFINDA_TIMEOUT_SECONDS: float = 240.0

    CD_RECRUIT_BASE_URL: str = "http://localhost:3001"
    CD_RECRUIT_API_KEY: str = "pk_live_7f9ec682b7da34e6b9d5fee8ad70be610c1b8d67647a1c99"
    CD_RECRUIT_TIMEOUT_SECONDS: float = 15.0
    CD_RECRUIT_DEFAULT_DEPARTMENT_CODE: str = "ENG"
    CD_RECRUIT_DEFAULT_LEVEL: str = "EXPERIENCED"

    # Amazon SES & Standard SMTP Email Configuration
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_USE_TLS: bool = True
    SMTP_USE_SSL: bool = False
    SMTP_FROM_EMAIL: str = "kanishkar@clouddestinations.com"
    SMTP_FROM_NAME: str = "AI Resume Screener"
    ENABLE_ASSESSMENT_EMAILS: bool = True
    MAX_CONCURRENT_EMAILS: int = Field(default=5, ge=1, le=50)
    MAX_EMAIL_RETRIES: int = Field(default=3, ge=0, le=10)
    EMAIL_RETRY_BASE_DELAY: float = Field(default=2.0, ge=0.1, le=60.0)

    # Amazon SES specific aliases
    SES_SMTP_HOST: str | None = None
    SES_SMTP_PORT: int | None = None
    SES_SMTP_USERNAME: str | None = None
    SES_SMTP_PASSWORD: str | None = None
    SES_FROM_EMAIL: str | None = None

    # Microsoft Outlook / Microsoft Graph OAuth Configuration
    OUTLOOK_CLIENT_ID: str | None = None
    OUTLOOK_CLIENT_SECRET: str | None = None
    OUTLOOK_TENANT_ID: str = "common"
    OUTLOOK_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/outlook/callback"
    OUTLOOK_SENDER_EMAIL: str = "kanishkar@clouddestinations.com"
    OUTLOOK_REFRESH_TOKEN: str | None = None
    DEFAULT_EMAIL_PROVIDER: str = "ses"





    @field_validator("OCR_LANGUAGES", mode="before")
    @classmethod
    def assemble_ocr_languages(cls, v: object) -> object:
        if isinstance(v, str):
            v_str = v.strip()
            if v_str.startswith("[") and v_str.endswith("]"):
                import json
                try:
                    parsed = json.loads(v_str)
                    if isinstance(parsed, list):
                        return [str(item).strip() for item in parsed]
                except Exception:
                    pass
            return [lang.strip() for lang in v_str.split(",") if lang.strip()]
        if not v:
            return ["en"]
        return v

    @property
    def ASYNC_DATABASE_URI(self) -> str:
        """Alias for sqlalchemy_database_uri used in async session engine."""
        return self.sqlalchemy_database_uri

    @property
    def sqlalchemy_database_uri(self) -> str:

        """Construct a validated SQLAlchemy connection URI."""
        if self.DATABASE_URL:
            raw_url = str(self.DATABASE_URL)
            if raw_url.startswith("postgres://"):
                raw_url = raw_url.replace("postgres://", "postgresql://", 1)
            if raw_url.startswith("postgresql://"):
                raw_url = raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
            parsed_url = make_url(raw_url)
            query_dict = dict(parsed_url.query)
            query_dict.pop("channel_binding", None)
            if "sslmode" in query_dict:
                ssl_val = query_dict.pop("sslmode")
                if ssl_val and "ssl" not in query_dict:
                    query_dict["ssl"] = ssl_val

            if parsed_url.host and ("neon.tech" in parsed_url.host or "aws" in parsed_url.host):
                try:
                    ip = socket.gethostbyname(parsed_url.host)
                    parsed_url = parsed_url._replace(host=ip)
                except Exception:
                    pass

            if parsed_url.password:
                encoded_password = quote_plus(parsed_url.password)
                parsed_url = parsed_url._replace(password=encoded_password)

            escaped_url = parsed_url._replace(query=query_dict)
            return escaped_url.render_as_string(hide_password=False)



        encoded_password = quote_plus(self.POSTGRES_PASSWORD)
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{encoded_password}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton across requests."""
    return Settings()
