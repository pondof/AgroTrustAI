"""
AgroTrust AI – Microsserviço HTTP do Agente de Segurança.

Expõe o SecurityGuardAgent como API REST autocontida.

Endpoints:
  POST /run     – exige scope agent:security:run; executa liveness/deepfake/blockchain.
  GET  /health  – liveness probe (público).

Auth: JWT Bearer (Zero Trust).
Erros: AgentExecutionError → 500 com correlation_id; ValidationError → 422.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from agents.base import AgentExecutionError
from agents.security.agent import SecurityGuardAgent
from agents.security.schemas import SecurityInput, SecurityOutput
from core.config.settings import Environment, get_settings
from core.security.audit import get_audit_repo
from core.security.crypto import KeyManager
from core.security.iam import Scope, ServiceIdentity, TokenService
from services.gateway.middlewares import CorrelationIdMiddleware, JWTAuthMiddleware

logger = structlog.get_logger(__name__)

_REQUIRED_SCOPE = Scope.AGENT_SECURITY_RUN
_SERVICE_NAME = "agent-security"
_DEFAULT_PORT = 8012


def _require_security_scope(request: Request) -> ServiceIdentity:
    """Depends() para POST /run: exige scope agent:security:run."""
    identity: ServiceIdentity | None = getattr(request.state, "identity", None)
    if identity is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identidade não autenticada",
        )
    if not identity.has_scope(_REQUIRED_SCOPE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Scope '{_REQUIRED_SCOPE.value}' necessário",
        )
    return identity


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logger.info(f"{_SERVICE_NAME}_starting", env=settings.environment.value)

    master_key_hex = settings.security.master_key_hex.get_secret_value()
    app.state.key_manager = KeyManager(master_key_hex=master_key_hex)
    app.state.audit_repo = get_audit_repo()
    app.state.token_service = TokenService()
    app.state.agent = SecurityGuardAgent()

    logger.info(f"{_SERVICE_NAME}_started")
    try:
        yield
    finally:
        logger.info(f"{_SERVICE_NAME}_stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    token_service = TokenService()

    app = FastAPI(
        title="AgroTrust AI – Agent Security",
        description="Microsserviço HTTP do agente de segurança/KYC (liveness, deepfake, blockchain).",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.environment != Environment.PRODUCTION else None,
        redoc_url="/redoc" if settings.environment != Environment.PRODUCTION else None,
    )

    app.add_middleware(JWTAuthMiddleware, token_service=token_service)
    app.add_middleware(CorrelationIdMiddleware)

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(
        request: Request, exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "detail": exc.errors(),
                "correlation_id": getattr(request.state, "correlation_id", ""),
            },
        )

    @app.get("/health", tags=["infra"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": _SERVICE_NAME}

    @app.post(
        "/run",
        response_model=SecurityOutput,
        tags=["agent"],
        dependencies=[Depends(_require_security_scope)],
    )
    async def run(input_data: SecurityInput, request: Request) -> SecurityOutput:
        log = logger.bind(
            correlation_id=getattr(request.state, "correlation_id", ""),
            dossie_id=input_data.dossie_id,
        )
        log.info("agent_security_run_received")
        try:
            agent: SecurityGuardAgent = request.app.state.agent
            output = await agent.run(input_data)
            log.info(
                "agent_security_run_completed",
                fraud_risk=output.fraud_risk_level,
                kyc_passed=output.kyc_passed,
            )
            return output
        except AgentExecutionError as exc:
            log.error(
                "agent_security_run_failed",
                error=type(exc.original_exception).__name__,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error": "AgentExecutionError",
                    "agent": exc.agent_name,
                    "correlation_id": exc.correlation_id,
                    "original_error": type(exc.original_exception).__name__,
                },
            ) from exc

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=_DEFAULT_PORT, log_level="info")
