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

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.engine import get_session
from core.db.repositories.dossie import DossieRepository
from core.events.schemas import PropertyLocation, SubscriptionInitiatedEvent
from core.events.topics import TOPICS
from core.security.audit import AuditEventType, get_audit_repo
from core.security.iam import Scope, ServiceIdentity

from .dependencies import require_scope
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
    outcome: str
    details: dict[str, Any]
    entry_hash: str


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
                outcome=e.outcome,
                details=e.details,
                entry_hash=e.entry_hash,
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
