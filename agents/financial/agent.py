"""AgroTrust AI – FinancialAnalystAgent."""
from __future__ import annotations

import structlog
from pydantic import BaseModel

from agents.base import AgentExecutionError, BaseAgent, XAIFactor
from agents.financial.schemas import FinancialInput, FinancialOutput
from agents.financial.tools import (
    OpenFinanceData,
    assess_risk_tier,
    calculate_trust_score_plus,
    fetch_open_finance,
)
from core.config.settings import get_settings

logger = structlog.get_logger(__name__)

_MAX_CREDIT_MULTIPLIER: float = 12.0  # limite = 12x receita mensal média


class FinancialAnalystAgent(BaseAgent):
    """
    Agente de análise financeira.
    Trust Score+ via Ridge+SHAP. Limite de crédito = 12x receita mensal.
    """

    MODEL_VERSION = "financial-ridge-0.1.0"

    async def run(self, input_data: BaseModel) -> FinancialOutput:
        if not isinstance(input_data, FinancialInput):
            raise TypeError(f"Esperava FinancialInput, recebeu {type(input_data)}")

        fin_input: FinancialInput = input_data
        log = logger.bind(
            correlation_id=fin_input.correlation_id,
            dossie_id=fin_input.dossie_id,
        )
        log.info("financial_agent_started")

        try:
            settings = get_settings()
            data: OpenFinanceData = await fetch_open_finance(
                consent_id=fin_input.open_finance_consent_id,
                base_url=settings.gov_apis.open_finance_base_url,
                timeout=settings.gov_apis.request_timeout,
            )
            trust_score, shap_factors = await calculate_trust_score_plus(data)
            risk_tier = assess_risk_tier(trust_score)

            # Limite recomendado: menor entre 12x receita e valor solicitado
            recommended = min(
                data.avg_monthly_revenue_brl * _MAX_CREDIT_MULTIPLIER,
                fin_input.requested_amount_brl,
            )

            xai = self._build_xai_rationale(
                decision=f"trust_score={trust_score:.0f} tier={risk_tier}",
                factors=[
                    XAIFactor(
                        name="avg_monthly_revenue",
                        weight=0.30,
                        value=round(data.avg_monthly_revenue_brl, 2),
                        impact="positive" if data.avg_monthly_revenue_brl > 20_000 else "negative",
                    ),
                    XAIFactor(
                        name="debt_to_income_ratio",
                        weight=0.35,
                        value=round(data.debt_to_income_ratio, 4),
                        impact="negative" if data.debt_to_income_ratio > 0.5 else "positive",
                    ),
                    XAIFactor(
                        name="history_months",
                        weight=0.20,
                        value=data.months_of_history,
                        impact="positive" if data.months_of_history >= 6 else "negative",
                    ),
                    XAIFactor(
                        name="defaulted_operations",
                        weight=0.15,
                        value=data.defaulted_operations,
                        impact="negative" if data.defaulted_operations > 0 else "positive",
                    ),
                ],
                confidence=min(data.data_quality_score, 1.0),
            )
            xai["shap"] = shap_factors

        except AgentExecutionError:
            raise
        except Exception as exc:
            log.error("financial_agent_failed", error=str(exc))
            raise AgentExecutionError(
                correlation_id=fin_input.correlation_id,
                agent_name="FinancialAnalystAgent",
                original_exception=exc,
            ) from exc

        log.info(
            "financial_agent_completed",
            trust_score=round(trust_score, 2),
            risk_tier=risk_tier,
        )

        return FinancialOutput(
            dossie_id=fin_input.dossie_id,
            trust_score=trust_score,
            open_finance_data_months=data.months_of_history,
            avg_monthly_revenue_brl=data.avg_monthly_revenue_brl,
            debt_to_income_ratio=data.debt_to_income_ratio,
            existing_rural_credit_brl=data.total_rural_credit_brl,
            recommended_credit_limit_brl=recommended,
            risk_tier=risk_tier,
            xai_rationale=xai,
        )
