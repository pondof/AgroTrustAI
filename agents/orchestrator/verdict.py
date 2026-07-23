"""
AgroTrust AI – VerdictEngine: compõe scores dos 3 agentes em veredicto final.

composite = 0.35 * esg_score + 0.45 * financial_score + 0.20 * security_score
  (todos na escala 0-1000)

approved:       composite >= 600 AND ESG approved AND fraud_risk not critical/high
manual_review:  composite >= 450 OU qualquer agente retornou warning/pending_docs
rejected:       demais casos (com rejection_reasons obrigatório – LGPD Art. 20)
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from agents.esg.schemas import ESGOutput
from agents.financial.schemas import FinancialOutput
from agents.orchestrator.state import DossieState
from agents.security.schemas import SecurityOutput
from core.db.repositories.params import RiskParams, resolve_params
from core.events.schemas import ESGComplianceStatus, SubscriptionVerdictEvent

logger = structlog.get_logger(__name__)

# Pesos/limiares padrão vivem em core.db.repositories.params (RiskParams.defaults):
# 0.35/0.45/0.20 e limiares 600/450. VerdictEngine resolve por tenant via cache.


def _esg_to_score(esg: ESGOutput) -> float:
    mapping = {
        ESGComplianceStatus.APPROVED: 1000.0,
        ESGComplianceStatus.WARNING: 600.0,
        ESGComplianceStatus.PENDING_DOCS: 500.0,
        ESGComplianceStatus.REJECTED: 0.0,
    }
    return mapping.get(esg.compliance_status, 0.0)


def _security_to_score(sec: SecurityOutput) -> float:
    mapping = {
        "low": 950.0,
        "medium": 700.0,
        "high": 300.0,
        "critical": 0.0,
    }
    return mapping.get(sec.fraud_risk_level, 0.0)


def _build_rejection_reasons(
    esg: ESGOutput | None,
    fin: FinancialOutput | None,
    sec: SecurityOutput | None,
    composite: float,
) -> list[str]:
    reasons: list[str] = []
    if esg and esg.compliance_status == ESGComplianceStatus.REJECTED:
        reasons.append(f"Não conformidade ambiental: {esg.compliance_status.value}")
    if esg and esg.deforestation_detected:
        reasons.append(f"Desmatamento detectado: {esg.deforestation_area_ha:.1f} ha (pós-2008)")
    if fin and fin.trust_score < 350:
        reasons.append(f"Trust Score+ insuficiente: {fin.trust_score:.0f}/1000")
    if fin and fin.debt_to_income_ratio > 0.65:
        reasons.append(f"DTI acima do limite: {fin.debt_to_income_ratio:.0%}")
    if sec and sec.fraud_risk_level in {"critical", "high"}:
        reasons.append(f"Risco de fraude {sec.fraud_risk_level} detectado")
    if not reasons:
        reasons.append(f"Composite score insuficiente: {composite:.0f}/1000")
    return reasons


class VerdictEngine:
    """
    Compõe o veredicto final a partir das saídas dos 3 agentes.

    Os pesos e limiares vêm de risk_params do tenant (via RiskParamsCache) quando
    disponíveis; caso contrário usa os defaults hardcoded (0.35/0.45/0.20, 600/450).
    Um override explícito de RiskParams pode ser injetado (útil em testes).
    """

    def __init__(self, params: RiskParams | None = None) -> None:
        self._params_override = params

    def _params(self, state: DossieState) -> RiskParams:
        if self._params_override is not None:
            return self._params_override
        return resolve_params(state.get("tenant_id", ""))

    def compute(self, state: DossieState) -> SubscriptionVerdictEvent:
        esg: ESGOutput | None = state.get("esg_output")
        fin: FinancialOutput | None = state.get("financial_output")
        sec: SecurityOutput | None = state.get("security_output")

        params = self._params(state)

        start_time = float(state.get("start_time_unix") or time.time())
        processing_ms = int((time.time() - start_time) * 1000)

        # Short-circuit: apenas security disponível (fraud crítico)
        if sec and not esg and not fin:
            return self._short_circuit_verdict(state, sec, processing_ms, params)

        # Fallback seguro se algum agente falhou
        esg_score = _esg_to_score(esg) if esg else 0.0
        fin_score = fin.trust_score if fin else 0.0
        sec_score = _security_to_score(sec) if sec else 0.0

        composite = params.w_esg * esg_score + params.w_financial * fin_score + params.w_security * sec_score

        esg_approved = esg and esg.compliance_status == ESGComplianceStatus.APPROVED
        fraud_ok = sec and sec.fraud_risk_level not in {"critical", "high"}
        has_warning = (
            (esg and esg.compliance_status in {ESGComplianceStatus.WARNING, ESGComplianceStatus.PENDING_DOCS})
            or (sec and sec.fraud_risk_level == "medium")
            or not esg
            or not fin
            or not sec
        )

        if composite >= params.approve_threshold and esg_approved and fraud_ok:
            verdict_str = "approved"
            approved_amount: float | None = fin.recommended_credit_limit_brl if fin else None
            rejection_reasons: list[str] = []
        elif composite >= params.manual_threshold or has_warning:
            verdict_str = "manual_review"
            approved_amount = None
            rejection_reasons = []
        else:
            verdict_str = "rejected"
            approved_amount = None
            rejection_reasons = _build_rejection_reasons(esg, fin, sec, composite)

        xai_consolidated: dict[str, Any] = {
            "scores": {
                "esg": esg_score,
                "financial": fin_score,
                "security": sec_score,
                "composite": round(composite, 2),
            },
            "esg_rationale": esg.xai_rationale if esg else {},
            "financial_rationale": fin.xai_rationale if fin else {},
            "security_rationale": sec.xai_rationale if sec else {},
        }

        logger.info(
            "verdict_computed",
            dossie_id=state.get("dossie_id"),
            verdict=verdict_str,
            composite=round(composite, 2),
            correlation_id=state.get("correlation_id"),
        )

        return SubscriptionVerdictEvent(
            correlation_id=state.get("correlation_id", ""),
            tenant_id=state.get("tenant_id", ""),
            dossie_id=state.get("dossie_id", ""),
            verdict=verdict_str,
            approved_amount_brl=approved_amount,
            rejection_reasons=rejection_reasons,
            esg_score=esg_score,
            financial_score=fin_score,
            security_score=sec_score,
            composite_score=round(composite, 2),
            xai_consolidated_rationale=xai_consolidated,
            processing_time_ms=processing_ms,
        )

    def _short_circuit_verdict(
        self,
        state: DossieState,
        sec: SecurityOutput,
        processing_ms: int,
        params: RiskParams,
    ) -> SubscriptionVerdictEvent:
        reason = state.get("short_circuit_reason", "Fraude crítica detectada pelo Agente de Segurança")
        logger.warning(
            "verdict_short_circuit",
            dossie_id=state.get("dossie_id"),
            fraud_risk=sec.fraud_risk_level,
        )
        sec_score = _security_to_score(sec)
        composite = params.w_security * sec_score
        return SubscriptionVerdictEvent(
            correlation_id=state.get("correlation_id", ""),
            tenant_id=state.get("tenant_id", ""),
            dossie_id=state.get("dossie_id", ""),
            verdict="rejected",
            approved_amount_brl=None,
            rejection_reasons=[reason],
            esg_score=0.0,
            financial_score=0.0,
            security_score=sec_score,
            composite_score=round(composite, 2),
            # Mantém o contrato XAI consolidado mesmo em short-circuit: ESG/Fin
            # ficam vazios (não rodaram) mas as 4 chaves do contrato existem.
            xai_consolidated_rationale={
                "scores": {
                    "esg": 0.0,
                    "financial": 0.0,
                    "security": sec_score,
                    "composite": round(composite, 2),
                },
                "esg_rationale": {},
                "financial_rationale": {},
                "security_rationale": sec.xai_rationale,
                "short_circuit": True,
                "short_circuit_reason": reason,
            },
            processing_time_ms=processing_ms,
        )
