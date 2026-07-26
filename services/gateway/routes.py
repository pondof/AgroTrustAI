"""
AgroTrust AI – Rotas HTTP do API Gateway.

Endpoints:
  - POST /api/v1/subscriptions          (inicia dossiê)
  - GET  /api/v1/subscriptions/{id}     (status atual)
  - GET  /api/v1/subscriptions/{id}/audit-trail (trilha de auditoria)
  - GET  /health
  - GET  /metrics
"""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.engine import get_session
from core.db.repositories.dossie import DossieRecord, DossieRepository
from core.events.schemas import PropertyLocation, SubscriptionInitiatedEvent
from core.events.topics import TOPICS
from core.security.audit import AuditEventType, get_audit_repo
from core.security.iam import Scope, ServiceIdentity, TokenService

from .dependencies import require_scope
from .dev_users import authenticate_dev_user
from .metrics import get_metrics

logger = structlog.get_logger(__name__)

api_router = APIRouter(prefix="/api/v1", tags=["subscriptions"])
infra_router = APIRouter(tags=["infra"])


# ─── Modelos ──────────────────────────────────────────────────────────────────


class SubscriptionRequest(BaseModel):
    """Payload aceito pelo POST /subscriptions."""

    producer_cpf_hash: str = Field(min_length=64, max_length=64, description="SHA-3-256 do CPF")
    car_number: str
    property_area_ha: float = Field(gt=0)
    location: PropertyLocation
    credit_amount_brl: float = Field(gt=0)
    credit_purpose: str
    requested_by: str


class SubscriptionResponse(BaseModel):
    dossie_id: str
    status: str
    correlation_id: str
    submitted_at: str


class TokenResponse(BaseModel):
    """Resposta do POST /token (compatível com OAuth2 password flow)."""

    access_token: str
    token_type: str = "bearer"
    scopes: list[str] = Field(default_factory=list)
    tenant_id: str


class DossieListItem(BaseModel):
    """Linha da listagem paginada (GET /subscriptions). Enxuta para a tabela."""

    dossie_id: str
    tenant_id: str
    status: str
    verdict: str | None = None
    car_number: str
    producer_cpf_hash: str
    credit_amount_brl: float
    credit_purpose: str
    composite_score: float | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_record(cls, record: DossieRecord) -> DossieListItem:
        return cls(
            dossie_id=record.dossie_id,
            tenant_id=record.tenant_id,
            status=record.status,
            verdict=record.verdict,
            car_number=record.car_number,
            producer_cpf_hash=record.producer_cpf_hash,
            credit_amount_brl=record.credit_amount_brl,
            credit_purpose=record.credit_purpose,
            composite_score=record.composite_score,
            created_at=record.created_at.isoformat() if record.created_at else None,
            updated_at=record.updated_at.isoformat() if record.updated_at else None,
        )


class DossieListResponse(BaseModel):
    """Envelope paginado da listagem de dossiês."""

    items: list[DossieListItem]
    total: int
    page: int
    pages: int


class DossieDetailResponse(BaseModel):
    """Detalhe do dossiê lido da projeção `dossies` (PostgreSQL)."""

    dossie_id: str
    tenant_id: str
    status: str
    verdict: str | None = None
    car_number: str
    credit_amount_brl: float
    credit_purpose: str
    property_area_ha: float
    composite_score: float | None = None
    esg_score: float | None = None
    financial_score: float | None = None
    security_score: float | None = None
    approved_amount_brl: float | None = None
    rejection_reasons: list[str] = Field(default_factory=list)
    xai_summary: dict[str, Any] = Field(
        default_factory=dict,
        description="Resumo do XAI consolidado (bloco de scores). Detalhe completo em /xai.",
    )
    processing_time_ms: int | None = None
    created_at: str | None = None
    updated_at: str | None = None


class AuditTrailEntry(BaseModel):
    event_id: str
    timestamp: str
    event_type: str
    subject: str
    tenant_id: str
    resource_id: str
    outcome: str
    details: dict[str, Any]
    previous_hash: str
    entry_hash: str
    # String canônica exata sobre a qual o SHA-3-256 foi calculado (espelha
    # core.security.audit.AuditEntry.compute_hash). O frontend recomputa o hash
    # client-side (Web Crypto não tem SHA-3; usa js-sha3) e compara com entry_hash.
    # Fornecemos a canônica porque JSON não preserva a repr de floats do Python,
    # inviabilizando uma reconstrução byte-a-byte no browser.
    canonical: str


