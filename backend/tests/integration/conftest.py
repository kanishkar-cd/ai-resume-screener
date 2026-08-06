import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy import text

from app.core.config import get_settings

settings = get_settings()


@pytest.fixture(autouse=True, scope="function")
async def override_db_session_for_integration_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use NullPool for asyncpg connection lifecycle across individual test event loops."""
    test_engine = create_async_engine(settings.ASYNC_DATABASE_URI, poolclass=NullPool)
    test_sessionmaker = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
    
    # Verify DB connection readiness
    try:
        async with test_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        await test_engine.dispose()
        pytest.skip(f"Database connection unavailable: {exc}")

    monkeypatch.setattr("app.db.session.AsyncSessionLocal", test_sessionmaker)
    monkeypatch.setattr("app.db.session.engine", test_engine)
    
    yield
    
    await test_engine.dispose()
