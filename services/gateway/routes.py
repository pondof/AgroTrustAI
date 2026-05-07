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


class SubscriptionStatusResponse(BaseModel):
    dossie_id: str
    status: str
    last_event: str | None
    score: float | None = None


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
    response_model=SubscriptionStatusResponse,
    responses={404: {"description": "Dossiê não encontrado"}},
)
async def get_subscription_status(
    dossie_id: str,
    identity: ServiceIdentity = Depends(require_scope(Scope.SUBSCRIPTION_READ)),
) -> SubscriptionStatusResponse:
    """
    Consulta o status atual do dossiê.

    Versão dev: deriva o status a partir da trilha de auditoria. Em produção
    consulta o projection `dossies` do PostgreSQL.
    """
    audit = get_audit_repo()
    entries = await audit.get_by_resource(dossie_id)
    if not entries:
        raise HTTPException(status_code=404, detail=f"Dossiê '{dossie_id}' não encontrado")

    # tenant isolation – evita leak entre cooperativas
    relevant = [e for e in entries if e.tenant_id == identity.tenant_id]
    if not relevant:
        raise HTTPException(status_code=404, detail=f"Dossiê '{dossie_id}' não encontrado")

    last = relevant[-1]
    return SubscriptionStatusResponse(
        dossie_id=dossie_id,
        status=last.event_type.value,
        last_event=last.timestamp,
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