def _audit_canonical(event_type: str, event: Any) -> str:
    """Reproduz a serialização canônica usada no cálculo do entry_hash (core)."""
    return json.dumps(
        {
            "event_id": event.event_id,
            "timestamp": event.timestamp,
            "event_type": event_type,
            "subject": event.subject,
            "tenant_id": event.tenant_id,
            "resource_id": event.resource_id,
            "outcome": event.outcome,
            "details": event.details,
            "previous_hash": event.previous_hash,
        },
        sort_keys=True,
        ensure_ascii=True,
    )


class AuditTrailResponse(BaseModel):
    dossie_id: str
    entries: list[AuditTrailEntry]
    total: int


# ─── Subscriptions ───────────────────────────────────────────────────────────


@api_router.post(
    "/subscriptions",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        401: {"description": "Não autenticado"},
        403: {"description": "Scope insuficiente"},
        422: {"description": "Payload inválido"},
        503: {"description": "Kafka indisponível"},
    },
)
async def create_subscription(
    request: Request,
    body: SubscriptionRequest,
    identity: ServiceIdentity = Depends(require_scope(Scope.SUBSCRIPTION_WRITE)),
) -> SubscriptionResponse:
    """
    Inicia um novo dossiê de subscrição: valida o payload, publica o evento
    `subscription.initiated` no Kafka e registra a abertura na trilha de auditoria.

    Retorna 202 (Accepted) — o processamento agêntico é assíncrono.
    """
    correlation_id = request.state.correlation_id
    dossie_id = f"DOS-{uuid.uuid4().hex[:12].upper()}"

    event = SubscriptionInitiatedEvent(
        correlation_id=correlation_id,
        tenant_id=identity.tenant_id,
        dossie_id=dossie_id,
        producer_cpf_hash=body.producer_cpf_hash,
        car_number=body.car_number,
        property_area_ha=body.property_area_ha,
        location=body.location,
        credit_amount_brl=body.credit_amount_brl,
        credit_purpose=body.credit_purpose,
        requested_by=body.requested_by,
    )

    producer = request.app.state.kafka_producer
    try:
        await producer.publish(
            topic="agrotrust.subscription.initiated",
            event=event,
            partition_key=identity.tenant_id,
        )
    except Exception as exc:
        logger.error("publish_failed", error=str(exc), dossie_id=dossie_id)
        raise HTTPException(status_code=503, detail="Falha ao publicar evento") from exc

    audit = get_audit_repo()
    await audit.append(
        event_type=AuditEventType.SUBSCRIPTION_INITIATED,
        subject=identity.subject,
        tenant_id=identity.tenant_id,
        resource_id=dossie_id,
        outcome="success",
        details={
            "car_number": body.car_number,
            "credit_amount_brl": body.credit_amount_brl,
            "credit_purpose": body.credit_purpose,
        },
    )

    logger.info("subscription_initiated", dossie_id=dossie_id)
    return SubscriptionResponse(
        dossie_id=dossie_id,
        status="initiated",
        correlation_id=correlation_id,
        submitted_at=event.timestamp,
    )


@api_router.get("/subscriptions", response_model=DossieListResponse)
async def list_subscriptions(
    identity: ServiceIdentity = Depends(require_scope(Scope.SUBSCRIPTION_READ)),
    session: AsyncSession = Depends(get_session),
    page: int = Query(1, ge=1, description="Página (1-indexed)"),
    limit: int = Query(20, ge=1, le=100, description="Itens por página"),
    status_filter: str | None = Query(None, alias="status", description="Filtra por status"),
    verdict: str | None = Query(None, description="Filtra por veredicto"),
) -> DossieListResponse:
    """
    Lista paginada dos dossiês do tenant (mais recentes primeiro), com filtros
    opcionais por status e veredicto. Isolamento por tenant no WHERE.
    """
    repo = DossieRepository(session)
    offset = (page - 1) * limit
    records = await repo.list_by_tenant(
        identity.tenant_id,
        limit=limit,
        offset=offset,
        status_filter=status_filter,
        verdict_filter=verdict,
    )
    total = await repo.count_by_tenant(
        identity.tenant_id,
        status_filter=status_filter,
        verdict_filter=verdict,
    )
    pages = (total + limit - 1) // limit if total else 0
    return DossieListResponse(
        items=[DossieListItem.from_record(r) for r in records],
        total=total,
        page=page,
        pages=pages,
    )


