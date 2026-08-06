import httpx
import pytest
from sqlalchemy.exc import OperationalError

from app.db.session import get_db
from app.main import app


class HealthySession:
    async def execute(self, _statement: object) -> None:
        return None


class UnhealthySession:
    async def execute(self, _statement: object) -> None:
        raise OperationalError("SELECT 1", {}, Exception("offline"))


@pytest.mark.asyncio
async def test_liveness(async_client: httpx.AsyncClient) -> None:
    response = await async_client.get("/api/v1/health/liveness")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_readiness_when_database_is_connected(
    async_client: httpx.AsyncClient,
) -> None:
    async def healthy_db() -> HealthySession:
        return HealthySession()

    app.dependency_overrides[get_db] = healthy_db
    response = await async_client.get("/api/v1/health/readiness")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}


@pytest.mark.asyncio
async def test_readiness_when_database_is_unavailable(
    async_client: httpx.AsyncClient,
) -> None:
    async def unhealthy_db() -> UnhealthySession:
        return UnhealthySession()

    app.dependency_overrides[get_db] = unhealthy_db
    response = await async_client.get("/api/v1/health/readiness")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database is unavailable."}
