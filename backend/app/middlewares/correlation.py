import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

CORRELATION_HEADER = "X-Correlation-ID"


class RequestCorrelationIdMiddleware(BaseHTTPMiddleware):
    """Attach a client-supplied or generated correlation ID to each request."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        correlation_id = request.headers.get(CORRELATION_HEADER) or str(uuid.uuid4())
        request.state.correlation_id = correlation_id
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
        try:
            response = await call_next(request)
            response.headers[CORRELATION_HEADER] = correlation_id
            return response
        finally:
            structlog.contextvars.unbind_contextvars("correlation_id")
