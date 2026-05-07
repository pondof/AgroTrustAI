"""AgroTrust AI – Schemas de entrada e saída do Agente Financeiro."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FinancialInput(BaseModel):
    dossie_id: str
    correlation_id: str
    tenant_id: str
    open_finance_consent_id: str
    requested_amount_brl: float = Field(gt=0)


class FinancialOutput(BaseModel):
    dossie_id: str
    trust_score: float = Field(ge=0.0, le=1000.0)
    open_finance_data_months: int
    avg_monthly_revenue_brl: float
    debt_to_income_ratio: float
    existing_rural_credit_brl: float
    recommended_credit_limit_brl: float
    risk_tier: str            # "A" | "B" | "C" | "D" | "E"
    xai_rationale: dict[str, Any]
