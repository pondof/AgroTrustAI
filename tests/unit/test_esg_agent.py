"""
Tests unitários – ESGAuditorAgent.

3 cenários principais:
  1. Propriedade regular → compliance_status=APPROVED
  2. CAR suspenso       → compliance_status=REJECTED
  3. Desmatamento pós-2008 → compliance_status=REJECTED
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agents.esg.agent import ESGAuditorAgent
from agents.esg.schemas import ESGInput
from agents.esg.tools import CARStatusResult, GEEDeforestationResult, VCCredentialResult
from core.events.schemas import ESGComplianceStatus

_COMMON_INPUT = ESGInput(
    dossie_id="dossie-esg-test",
    correlation_id="corr-esg-001",
    tenant_id="tenant-test",
    car_number="MT-5107602-C3E4B5A6D7E8F9A0B1C2D3E4F5A6B7C8",
    holder_did="did:gov:br:abc123",
    property_area_ha=250.0,
    location_lat=-12.5,
    location_lon=-55.3,
    location_estado="MT",
)

_CAR_ACTIVE = CARStatusResult(
    car_number=_COMMON_INPUT.car_number,
    status="ativo",
    compliance_status="regular",
    area_desmatamento_ha=0.0,
    area_total_ha=250.0,
)
_CAR_SUSPENSO = CARStatusResult(
    car_number=_COMMON_INPUT.car_number,
    status="suspenso",
    compliance_status="irregular",
    area_desmatamento_ha=0.0,
    area_total_ha=250.0,
)

_DEFO_NONE = GEEDeforestationResult(
    car_number=_COMMON_INPUT.car_number,
    deforestation_detected=False,
    deforestation_area_ha=0.0,
    gee_images_count=3,
    confidence_score=0.95,
    biome="Cerrado",
)
_DEFO_POST_2008 = GEEDeforestationResult(
    car_number=_COMMON_INPUT.car_number,
    deforestation_detected=True,
    deforestation_area_ha=47.3,
    gee_images_count=5,
    confidence_score=0.97,
    biome="Amazônia",
)

_VC_VALID = VCCredentialResult(
    holder_did=_COMMON_INPUT.holder_did,
    is_valid=True,
    is_revoked=False,
    chain_of_trust=["Dataprev", "Gov.br"],
)


@pytest.fixture(autouse=True)
def reset_esg_graph():
    """Garante que o grafo LangGraph não fica cacheado entre testes."""
    import agents.esg.agent as _mod

    original = _mod._ESG_GRAPH
    _mod._ESG_GRAPH = None
    yield
    _mod._ESG_GRAPH = original


@pytest.mark.asyncio
async def test_esg_regular_farm_approved():
    """Propriedade com CAR ativo, sem desmatamento, credencial válida → APPROVED."""
    with (
        patch("agents.esg.agent.fetch_car_status", new=AsyncMock(return_value=_CAR_ACTIVE)),
        patch("agents.esg.agent.detect_deforestation", new=AsyncMock(return_value=_DEFO_NONE)),
        patch("agents.esg.agent.verify_vc_credential", new=AsyncMock(return_value=_VC_VALID)),
    ):
        agent = ESGAuditorAgent()
        result = await agent.run(_COMMON_INPUT)

    assert result.compliance_status == ESGComplianceStatus.APPROVED
    assert result.deforestation_detected is False
    assert result.vc_credential_valid is True
    assert result.confidence_score > 0.0
    assert "decision" in result.xai_rationale
    assert result.xai_rationale["decision"] == "approved"


@pytest.mark.asyncio
async def test_esg_suspended_car_rejected():
    """CAR suspenso → REJECTED independentemente dos outros fatores."""
    with (
        patch("agents.esg.agent.fetch_car_status", new=AsyncMock(return_value=_CAR_SUSPENSO)),
        patch("agents.esg.agent.detect_deforestation", new=AsyncMock(return_value=_DEFO_NONE)),
        patch("agents.esg.agent.verify_vc_credential", new=AsyncMock(return_value=_VC_VALID)),
    ):
        agent = ESGAuditorAgent()
        result = await agent.run(_COMMON_INPUT)

    assert result.compliance_status == ESGComplianceStatus.REJECTED
    assert result.car_status == "suspenso"
    reasons = result.xai_rationale.get("reasons", [])
    assert any("suspenso" in r.lower() for r in reasons)


@pytest.mark.asyncio
async def test_esg_deforestation_post_2008_rejected():
    """Desmatamento detectado pós-2008 → REJECTED (Código Florestal Lei 12.651/2012)."""
    with (
        patch("agents.esg.agent.fetch_car_status", new=AsyncMock(return_value=_CAR_ACTIVE)),
        patch(
            "agents.esg.agent.detect_deforestation",
            new=AsyncMock(return_value=_DEFO_POST_2008),
        ),
        patch("agents.esg.agent.verify_vc_credential", new=AsyncMock(return_value=_VC_VALID)),
    ):
        agent = ESGAuditorAgent()
        result = await agent.run(_COMMON_INPUT)

    assert result.compliance_status == ESGComplianceStatus.REJECTED
    assert result.deforestation_detected is True
    assert result.deforestation_area_ha == pytest.approx(47.3, abs=0.1)
    reasons = result.xai_rationale.get("reasons", [])
    assert any("desmatamento" in r.lower() for r in reasons)
