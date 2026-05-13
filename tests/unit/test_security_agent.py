"""
Tests unitários – SecurityGuardAgent.

Cenários:
  1. Deepfake crítico (prob > 0.8) → fraud_risk_level="critical", kyc_passed=False
  2. Liveness falhou         → fraud_risk_level="critical"
  3. Tudo normal (baixa prob, liveness OK) → fraud_risk_level="low", kyc_passed=True
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agents.security.agent import SecurityGuardAgent
from agents.security.schemas import SecurityInput
from agents.security.tools import BlockchainResult, DeepfakeResult, LivenessResult

_COMMON_INPUT = SecurityInput(
    dossie_id="dossie-sec-test",
    correlation_id="corr-sec-001",
    tenant_id="tenant-test",
    session_id="session-abc123",
    media_url="https://biometria.agrotrust.ai/media/dossie-sec-test.enc",
    car_number="MT-5107602-C3E4B5A6D7E8F9A0B1C2D3E4F5A6B7C8",
    owner_cpf_hash="a3f5b8c2d1e4f7a0b3c6d9e2f5a8b1c4d7e0f3a6b9c2d5e8f1a4b7c0d3e6f9",
)

_LIVENESS_PASS = LivenessResult(session_id=_COMMON_INPUT.session_id, passed=True, score=0.95)
_LIVENESS_FAIL = LivenessResult(session_id=_COMMON_INPUT.session_id, passed=False, score=0.05)

_DEEPFAKE_CRITICAL = DeepfakeResult(
    media_url_hash="abc123",
    deepfake_probability=0.92,
    voice_clone_probability=0.78,
    digital_mask_probability=0.85,
)
_DEEPFAKE_LOW = DeepfakeResult(
    media_url_hash="abc123",
    deepfake_probability=0.02,
    voice_clone_probability=0.01,
    digital_mask_probability=0.03,
)

_BLOCKCHAIN_OK = BlockchainResult(
    car_number=_COMMON_INPUT.car_number,
    verified=True,
    tx_hash="550e8400-e29b-41d4-a716-446655440000",
)


@pytest.mark.asyncio
async def test_security_critical_deepfake():
    """Deepfake probability > 0.8 deve resultar em fraud_risk_level='critical'."""
    with (
        patch(
            "agents.security.agent.run_liveness_check",
            new=AsyncMock(return_value=_LIVENESS_PASS),
        ),
        patch(
            "agents.security.agent.detect_deepfake",
            new=AsyncMock(return_value=_DEEPFAKE_CRITICAL),
        ),
        patch(
            "agents.security.agent.verify_title_blockchain",
            new=AsyncMock(return_value=_BLOCKCHAIN_OK),
        ),
    ):
        agent = SecurityGuardAgent()
        result = await agent.run(_COMMON_INPUT)

    assert result.fraud_risk_level == "critical"
    assert result.kyc_passed is False
    assert result.deepfake_probability == pytest.approx(0.92)


@pytest.mark.asyncio
async def test_security_liveness_failed_critical():
    """Liveness falhou → fraud_risk_level='critical' mesmo com deepfake baixo."""
    with (
        patch(
            "agents.security.agent.run_liveness_check",
            new=AsyncMock(return_value=_LIVENESS_FAIL),
        ),
        patch(
            "agents.security.agent.detect_deepfake",
            new=AsyncMock(return_value=_DEEPFAKE_LOW),
        ),
        patch(
            "agents.security.agent.verify_title_blockchain",
            new=AsyncMock(return_value=_BLOCKCHAIN_OK),
        ),
    ):
        agent = SecurityGuardAgent()
        result = await agent.run(_COMMON_INPUT)

    assert result.fraud_risk_level == "critical"
    assert result.liveness_passed is False
    assert result.kyc_passed is False


@pytest.mark.asyncio
async def test_security_low_risk_kyc_passed():
    """Liveness OK + deepfake baixo + blockchain verificado → fraud_risk='low', kyc=True."""
    with (
        patch(
            "agents.security.agent.run_liveness_check",
            new=AsyncMock(return_value=_LIVENESS_PASS),
        ),
        patch(
            "agents.security.agent.detect_deepfake",
            new=AsyncMock(return_value=_DEEPFAKE_LOW),
        ),
        patch(
            "agents.security.agent.verify_title_blockchain",
            new=AsyncMock(return_value=_BLOCKCHAIN_OK),
        ),
    ):
        agent = SecurityGuardAgent()
        result = await agent.run(_COMMON_INPUT)

    assert result.fraud_risk_level == "low"
    assert result.liveness_passed is True
    assert result.kyc_passed is True
    assert result.title_verified_on_blockchain is True
    assert "factors" in result.xai_rationale
