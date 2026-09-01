from collections.abc import AsyncGenerator

import httpx
import pytest_asyncio

import pytest

from app.main import app
from app.services.matching_service import GroqTokenBudgetGate


@pytest.fixture(autouse=True)
def reset_groq_token_gate():
    GroqTokenBudgetGate.reset_gate()


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
