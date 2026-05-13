"""
Tests unitários – SubscriptionConsumer.

services/agent-runner/ usa hífen no caminho → carregamos o módulo via importlib.

Cenários:
  1. handle() com evento válido → run_orchestrator chamado + producer.publish chamado
     com tópico correto e partition_key=dossie_id.
  2. handle() com orquestrador falhando → exceção propagada + audit.append com
     outcome="failure" registrado.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from core.events.schemas import (
    PropertyLocation,
    SubscriptionInitiatedEvent,
    SubscriptionVerdictEvent,
)
from core.security.audit import AuditEventType, AuditRepository

# ─── Carrega SubscriptionConsumer via importlib (diretório com hífen) ─────────

_CONSUMER_PATH = Path(__file__).parent.parent.parent / "services" / "agent-runner" / "consumer.py"
_MOD_NAME = "agent_runner_consumer"

if _MOD_NAME not in sys.modules:
    _spec = importlib.util.spec_from_file_location(_MOD_NAME, _CONSUMER_PATH)
    assert _spec and _spec.loader
    _consumer_mod = importlib.util.module_from_spec(_spec)
    sys.modules[_MOD_NAME] = _consumer_mod
    _spec.loader.exec_module(_consumer_mod)  # type: ignore[union-attr]

_consumer_mod = sys.modules[_MOD_NAME]
SubscriptionConsumer = _consumer_mod.SubscriptionConsumer
TOPIC_VERDICT = _consumer_mod.TOPIC_VERDICT

# ─── Fixtures e dados de teste ────────────────────────────────────────────────

_DOSSIE_ID = "dossie-consumer-test"
_CORR_ID = "corr-consumer-001"
_TENANT_ID = "tenant-consumer"

_VALID_EVENT = SubscriptionInitiatedEvent(
    dossie_id=_DOSSIE_ID,
    correlation_id=_CORR_ID,
    tenant_id=_TENANT_ID,
    producer_cpf_hash="a3f5b8c2d1e4f7a0b3c6d9e2f5a8b1c4d7e0f3a6b9c2d5e8f1a4b7c0d3e6f9",
    car_number="MT-5107602-C3E4B5A6D7E8F9A0B1C2D3E4F5A6B7C8",
    property_area_ha=200.0,
    location=PropertyLocation(
        latitude=-12.5,
        longitude=-55.3,
        municipio="Sorriso",
        estado="MT",
        biome="Cerrado",
    ),
    credit_amount_brl=80_000.0,
    credit_purpose="custeio",
    requested_by="analista-test",
)

_VERDICT = SubscriptionVerdictEvent(
    correlation_id=_CORR_ID,
    tenant_id=_TENANT_ID,
    dossie_id=_DOSSIE_ID,
    verdict="approved",
    approved_amount_brl=80_000.0,
    rejection_reasons=[],
    esg_score=1000.0,
    financial_score=780.0,
    security_score=950.0,
    composite_score=876.0,
    xai_consolidated_rationale={"scores": {"composite": 876.0}},
    processing_time_ms=1200,
)

# Estado final simulado que o orquestrador retornaria
_FINAL_STATE: dict = {
    "dossie_id": _DOSSIE_ID,
    "correlation_id": _CORR_ID,
    "tenant_id": _TENANT_ID,
    "verdict": _VERDICT,
}


def _make_consumer() -> tuple:
    """Retorna (consumer, mock_producer, real_audit_repo)."""
    mock_producer = AsyncMock()
    mock_producer.publish = AsyncMock()
    audit_repo = AuditRepository()
    consumer = SubscriptionConsumer(producer=mock_producer, audit_repo=audit_repo)
    return consumer, mock_producer, audit_repo


# ─── Testes ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_valid_event_calls_orchestrator_and_publishes():
    """
    Evento válido:
    - run_orchestrator deve ser chamado uma vez com o estado derivado do evento.
    - producer.publish deve ser chamado com tópico=agrotrust.subscription.verdict
      e partition_key=dossie_id.
    - audit.append deve registrar SUBSCRIPTION_INITIATED + SUBSCRIPTION_APPROVED.
    """
    consumer, mock_producer, audit_repo = _make_consumer()

    with patch(f"{_MOD_NAME}.run_orchestrator", new=AsyncMock(return_value=_FINAL_STATE)):
        await consumer.handle(_VALID_EVENT)

    mock_producer.publish.assert_awaited_once()
    publish_kwargs = mock_producer.publish.await_args.kwargs
    assert publish_kwargs["topic"] == TOPIC_VERDICT
    assert publish_kwargs["partition_key"] == _DOSSIE_ID
    assert isinstance(publish_kwargs["event"], SubscriptionVerdictEvent)

    # Auditoria: SUBSCRIPTION_INITIATED + SUBSCRIPTION_APPROVED
    entries = await audit_repo.get_by_resource(_DOSSIE_ID)
    assert len(entries) == 2
    assert entries[0].event_type == AuditEventType.SUBSCRIPTION_INITIATED
    assert entries[0].outcome == "success"
    assert entries[1].event_type == AuditEventType.SUBSCRIPTION_APPROVED
    assert entries[1].outcome == "success"


@pytest.mark.asyncio
async def test_handle_orchestrator_failure_records_audit_and_reraises():
    """
    Orquestrador lança exceção:
    - A exceção deve ser propagada (para o BaseConsumer enviá-la à DLQ).
    - audit.append deve ter sido chamado 2 vezes:
        1. SUBSCRIPTION_INITIATED (antes do orchestrador) – outcome=success
        2. AGENT_INVOKED            (captura do erro)       – outcome=failure
    - producer.publish NÃO deve ser chamado.
    """
    consumer, mock_producer, audit_repo = _make_consumer()

    boom = RuntimeError("orchestrator explodiu")

    with (
        patch(f"{_MOD_NAME}.run_orchestrator", new=AsyncMock(side_effect=boom)),
        pytest.raises(RuntimeError, match="orchestrator explodiu"),
    ):
        await consumer.handle(_VALID_EVENT)

    mock_producer.publish.assert_not_awaited()

    entries = await audit_repo.get_by_resource(_DOSSIE_ID)
    assert len(entries) == 2

    initiated = entries[0]
    assert initiated.event_type == AuditEventType.SUBSCRIPTION_INITIATED
    assert initiated.outcome == "success"

    failure = entries[1]
    assert failure.event_type == AuditEventType.AGENT_INVOKED
    assert failure.outcome == "failure"
    assert "RuntimeError" in failure.details.get("error", "")
