"""
AgroTrust AI – Middlewares do API Gateway.

Componentes:
  - CorrelationIdMiddleware: gera/propaga X-Correlation-ID em cada request.
  - JWTAuthMiddleware: valida Bearer token e injeta ServiceIdentity em request.state.
  - RateLimitMiddleware: rate limit in-memory por tenant (token bucket simplificado).
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from core.security.iam import ServiceIdentity, TokenService

logger = structlog.get_logger(__name__)

CORRELATION_HEADER: str = "X-Correlation-ID"
PUBLIC_PATHS: frozenset[str] = frozenset(
    {"/health", "/metrics", "/docs", "/openapi.json", "/redoc", "/token"}
)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Garante correlation_id em todo request/response e contexto structlog."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        correlation_id = request.headers.get(CORRELATION_HEADER) or str(uuid.uuid4())
        request.state.correlation_id = correlation_id
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("correlation_id")
        response.headers[CORRELATION_HEADER] = correlation_id
        return response


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """
    Valida o header Authorization: Bearer <token> via TokenService.
    Endpoints em PUBLIC_PATHS passam sem autenticação.
    """

    def __init__(self, app: object, token_service: TokenService) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._tokens = token_service

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path in PUBLIC_PATHS or request.method == "OPTIONS":
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Bearer token ausente ou inválido"},
            )
        token = auth.removeprefix("Bearer ").strip()
        try:
            identity: ServiceIdentity = self._tokens.verify(token)
        except PermissionError as exc:
            logger.warning("jwt_verification_failed", error=str(exc))
            return JSONResponse(
                status_code=401,
                content={"detail": "Token inválido ou expirado"},
            )

        request.state.identity = identity
        structlog.contextvars.bind_contextvars(
            subject=identity.subject,
            tenant_id=identity.tenant_id,
        )
        try:
            return await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("subject", "tenant_id")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limit in-memory por tenant_id (sliding window).

    Atenção: in-memory não escala horizontalmente; em produção usar Redis.
    """

    def __init__(self, app: object, max_requests: int = 100, window_seconds: int = 60) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._max = max_requests
        self._window = window_seconds
        self._buckets: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        identity: ServiceIdentity | None = getattr(request.state, "identity", None)
        tenant_id = identity.tenant_id if identity else "anonymous"

        now = time.monotonic()
        bucket = self._buckets[tenant_id]
        cutoff = now - self._window
        while bucket and bucket[0] < cutoff:
            bucket.popleft()

        if len(bucket) >= self._max:
            retry_after = max(1, int(bucket[0] + self._window - now))
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit excedido para o tenant"},
                headers={"Retry-After": str(retry_after)},
            )

        bucket.append(now)
        return await call_next(request)
