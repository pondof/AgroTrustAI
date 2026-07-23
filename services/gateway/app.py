"""
AgroTrust AI – API Gateway (FastAPI).

Entry-point HTTP do sistema. Responsabilidades:
  - Autenticação JWT (Zero Trust).
  - Propagação de correlation_id em todo request/response.
  - Rate limit por tenant.
  - Roteamento para criação/consulta de dossiês.
  - Métricas Prometheus e health check.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response

from core.config.settings import Environment, get_settings
from core.events.producer import get_producer
from core.security.audit import get_audit_repo
from core.security.crypto import KeyManager
from core.security.iam import TokenService

from .metrics import get_metrics
from .middlewares import (
    CorrelationIdMiddleware,
    JWTAuthMiddleware,
    RateLimitMiddleware,
)
from .routes import api_router, infra_router
from .routes_params import params_router

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Inicializa singletons (KeyManager, KafkaProducer, AuditRepository) na startup."""
    settings = get_settings()
    logger.info("gateway_starting", env=settings.environment.value)

    # KeyManager – AES master key
    master_key_hex = settings.security.master_key_hex.get_secret_value()
    app.state.key_manager = KeyManager(master_key_hex=master_key_hex)

    # AuditRepository – singleton process-wide
    app.state.audit_repo = get_audit_repo()

    # KafkaProducer – inicia conexão com Kafka (ou noop em CI)
    app.state.kafka_producer = await get_producer()

    # TokenService – verifica JWTs incoming
    app.state.token_service = TokenService()

    logger.info("gateway_started", env=settings.environment.value)
    try:
        yield
    finally:
        logger.info("gateway_stopping")
        try:
            await app.state.kafka_producer.stop()
        except Exception as exc:  # pragma: no cover
            logger.warning("kafka_producer_stop_error", error=str(exc))
        logger.info("gateway_stopped")


def create_app() -> FastAPI:
    """Factory pattern: facilita testes e reuso."""
    settings = get_settings()
    token_service = TokenService()

    app = FastAPI(
        title="AgroTrust AI – API Gateway",
        description="Gateway central do sistema agêntico de subscrição de crédito rural.",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.environment != Environment.PRODUCTION else None,
        redoc_url="/redoc" if settings.environment != Environment.PRODUCTION else None,
    )

    # CORS – restrito em prod
    cors_origins = ["*"] if settings.environment != Environment.PRODUCTION else []
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Correlation-ID"],
    )

    # Ordem importa: rate limit DEPOIS de auth (precisa do tenant); auth DEPOIS de correlation_id
    app.add_middleware(RateLimitMiddleware, max_requests=100, window_seconds=60)
    app.add_middleware(JWTAuthMiddleware, token_service=token_service)
    app.add_middleware(CorrelationIdMiddleware)

    # Hook de métricas (após resposta gerada)
    @app.middleware("http")
    async def _metrics_hook(request: Request, call_next):  # type: ignore[no-untyped-def]
        start = time.monotonic()
        response: Response = await call_next(request)
        duration = time.monotonic() - start
        get_metrics().observe_request(
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_sec=duration,
        )
        return response

    app.include_router(infra_router)
    app.include_router(api_router)
    app.include_router(params_router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
