"""
Tests unitários – Orquestrador LangGraph + VerdictEngine.

Cenários:
  1. Pipeline completo (ESG approved + financial sólido + security low) → approved
  2. Short-circuit: fraude crítica na etapa security → verdict=rejected sem chamar ESG/Financeiro
  3. composite_score dentro dos pesos esperados (0.35*ESG + 0.45*FIN + 0.20*SEC)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agents.esg.schemas import ESGOutput
from agents.financial.schemas import FinancialOutput
from agents.orchestrator.graph import run_orchestrator
from agents.orchestrator.state import DossieState
from agents.security.schemas import SecurityOutput
from core.events.schemas import ESGComplianceStatus

_BASE_STATE: DossieState = DossieState(
    dossie_id="dossie-orch-test",
    correlation_id="corr-orch-001",
    tenant_id="tenant-test",
    producer_cpf_hash="a3f5b8c2d1e4f7a0b3c6d9e2f5a8b1c4d7e0f3a6b9c2d5e8f1a4b7c0d3e6f9",
    car_number="MT-5107602-C3E4B5A6D7E8F9A0B1C2D3E4F5A6B7C8",
    property_area_ha=300.0,
    location_lat=-12.5,
    location_lon=-55.3,
    location_estado="MT",
    credit_amount_brl=200_000.0,
    credit_purpose="custeio",
    requested_by="analista-001",
)

_SEC_LOW = SecurityOutput(
    dossie_id="dossie-orch-test",
    liveness_passed=True,
    deepfake_probability=0.02,
    voice_clone_probability=0.01,
    digital_mask_probability=0.03,
    title_verified_on_blockchain=True,
    blockchain_tx_hash="550e8400-e29b-41d4-a716-446655440000",
    fraud_risk_level="low",
    kyc_passed=True,
    xai_rationale={
        "decision": "fraud_risk=low kyc=True",
        "factors": [{"name": "liveness_score", "weight": 0.35, "value": 0.95, "impact": "positive"}],
        "confidence": 0.97,
        "model_version": "security-mock-0.1.0",
        "timestamp": "2026-05-06T00:00:00+00:00",
    },
)

_SEC_CRITICAL = SecurityOutput(
    dossie_id="dossie-orch-test",
    liveness_passed=False,
    deepfake_probability=0.95,
    voice_clone_probability=0.80,
    digital_mask_probability=0.90,
    title_verified_on_blockchain=True,
    blockchain_tx_hash=None,
    fraud_risk_level="critical",
    kyc_passed=False,
    xai_rationale={
        "decision": "fraud_risk=critical kyc=False",
        "factors": [{"name": "deepfake_probability", "weight": 0.35, "value": 0.95, "impact": "negative"}],
        "confidence": 0.97,
        "model_version": "security-mock-0.1.0",
        "timestamp": "2026-05-06T00:00:00+00:00",
    },
)

_ESG_APPROVED = ESGOutput(
    dossie_id="dossie-orch-test",
    car_status="ativo",
    car_verified_at="2026-05-06T00:00:00+00:00",
    deforestation_detected=False,
    deforestation_area_ha=0.0,
    gee_satellite_images_used=3,
    vc_credential_valid=True,
    compliance_status=ESGComplianceStatus.APPROVED,
    confidence_score=0.92,
    xai_rationale={
        "decision": "approved",
        "factors": [],
        "confidence": 0.92,
        "model_version": "esg-0.1.0",
        "timestamp": "2026-05-06T00:00:00+00:00",
    },
)

_FIN_SOLID = FinancialOutput(
    dossie_id="dossie-orch-test",
    trust_score=780.0,
    open_finance_data_months=18,
    avg_monthly_revenue_brl=40_000.0,
    debt_to_income_ratio=0.18,
    existing_rural_credit_brl=20_000.0,
    recommended_credit_limit_brl=200_000.0,
    risk_tier="A",
    xai_rationale={
        "decision": "trust_score=780 tier=A",
        "factors": [],
        "confidence": 0.95,
        "model_version": "financial-ridge-0.1.0",
        "timestamp": "2026-05-06T00:00:00+00:00",
    },
)


@pytest.fixture(autouse=True)
def reset_orchestrator_graph():
    """Reseta o singleton do grafo para isolar cada teste."""
    import agents.orchestrator.graph as _mod
    original = _mod._ORCHESTRATOR_GRAPH
    _mod._ORCHESTRATOR_GRAPH = None
    yield
    _mod._ORCHESTRATOR_GRAPH = original


@pytest.mark.asyncio
async def test_full_pipeline_approved():
    """Pipeline completo com todos os agentes → verdict=approved + composite_score correto."""
    from agents.esg.agent import ESGAuditorAgent
    from agents.financial.agent import FinancialAnalystAgent
    from agents.security.agent import SecurityGuardAgent

    with (
        patch.object(SecurityGuardAgent, "run", new=AsyncMock(return_value=_SEC_LOW)),
        patch.object(ESGAuditorAgent, "run", new=AsyncMock(return_value=_ESG_APPROVED)),
        patch.object(FinancialAnalystAgent, "run", new=AsyncMock(return_value=_FIN_SOLID)),
    ):
        final_state = await run_orchestrator(_BASE_STATE)

    verdict = final_state["verdict"]
    assert verdict is not None
    assert verdict.verdict == "approved"
    assert verdict.approved_amount_brl == pytest.approx(200_000.0)
    assert verdict.rejection_reasons == []

    # Verifica composite_score: 0.35*1000 + 0.45*780 + 0.20*950
    expected_esg = 1000.0   # APPROVED
    expected_fin = 780.0    # trust_score
    expected_sec = 950.0    # low = 950
    expected_composite = 0.35 * expected_esg + 0.45 * expected_fin + 0.20 * expected_sec
    assert verdict.composite_score == pytest.approx(expected_composite, abs=1.0)
    assert verdict.composite_score >= 600.0


@pytest.mark.asyncio
async def test_short_circuit_critical_fraud():
    """
    Fraude crítica na etapa security deve curto-circuitar o pipeline:
    ESGAuditorAgent e FinancialAnalystAgent NÃO devem ser invocados.
    """
    from agents.esg.agent import ESGAuditorAgent
    from agents.financial.agent import FinancialAnalystAgent
    from agents.security.agent import SecurityGuardAgent

    esg_mock = AsyncMock(return_value=_ESG_APPROVED)
    fin_mock = AsyncMock(return_value=_FIN_SOLID)

    with (
        patch.object(SecurityGuardAgent, "run", new=AsyncMock(return_value=_SEC_CRITICAL)),
        patch.object(ESGAuditorAgent, "run", new=esg_mock),
        patch.object(FinancialAnalystAgent, "run", new=fin_mock),
    ):
        final_state = await run_orchestrator(_BASE_STATE)

    verdict = final_state["verdict"]
    assert verdict.verdict == "rejected"
    assert verdict.rejection_reasons  # LGPD Art. 20 – obrigatório no rejected
    assert any("fraude" in r.lower() or "critical" in r.lower() for r in verdict.rejection_reasons)

    # Agentes ESG e Financeiro não devem ter sido chamados
    esg_mock.assert_not_awaited()
    fin_mock.assert_not_awaited()
