"""
AgroTrust AI – Runner assíncrono do orquestrador para validação M1.

Executa cenários M1 em paralelo controlado (asyncio.Semaphore), captura erros
em vez de propagar (para permitir análise agregada) e valida cada
SubscriptionVerdictEvent contra os critérios M1:

  1. Estrutura Pydantic correta (already enforced pelo retorno tipado).
  2. xai_consolidated_rationale presente com chaves obrigatórias.
  3. rejection_reasons obrigatório quando verdict='rejected' (LGPD Art. 20).
  4. processing_time_ms < 30s.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import structlog

from agents.orchestrator.graph import run_orchestrator
from agents.orchestrator.state import DossieState
from core.events.schemas import SubscriptionVerdictEvent
from scripts.m1.scenarios import M1Scenario

logger = structlog.get_logger(__name__)

_MAX_PROCESSING_MS = 30_000
_REQUIRED_XAI_KEYS: tuple[str, ...] = (
    "scores",
    "esg_rationale",
    "financial_rationale",
    "security_rationale",
)


@dataclass(slots=True)
class M1Result:
    """Resultado de um único dossiê processado + validação."""

    scenario: M1Scenario
    verdict: SubscriptionVerdictEvent | None
    error: str | None
    processing_time_ms: int
    validation_errors: list[str]


def _build_initial_state(scenario: M1Scenario) -> DossieState:
    """Pré-popula a DossieState para evitar a derivação automática do dispatch."""
    return DossieState(
        dossie_id=scenario.dossie_id,
        correlation_id=scenario.correlation_id,
        tenant_id=scenario.tenant_id,
        producer_cpf_hash=scenario.cpf_hash,
        car_number=scenario.car_number,
        property_area_ha=scenario.property_area_ha,
        location_lat=scenario.location_lat,
        location_lon=scenario.location_lon,
        location_estado=scenario.location_estado,
        credit_amount_brl=scenario.credit_amount_brl,
        credit_purpose=scenario.credit_purpose,
        requested_by=scenario.requested_by,
        # Campos pré-derivados — bypass dos _derive_* do nó dispatch
        holder_did=scenario.holder_did,
        open_finance_consent_id=scenario.consent_id,
        session_id=scenario.session_id,
        media_url=scenario.media_url,
    )


def _validate_verdict(
    verdict: SubscriptionVerdictEvent | None,
    processing_ms: int,
) -> list[str]:
    """Aplica os 4 critérios M1 ao veredicto. Retorna lista vazia se OK."""
    errors: list[str] = []
    if verdict is None:
        errors.append("verdict_event_missing")
        return errors

    if verdict.verdict not in {"approved", "manual_review", "rejected"}:
        errors.append(f"invalid_verdict_value:{verdict.verdict}")

    xai = verdict.xai_consolidated_rationale
    if not isinstance(xai, dict):
        errors.append("xai_not_dict")
    else:
        missing = [k for k in _REQUIRED_XAI_KEYS if k not in xai]
        if missing:
            errors.append(f"xai_missing_keys:{','.join(missing)}")
        # Validação granular do bloco 'scores'
        scores = xai.get("scores")
        if not isinstance(scores, dict) or "composite" not in scores:
            errors.append("xai_scores_malformed")

    if verdict.verdict == "rejected" and not verdict.rejection_reasons:
        errors.append("rejected_without_reasons_lgpd_violation")

    if processing_ms > _MAX_PROCESSING_MS:
        errors.append(f"processing_too_slow:{processing_ms}ms")

    return errors


async def _run_one(sem: asyncio.Semaphore, scenario: M1Scenario) -> M1Result:
    async with sem:
        t0 = time.perf_counter()
        verdict: SubscriptionVerdictEvent | None = None
        error: str | None = None
        try:
            final_state = await run_orchestrator(_build_initial_state(scenario))
            verdict = final_state.get("verdict")
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            logger.error(
                "m1_dossie_orchestrator_failed",
                dossie_id=scenario.dossie_id,
                error=error,
            )
        processing_ms = int((time.perf_counter() - t0) * 1000)

    validation = _validate_verdict(verdict, processing_ms)

    logger.info(
        "m1_dossie_processed",
        dossie_id=scenario.dossie_id,
        category=scenario.category,
        variant=scenario.variant,
        expected=scenario.expected_verdict,
        actual=verdict.verdict if verdict else "error",
        processing_ms=processing_ms,
        ok=not validation and error is None,
    )

    return M1Result(
        scenario=scenario,
        verdict=verdict,
        error=error,
        processing_time_ms=processing_ms,
        validation_errors=validation,
    )


async def run_all(
    scenarios: list[M1Scenario],
    *,
    max_concurrent: int = 10,
) -> list[M1Result]:
    """Executa todos os cenários com no máximo `max_concurrent` em paralelo."""
    sem = asyncio.Semaphore(max_concurrent)
    tasks = [_run_one(sem, s) for s in scenarios]
    return list(await asyncio.gather(*tasks))
