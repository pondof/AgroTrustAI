"""
Test de integração – pipeline completo E2E.

Moca todas as chamadas HTTP externas (SICAR, GEE, Dataprev, Open Finance)
com respx, enquanto as ferramentas de segurança rodam como mocks determinísticos.
Valida que o resultado final é um SubscriptionVerdictEvent bem-formado.
"""
from __future__ import annotations

import pytest
import respx
from httpx import Response

from agents.orchestrator.graph import run_orchestrator
from agents.orchestrator.state import DossieState
from core.events.schemas import SubscriptionVerdictEvent

# ─── Estado inicial do teste ──────────────────────────────────────────────────

_DOSSIE_ID = "dossie-integ-001"
_CORR_ID = "corr-integ-001"
_TENANT_ID = "tenant-integ-test"

# car_number sem palavras-chave "DEFOREST" ou "CANCELADO" → consent REGULAR
_CAR = "MT-5107602-C3E4B5A6D7E8F9A0B1C2D3E4F5A6B7C8"
_CPF_HASH = "a3f5b8c2d1e4f7a0b3c6d9e2f5a8b1c4d7e0f3a6b9c2d5e8f1a4b7c0d3e6f9"

_INITIAL_STATE: DossieState = DossieState(
    dossie_id=_DOSSIE_ID,
    correlation_id=_CORR_ID,
    tenant_id=_TENANT_ID,
    producer_cpf_hash=_CPF_HASH,
    car_number=_CAR,
    property_area_ha=300.0,
    location_lat=-12.5,
    location_lon=-55.3,
    location_estado="MT",
    credit_amount_brl=120_000.0,
    credit_purpose="custeio",
    requested_by="analista-integ",
)

# ─── Respostas dos mocks HTTP ─────────────────────────────────────────────────

_SICAR_RESPONSE = {
    "car_number": _CAR,
    "status": "ativo",
    "compliance_status": "regular",
    "area_desmatamento_ha": 0.0,
    "area_total_ha": 300.0,
}

_GEE_RESPONSE = {
    "car_number": _CAR,
    "deforestation_detected": False,
    "deforestation_area_ha": 0.0,
    "confidence_score": 0.97,
    "biome": "Cerrado",
    "polygons": {"type": "FeatureCollection", "features": []},
}

_DATAPREV_RESPONSE = {
    "holder_did": f"did:gov:br:{_CPF_HASH[:32]}",
    "verified": True,
    "is_revoked": False,
    "chain_of_trust": ["Dataprev", "Gov.br"],
}

_OPEN_FINANCE_RESPONSE = {
    "consent_id": "CONSENT_REGULAR_001",
    "months_of_history": 12,
    "avg_monthly_revenue_brl": 38_000.0,
    "debt_to_income_ratio": 0.22,
    "defaulted_operations": 0,
    "total_rural_credit_brl": 15_000.0,
    "data_quality_score": 0.92,
}


@pytest.fixture(autouse=True)
def reset_orchestrator_graph():
    import agents.orchestrator.graph as _mod
    original = _mod._ORCHESTRATOR_GRAPH
    _mod._ORCHESTRATOR_GRAPH = None
    yield
    _mod._ORCHESTRATOR_GRAPH = original


@pytest.mark.asyncio
@respx.mock
async def test_full_pipeline_produces_valid_verdict():
    """
    E2E: HTTP APIs mockadas com respx + ferramentas security determinísticas.
    Deve produzir um SubscriptionVerdictEvent válido com correlation_id e dossie_id corretos.
    """
    # SICAR mock
    respx.get("http://localhost:8001/api/v1/car/" + _CAR).mock(
        return_value=Response(200, json=_SICAR_RESPONSE)
    )
    # GEE mock
    respx.get("http://localhost:8002/api/v1/deforestation/" + _CAR).mock(
        return_value=Response(200, json=_GEE_RESPONSE)
    )
    # Dataprev mock (DID derivado de cpf_hash[:32])
    derived_did = f"did:gov:br:{_CPF_HASH[:32]}"
    respx.get(f"http://localhost:8003/api/v1/credentials/{derived_did}/verify").mock(
        return_value=Response(200, json=_DATAPREV_RESPONSE)
    )
    # Open Finance mock
    respx.get("http://localhost:8004/api/v1/consents/CONSENT_REGULAR_001/summary").mock(
        return_value=Response(200, json=_OPEN_FINANCE_RESPONSE)
    )

    final_state = await run_orchestrator(_INITIAL_STATE)

    verdict: SubscriptionVerdictEvent | None = final_state.get("verdict")
    assert verdict is not None, "Orquestrador deve produzir um veredicto"
    assert isinstance(verdict, SubscriptionVerdictEvent)

    # Identidade do evento
    assert verdict.dossie_id == _DOSSIE_ID
    assert verdict.correlation_id == _CORR_ID
    assert verdict.tenant_id == _TENANT_ID

    # Estrutura obrigatória
    assert verdict.verdict in {"approved", "manual_review", "rejected"}
    assert 0.0 <= verdict.composite_score <= 1000.0
    assert verdict.processing_time_ms >= 0
    assert "scores" in verdict.xai_consolidated_rationale

    # LGPD Art. 20: rejected deve ter motivos
    if verdict.verdict == "rejected":
        assert verdict.rejection_reasons, "Veredicto rejected requer rejection_reasons (LGPD Art. 20)"

    # Scores individuais dentro do intervalo válido
    assert 0.0 <= verdict.esg_score <= 1000.0
    assert 0.0 <= verdict.financial_score <= 1000.0
    assert 0.0 <= verdict.security_score <= 1000.0

    # Composite score coerente (pesos 0.35/0.45/0.20)
    expected_composite = (
        0.35 * verdict.esg_score
        + 0.45 * verdict.financial_score
        + 0.20 * verdict.security_score
    )
    assert verdict.composite_score == pytest.approx(expected_composite, abs=1.0)


@pytest.mark.asyncio
@respx.mock
async def test_pipeline_with_deforestation_rejected():
    """
    Propriedade com desmatamento pós-2008 detectado → ESG rejected → verdict rejected ou manual_review.
    """
    gee_defo_response = {
        **_GEE_RESPONSE,
        "deforestation_detected": True,
        "deforestation_area_ha": 35.5,
    }

    respx.get("http://localhost:8001/api/v1/car/" + _CAR).mock(
        return_value=Response(200, json=_SICAR_RESPONSE)
    )
    respx.get("http://localhost:8002/api/v1/deforestation/" + _CAR).mock(
        return_value=Response(200, json=gee_defo_response)
    )
    derived_did = f"did:gov:br:{_CPF_HASH[:32]}"
    respx.get(f"http://localhost:8003/api/v1/credentials/{derived_did}/verify").mock(
        return_value=Response(200, json=_DATAPREV_RESPONSE)
    )
    respx.get("http://localhost:8004/api/v1/consents/CONSENT_REGULAR_001/summary").mock(
        return_value=Response(200, json=_OPEN_FINANCE_RESPONSE)
    )

    final_state = await run_orchestrator(_INITIAL_STATE)
    verdict = final_state["verdict"]

    assert verdict is not None
    # ESG rejected → composite não deve ser suficiente para approval
    assert verdict.esg_score == 0.0, "ESG rejected deve ter score=0"
    assert verdict.verdict in {"rejected", "manual_review"}
