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
        env_file=BACKEND_ROOT / ".env",
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

<<<<<<< Updated upstream
    ENABLE_OCR_FALLBACK: bool = True
    OCR_ENGINE: str = "paddleocr"
    OCR_LANGUAGES: list[str] | str = Field(default_factory=lambda: ["en"])
=======
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
    GROQ_API_KEY_1: str | None = None
    GROQ_API_KEY_2: str | None = None
    GROQ_API_KEY_3: str | None = None
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    GROQ_MODEL: str = "openai/gpt-oss-20b"
    GROQ_TIMEOUT_SECONDS: float = 30.0
    GROQ_MAX_RETRIES: int = 1
    GROQ_KEY_COOLDOWN_SECONDS: float = Field(default=60.0, ge=0.01, le=600.0)
    GROQ_KEY_TOKEN_BUDGET: int = Field(default=7000, ge=100)
    GROQ_TPM_LIMIT: int = Field(default=8000, ge=100)
    GROQ_TPM_SAFETY_MARGIN: float = Field(default=0.125, ge=0.0, le=0.5)
    GROQ_ESTIMATED_OUTPUT_TOKENS: int = Field(default=350, ge=50, le=4096)
    GROQ_MAX_COMPLETION_TOKENS: int = Field(default=4096, ge=512, le=8192)
    ENABLE_AI_RESUME_EXTRACTION: bool = False
    AI_EXTRACTION_TIMEOUT_SECONDS: float = 30.0

    # OpenRouter LLM Provider Fallback Configuration
    OPENROUTER_API_KEY: str | None = None
    OPEN_ROUTER: str | None = None  # Backward/alias support for .env Open_router
    Open_router: str | None = None  # Alias for exact .env casing
    open_router: str | None = None  # Alias for lowercase .env
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_MODEL: str = "meta-llama/llama-3.3-70b-instruct"
    OPENROUTER_TIMEOUT_SECONDS: float = Field(default=30.0, ge=1.0, le=300.0)
    OPENROUTER_MAX_RETRIES: int = Field(default=1, ge=0, le=5)
    OPENROUTER_ENABLED: bool = True
    OPENROUTER_MAX_COMPLETION_TOKENS: int = Field(default=4096, ge=512, le=8192)
    OPENROUTER_HTTP_REFERER: str = "https://clouddestinations.com"
    OPENROUTER_APP_TITLE: str = "AI Resume Screener"

    @property
    def openrouter_is_configured(self) -> bool:
        """True if OpenRouter is enabled and has a valid API key."""
        key = self.OPENROUTER_API_KEY or self.OPEN_ROUTER or self.Open_router or self.open_router
        return bool(self.OPENROUTER_ENABLED and key and key.strip())

    @property
    def groq_keys(self) -> list[str]:
        """
        Normalized list of configured Groq API keys with deterministic ordering,
        empty/whitespace removed, and duplicates removed.
        Order: GROQ_API_KEY_1, GROQ_API_KEY_2, GROQ_API_KEY_3, GROQ_API_KEY.
        """
        raw_candidates = [
            self.GROQ_API_KEY_1,
            self.GROQ_API_KEY_2,
            self.GROQ_API_KEY_3,
            self.GROQ_API_KEY,
        ]
        keys: list[str] = []
        for key in raw_candidates:
            if key and isinstance(key, str):
                cleaned = key.strip()
                if cleaned and cleaned not in keys:
                    keys.append(cleaned)
        return keys

    @property
    def primary_groq_api_key(self) -> str | None:
        """First available valid Groq API key, or None if none configured."""
        keys = self.groq_keys
        return keys[0] if keys else None

    @property
    def groq_is_configured(self) -> bool:
        """True if at least one valid Groq API key is configured."""
        return bool(self.groq_keys)

    def model_post_init(self, __context: object) -> None:
        """Ensure backward-compatibility: populate GROQ_API_KEY and OPENROUTER_API_KEY if aliases are set."""
        if not self.GROQ_API_KEY and self.groq_keys:
            self.GROQ_API_KEY = self.groq_keys[0]
        if not self.OPENROUTER_API_KEY:
            alias = self.OPEN_ROUTER or self.Open_router or self.open_router
            if alias:
                self.OPENROUTER_API_KEY = alias.strip()

    CEREBRAS_API_KEY: str | None = None
    CEREBRAS_BASE_URL: str = "https://api.cerebras.ai/v1"
    CEREBRAS_MODEL: str = "gpt-oss-120b"
    CEREBRAS_TIMEOUT_SECONDS: float = 30.0
    CEREBRAS_MAX_RETRIES: int = 1
    CEREBRAS_TPM_LIMIT: int = Field(default=60000, ge=100)
    CEREBRAS_TPM_SAFETY_MARGIN: float = Field(default=0.10, ge=0.0, le=0.5)
    CEREBRAS_MAX_COMPLETION_TOKENS: int = Field(default=4096, ge=512, le=8192)

    MAX_CONCURRENT_RESUMES: int = Field(default=3, ge=1, le=10)
    LLM_BATCH_THROTTLE_SECONDS: float = Field(default=0.25, ge=0.0, le=5.0)
    LLM_BATCH_CHUNK_SIZE: int = Field(default=8, ge=1, le=20)
    PROVIDER_CIRCUIT_BREAKER_COOLDOWN_SECONDS: float = Field(default=60.0, ge=0.01, le=600.0)
    PROVIDER_CIRCUIT_BREAKER_MAX_FAILURES: int = Field(default=2, ge=1, le=10)

    ENABLE_OCR_FALLBACK: bool = False
    OCR_ENGINE: str = "easyocr"
    OCR_LANGUAGES: str | list[str] = Field(default_factory=lambda: ["en"])
>>>>>>> Stashed changes
    OCR_DPI: int = 200

    GROQ_API_KEY: str | None = None
    ENABLE_AI_RESUME_EXTRACTION: bool = False
    ENABLE_AI_JD_EXTRACTION: bool = False
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    AI_EXTRACTION_TIMEOUT_SECONDS: float = 30.0

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
        return v

    @field_validator("DEBUG", mode="before")
    @classmethod
    def normalize_debug(cls, value: object) -> object:
        """Normalize common build-mode values sometimes exported as DEBUG."""
        if isinstance(value, str):
            normalized = value.casefold()
            if normalized in {"release", "production"}:
                return False
            if normalized in {"debug", "development"}:
                return True
        return value

    @property
    def ASYNC_DATABASE_URI(self) -> str:
        """Build the SQLAlchemy async PostgreSQL connection URI."""
        if self.DATABASE_URL:
            url = make_url(self.DATABASE_URL)
            query = dict(url.query)
            query.pop("channel_binding", None)
            if query.pop("sslmode", None) == "require":
                query["ssl"] = "require"
            return url.set(
                drivername="postgresql+asyncpg",
                query=query,
            ).render_as_string(hide_password=False)
        user = quote_plus(self.POSTGRES_USER)
        password = quote_plus(self.POSTGRES_PASSWORD)
        return (
            f"postgresql+asyncpg://{user}:{password}@{self.POSTGRES_SERVER}:"
            f"{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide immutable settings instance."""
    return Settings()
