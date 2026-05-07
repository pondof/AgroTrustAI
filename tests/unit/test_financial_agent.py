"""
Tests unitários – FinancialAnalystAgent.

Cenários:
  1. Dados sólidos (alta receita, baixo DTI, histórico longo) → trust_score alto + tier A/B
  2. Dados ruins (baixa receita, DTI alto, inadimplências) → trust_score baixo + tier D/E
  3. xai_rationale contém chave 'shap' com SHAP values por feature
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agents.financial.agent import FinancialAnalystAgent
from agents.financial.schemas import FinancialInput
from agents.financial.tools import OpenFinanceData

_COMMON_INPUT = FinancialInput(
    dossie_id="dossie-fin-test",
    correlation_id="corr-fin-001",
    tenant_id="tenant-test",
    open_finance_consent_id="CONSENT_REGULAR_001",
    requested_amount_brl=150_000.0,
)

_OPEN_FINANCE_GOOD = OpenFinanceData(
    consent_id="CONSENT_REGULAR_001",
    months_of_history=24,
    avg_monthly_revenue_brl=300_000.0,   # R$300k/mês → avg_rev_norm=0.6
    debt_to_income_ratio=0.10,
    defaulted_operations=0,
    total_rural_credit_brl=30_000.0,
    data_quality_score=0.95,
)

_OPEN_FINANCE_BAD = OpenFinanceData(
    consent_id="CONSENT_REGULAR_001",
    months_of_history=3,
    avg_monthly_revenue_brl=8_000.0,
    debt_to_income_ratio=0.75,
    defaulted_operations=3,
    total_rural_credit_brl=60_000.0,
    data_quality_score=0.70,
)


@pytest.mark.asyncio
async def test_financial_high_trust_score():
    """Produtor com receita alta e DTI baixo deve obter trust_score >= 650 e tier A ou B."""
    with patch(
        "agents.financial.agent.fetch_open_finance",
        new=AsyncMock(return_value=_OPEN_FINANCE_GOOD),
    ):
        agent = FinancialAnalystAgent()
        result = await agent.run(_COMMON_INPUT)

    assert result.trust_score >= 750.0, f"Esperado >=750, obtido {result.trust_score:.1f}"
    assert result.risk_tier in {"A", "B"}
    assert result.debt_to_income_ratio == pytest.approx(0.10)
    assert result.avg_monthly_revenue_brl == pytest.approx(300_000.0)
    assert result.recommended_credit_limit_brl <= _COMMON_INPUT.requested_amount_brl


@pytest.mark.asyncio
async def test_financial_low_trust_score():
    """Produtor com alta inadimplência e DTI > 0.65 deve obter trust_score < 400 e tier D/E."""
    with patch(
        "agents.financial.agent.fetch_open_finance",
        new=AsyncMock(return_value=_OPEN_FINANCE_BAD),
    ):
        agent = FinancialAnalystAgent()
        result = await agent.run(_COMMON_INPUT)

    assert result.trust_score < 400.0, f"Esperado <400, obtido {result.trust_score:.1f}"
    assert result.risk_tier in {"D", "E"}
    assert result.debt_to_income_ratio == pytest.approx(0.75)


@pytest.mark.asyncio
async def test_financial_xai_contains_shap_values():
    """xai_rationale deve conter chave 'shap' com SHAP values para as 4 features."""
    with patch(
        "agents.financial.agent.fetch_open_finance",
        new=AsyncMock(return_value=_OPEN_FINANCE_GOOD),
    ):
        agent = FinancialAnalystAgent()
        result = await agent.run(_COMMON_INPUT)

    assert "shap" in result.xai_rationale, "xai_rationale deve conter 'shap'"
    shap_block = result.xai_rationale["shap"]
    assert "shap_values" in shap_block, "shap block deve ter 'shap_values'"
    shap_values = shap_block["shap_values"]

    expected_features = {
        "avg_revenue_norm",
        "dti_inverted",
        "history_months_norm",
        "default_rate_inverted",
    }
    assert expected_features.issubset(shap_values.keys()), (
        f"SHAP values ausentes: {expected_features - set(shap_values.keys())}"
    )
    # todos os valores devem ser float finitos
    for feat, val in shap_values.items():
        assert isinstance(val, float), f"SHAP[{feat}] não é float"
        assert -1000.0 < val < 1000.0, f"SHAP[{feat}]={val} fora do intervalo esperado"