@api_router.get(
    "/subscriptions/{dossie_id}",
    response_model=DossieDetailResponse,
    responses={404: {"description": "Dossiê não encontrado"}},
)
async def get_subscription(
    dossie_id: str,
    identity: ServiceIdentity = Depends(require_scope(Scope.SUBSCRIPTION_READ)),
    session: AsyncSession = Depends(get_session),
) -> DossieDetailResponse:
    """
    Consulta o dossiê na projeção de leitura `dossies` do PostgreSQL.

    O acesso é isolado por tenant (get_by_id filtra tenant_id no WHERE), evitando
    vazamento de dados entre cooperativas.
    """
    record = await DossieRepository(session).get_by_id(dossie_id, identity.tenant_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Dossiê '{dossie_id}' não encontrado")

    return DossieDetailResponse(
        dossie_id=record.dossie_id,
        tenant_id=record.tenant_id,
        status=record.status,
        verdict=record.verdict,
        car_number=record.car_number,
        credit_amount_brl=record.credit_amount_brl,
        credit_purpose=record.credit_purpose,
        property_area_ha=record.property_area_ha,
        composite_score=record.composite_score,
        esg_score=record.esg_score,
        financial_score=record.financial_score,
        security_score=record.security_score,
        approved_amount_brl=record.approved_amount_brl,
        rejection_reasons=record.rejection_reasons,
        xai_summary=record.xai_consolidated_rationale.get("scores", {}),
        processing_time_ms=record.processing_time_ms,
        created_at=record.created_at.isoformat() if record.created_at else None,
        updated_at=record.updated_at.isoformat() if record.updated_at else None,
    )


@api_router.get(
    "/subscriptions/{dossie_id}/audit-trail",
    response_model=AuditTrailResponse,
    responses={404: {"description": "Dossiê não encontrado"}},
)
async def get_audit_trail(
    dossie_id: str,
    identity: ServiceIdentity = Depends(require_scope(Scope.AUDIT_READ)),
) -> AuditTrailResponse:
    """Retorna trilha completa de auditoria (hash chain) do dossiê."""
    audit = get_audit_repo()
    entries = await audit.get_by_resource(dossie_id)
    relevant = [e for e in entries if e.tenant_id == identity.tenant_id]
    if not relevant:
        raise HTTPException(status_code=404, detail=f"Dossiê '{dossie_id}' não encontrado")

    return AuditTrailResponse(
        dossie_id=dossie_id,
        total=len(relevant),
        entries=[
            AuditTrailEntry(
                event_id=e.event_id,
                timestamp=e.timestamp,
                event_type=e.event_type.value,
                subject=e.subject,
                tenant_id=e.tenant_id,
                resource_id=e.resource_id,
                outcome=e.outcome,
                details=e.details,
                previous_hash=e.previous_hash,
                entry_hash=e.entry_hash,
                canonical=_audit_canonical(e.event_type.value, e),
            )
            for e in relevant
        ],
    )


# ─── Infra (público) ─────────────────────────────────────────────────────────


@infra_router.get("/health")
async def health() -> dict[str, Any]:
    """Liveness probe – usado por Kubernetes."""
    return {
        "status": "ok",
        "service": "agrotrust-gateway",
        "topics_configured": len(TOPICS),
    }


@infra_router.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> str:
    """Métricas Prometheus-compatible (texto)."""
    return get_metrics().render_prometheus()


# ─── Autenticação (público, DEV) ─────────────────────────────────────────────


@infra_router.post(
    "/token",
    response_model=TokenResponse,
    responses={401: {"description": "Credenciais inválidas"}},
    tags=["auth"],
)
async def login(
    request: Request,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> TokenResponse:
    """
    Login (OAuth2 password flow) — **apenas DEV**. Valida `username`/`password`
    contra a lista mock (`dev_users`) e emite um JWT com os scopes do perfil.

    Em produção este endpoint delega para o IdP corporativo (OIDC). O token é
    devolvido no corpo; o frontend o mantém somente em memória (nunca em storage).
    """
    user = authenticate_dev_user(form.username, form.password)

    audit = get_audit_repo()
    if user is None:
        await audit.append(
            event_type=AuditEventType.AUTH_FAILURE,
            subject=form.username[:64],
            tenant_id="unknown",
            resource_id="token",
            outcome="failure",
            details={"reason": "invalid_credentials"},
        )
        logger.warning("login_failed", username=form.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário ou senha inválidos",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_service: TokenService = getattr(request.app.state, "token_service", None) or TokenService()
    access_token = token_service.issue_user_token(
        user_id=user.username,
        tenant_id=user.tenant_id,
        scopes=list(user.scopes),
    )
    await audit.append(
        event_type=AuditEventType.AUTH_SUCCESS,
        subject=user.username,
        tenant_id=user.tenant_id,
        resource_id="token",
        outcome="success",
        details={"scopes": [s.value for s in user.scopes]},
    )
    logger.info("login_success", username=user.username, tenant_id=user.tenant_id)
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        scopes=[s.value for s in user.scopes],
        tenant_id=user.tenant_id,
    )
