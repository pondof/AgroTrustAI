"""
AgroTrust AI – SubscriptionConsumer: consome subscription.initiated e executa o orquestrador.

Fluxo:
  1. Evento chega no tópico agrotrust.subscription.initiated
  2. BaseConsumer valida e entrega SubscriptionInitiatedEvent ao handle()
  3. handle() monta DossieState e invoca run_orchestrator()
  4. SubscriptionVerdictEvent publicado em agrotrust.subscription.verdict
  5. Auditoria imutável registrada em cada etapa (LGPD Art. 37)
"""

from __future__ import annotations

import os
import traceback
from typing import Any

import structlog

from agents.orchestrator.graph import run_orchestrator
from agents.orchestrator.state import DossieState
from core.events.consumer import BaseConsumer
from core.events.producer import KafkaProducer
from core.events.schemas import BaseEvent, SubscriptionInitiatedEvent, SubscriptionVerdictEvent
from core.security.audit import AuditEventType, AuditRepository

logger = structlog.get_logger(__name__)

TOPIC_INITIATED = "agrotrust.subscription.initiated"
TOPIC_VERDICT = "agrotrust.subscription.verdict"
GROUP_ID = "agent-runner-orchestrator"


def _build_dossie_state(event: SubscriptionInitiatedEvent) -> DossieState:
    """Converte SubscriptionInitiatedEvent para DossieState inicial."""
    return DossieState(
        dossie_id=event.dossie_id,
        correlation_id=event.correlation_id,
        tenant_id=event.tenant_id,
        producer_cpf_hash=event.producer_cpf_hash,
        car_number=event.car_number,
        property_area_ha=event.property_area_ha,
        location_lat=event.location.latitude,
        location_lon=event.location.longitude,
        location_estado=event.location.estado,
        credit_amount_brl=event.credit_amount_brl,
        credit_purpose=event.credit_purpose,
        requested_by=event.requested_by,
    )


class SubscriptionConsumer(BaseConsumer):
    """
    Consome agrotrust.subscription.initiated, executa o orquestrador multiagente
    e publica o SubscriptionVerdictEvent resultante.
    """

    def __init__(
        self,
        producer: KafkaProducer,
        audit_repo: AuditRepository,
    ) -> None:
        super().__init__(
            topics=[TOPIC_INITIATED],
            group_id=GROUP_ID,
        )
        self._producer = producer
        self._audit = audit_repo
        # Projeção de leitura é opcional: só persiste quando há banco configurado.
        # O evento Kafka permanece a fonte de verdade; o DB é projeção best-effort.
        self._persist = bool(os.environ.get("DB_URL"))
        self._session_factory: Any = None

    def _sessions(self) -> Any:
        """async_sessionmaker lazy (evita tocar no engine quando não há DB)."""
        if self._session_factory is None:
            from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

            from core.db.engine import get_engine

            self._session_factory = async_sessionmaker(
                bind=get_engine(), class_=AsyncSession, expire_on_commit=False
            )
        return self._session_factory

    async def _persist_initiated(self, event: SubscriptionInitiatedEvent) -> None:
        """Materializa o dossiê recém-iniciado. Falha nunca interrompe o consumo."""
        if not self._persist:
            return
        try:
            from core.db.repositories.dossie import DossieCreateDTO, DossieRepository

            async with self._sessions()() as session:
                await DossieRepository(session).create(
                    DossieCreateDTO(
                        dossie_id=event.dossie_id,
                        correlation_id=event.correlation_id,
                        tenant_id=event.tenant_id,
                        producer_cpf_hash=event.producer_cpf_hash,
                        car_number=event.car_number,
                        property_area_ha=event.property_area_ha,
                        credit_amount_brl=event.credit_amount_brl,
                        credit_purpose=event.credit_purpose,
                        requested_by=event.requested_by,
                        status="processing",
                    )
                )
        except Exception as exc:
            logger.warning(
                "dossie_persist_initiated_failed",
                dossie_id=event.dossie_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )

    async def _persist_verdict(self, dossie_id: str, verdict: SubscriptionVerdictEvent) -> None:
        """Projeta o veredicto no DB. Erro é logado mas não rejeita o commit Kafka."""
        if not self._persist:
            return
        try:
            from core.db.repositories.dossie import DossieRepository

            async with self._sessions()() as session:
                await DossieRepository(session).update_verdict(dossie_id, verdict)
        except Exception as exc:
            logger.warning(
                "dossie_persist_verdict_failed",
                dossie_id=dossie_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )

    async def handle(self, event: BaseEvent) -> None:
        if not isinstance(event, SubscriptionInitiatedEvent):
            raise TypeError(f"Esperava SubscriptionInitiatedEvent, recebeu {type(event)}")

        correlation_id = event.correlation_id
        dossie_id = event.dossie_id
        tenant_id = event.tenant_id
        log = logger.bind(correlation_id=correlation_id, dossie_id=dossie_id)

        log.info("orchestrator_run_started")

        await self._audit.append(
            event_type=AuditEventType.SUBSCRIPTION_INITIATED,
            subject=event.requested_by,
            tenant_id=tenant_id,
            resource_id=dossie_id,
            outcome="success",
            details={
                "correlation_id": correlation_id,
                "car_number": event.car_number,
                "credit_amount_brl": event.credit_amount_brl,
            },
        )

        # Persiste a projeção ANTES do orquestrador (status='processing').
        await self._persist_initiated(event)

        try:
            initial_state = _build_dossie_state(event)
            final_state = await run_orchestrator(initial_state)
        except Exception as exc:
            log.error(
                "orchestrator_run_failed",
                error_type=type(exc).__name__,
                error=str(exc),
                traceback=traceback.format_exc(),
            )
            await self._audit.append(
                event_type=AuditEventType.AGENT_INVOKED,
                subject="agent-runner",
                tenant_id=tenant_id,
                resource_id=dossie_id,
                outcome="failure",
                details={"error": type(exc).__name__, "correlation_id": correlation_id},
            )
            raise

        verdict: SubscriptionVerdictEvent | None = final_state.get("verdict")
        if verdict is None:
            raise RuntimeError(f"Orquestrador não produziu veredicto para dossie_id={dossie_id}")

        # Projeta o veredicto no DB ANTES de publicar (best-effort; não bloqueia o commit).
        await self._persist_verdict(dossie_id, verdict)

        await self._producer.publish(
            topic=TOPIC_VERDICT,
            event=verdict,
            partition_key=dossie_id,
        )

        audit_event_type = (
            AuditEventType.SUBSCRIPTION_APPROVED
            if verdict.verdict == "approved"
            else AuditEventType.SUBSCRIPTION_REJECTED
        )
        await self._audit.append(
            event_type=audit_event_type,
            subject="agent-runner",
            tenant_id=tenant_id,
            resource_id=dossie_id,
            outcome="success",
            details=_verdict_audit_details(verdict),
        )

        log.info(
            "orchestrator_run_completed",
            verdict=verdict.verdict,
            composite_score=verdict.composite_score,
            processing_time_ms=verdict.processing_time_ms,
        )


def _verdict_audit_details(verdict: SubscriptionVerdictEvent) -> dict[str, Any]:
    return {
        "verdict": verdict.verdict,
        "composite_score": verdict.composite_score,
        "esg_score": verdict.esg_score,
        "financial_score": verdict.financial_score,
        "security_score": verdict.security_score,
        "approved_amount_brl": verdict.approved_amount_brl,
        "rejection_reasons": verdict.rejection_reasons,
        "processing_time_ms": verdict.processing_time_ms,
    }
