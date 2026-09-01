from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.engine import make_url

from app.core.config import get_settings

settings = get_settings()

connect_args: dict = {}
if settings.POSTGRES_SERVER and "neon.tech" in settings.POSTGRES_SERVER:
    endpoint_id = settings.POSTGRES_SERVER.split(".")[0]
    if endpoint_id:
        connect_args["server_settings"] = {"options": f"endpoint={endpoint_id}"}
elif settings.DATABASE_URL and "neon.tech" in settings.DATABASE_URL:
    try:
        parsed = make_url(settings.DATABASE_URL)
        if parsed.host and "neon.tech" in parsed.host:
            endpoint_id = parsed.host.split(".")[0]
            if endpoint_id:
                connect_args["server_settings"] = {"options": f"endpoint={endpoint_id}"}
    except Exception:
        pass

engine = create_async_engine(
    settings.ASYNC_DATABASE_URI,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    connect_args=connect_args,
)
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped async database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
