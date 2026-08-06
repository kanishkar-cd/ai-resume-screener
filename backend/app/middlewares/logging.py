from time import perf_counter

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger(__name__)


class RequestTimingLoggingMiddleware(BaseHTTPMiddleware):
    """Measure latency and emit a structured request completion event."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        started_at = perf_counter()
        response = await call_next(request)
        duration_ms = (perf_counter() - started_at) * 1000
        response.headers["X-Process-Time"] = f"{duration_ms:.2f}ms"
        logger.info(
            "HTTP request completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 2),
        )
        return response
