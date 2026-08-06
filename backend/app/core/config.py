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
    CORS_ORIGINS: list[str] = Field(default_factory=list)

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
