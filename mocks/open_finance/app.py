"""
AgroTrust AI – Mock Open Finance Brasil.

Simula o ecossistema Open Finance BR (Banco Central – Fase 2/3) para
coleta de dados financeiros de produtores rurais: contas, crédito rural
existente, fluxo de caixa, investimentos.

Referências:
  - Banco Central: Manual de Escopo Open Finance BR v3.0
  - Pluggy/Belvo como agregadores homologados
"""
from __future__ import annotations

import asyncio
import random
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel

app = FastAPI(
    title="Mock Open Finance BR",
    description="Simulação Open Finance Brasil para AgroTrust AI",
    version="1.0.0",
)


# ─── Modelos ──────────────────────────────────────────────────────────────────

class BankAccount(BaseModel):
    account_id: str
    bank_ispb: str
    bank_name: str
    account_type: str      # "corrente" | "poupança" | "pagamento"
    currency: str = "BRL"
    balance: float
    available_balance: float
    credit_limit: float = 0.0


class Transaction(BaseModel):
    transaction_id: str
    date: str
    amount: float               # positivo = crédito, negativo = débito
    description: str
    category: str               # "receita_agro" | "insumos" | "folha" | etc.
    type: str                   # "credit" | "debit"


class RuralCreditOperation(BaseModel):
    operation_id: str
    institution: str
    modality: str               # "custeio" | "investimento" | "comercialização"
    amount_brl: float
    outstanding_balance_brl: float
    interest_rate_pct: float
    start_date: str
    due_date: str
    status: str                 # "ativo" | "quitado" | "em_atraso"
    collateral_type: str        # "penhor_safra" | "hipoteca" | "CPR"


class FinancialSummary(BaseModel):
    consent_id: str
    cpf_hash: str
    months_of_history: int
    total_accounts: int
    total_balance_brl: float
    avg_monthly_revenue_brl: float
    avg_monthly_expenses_brl: float
    avg_monthly_agro_revenue_brl: float
    debt_to_income_ratio: float
    rural_credit_operations: list[RuralCreditOperation]
    total_rural_credit_brl: float
    defaulted_operations: int
    data_quality_score: float   # 0-1, baseado na completude dos dados


# ─── Base simulada ────────────────────────────────────────────────────────────

def _gen_transactions(months: int, monthly_revenue: float) -> list[Transaction]:
    txs = []
    today = date.today()
    for m in range(months):
        base_date = today - timedelta(days=30 * m)
        # Receita safra (concentrada em mai/jun e out/nov)
        is_harvest_month = base_date.month in {5, 6, 10, 11}
        revenue = monthly_revenue * (2.5 if is_harvest_month else 0.6)
        txs.append(Transaction(
            transaction_id=str(uuid.uuid4()),
            date=(base_date - timedelta(days=random.randint(0, 25))).isoformat(),
            amount=round(revenue + random.uniform(-revenue * 0.1, revenue * 0.1), 2),
            description="Venda soja – Tradig XYZ" if is_harvest_month else "Adiantamento cooperativa",
            category="receita_agro",
            type="credit",
        ))
        # Insumos
        txs.append(Transaction(
            transaction_id=str(uuid.uuid4()),
            date=(base_date - timedelta(days=random.randint(5, 20))).isoformat(),
            amount=-round(monthly_revenue * random.uniform(0.15, 0.35), 2),
            description="Compra insumos – Cooperativa Agro",
            category="insumos",
            type="debit",
        ))
    return txs


_PRODUCERS: dict[str, dict[str, Any]] = {
    "CONSENT_REGULAR_001": {
        "cpf_hash": "sha3-cpf-hash-001",
        "monthly_revenue": 85_000.0,
        "dti": 0.28,
        "has_rural_credit": True,
        "rural_credit_status": "ativo",
        "rural_credit_amount": 450_000.0,
        "defaulted": 0,
    },
    "CONSENT_HIGH_DTI_002": {
        "cpf_hash": "sha3-cpf-hash-002",
        "monthly_revenue": 32_000.0,
        "dti": 0.71,   # Alto DTI – risco elevado
        "has_rural_credit": True,
        "rural_credit_status": "em_atraso",
        "rural_credit_amount": 280_000.0,
        "defaulted": 2,
    },
    "CONSENT_NEW_PRODUCER_003": {
        "cpf_hash": "sha3-cpf-hash-003",
        "monthly_revenue": 18_000.0,
        "dti": 0.15,
        "has_rural_credit": False,
        "rural_credit_amount": 0.0,
        "defaulted": 0,
    },
}


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "mock-open-finance-br"}


@app.get("/api/v1/consents/{consent_id}/summary", response_model=FinancialSummary)
async def get_financial_summary(
    consent_id: str,
    months: int = Query(default=6, ge=1, le=24),
    x_api_key: str = Header(default="mock-key"),
) -> FinancialSummary:
    """
    Retorna resumo financeiro consolidado via consentimento Open Finance.
    Simula latência real de agregação multi-banco (1s – 5s).
    """
    await asyncio.sleep(random.uniform(1.0, 5.0))

    if random.random() < 0.04:
        raise HTTPException(status_code=503, detail="Open Finance agregador temporariamente indisponível")

    if consent_id not in _PRODUCERS:
        raise HTTPException(status_code=404, detail=f"Consentimento '{consent_id}' não encontrado ou expirado")

    p = _PRODUCERS[consent_id]
    monthly = p["monthly_revenue"]
    txs = _gen_transactions(months, monthly)
    credit_ops: list[RuralCreditOperation] = []

    if p["has_rural_credit"]:
        credit_ops.append(RuralCreditOperation(
            operation_id=str(uuid.uuid4()),
            institution="Sicredi MT",
            modality="custeio",
            amount_brl=p["rural_credit_amount"],
            outstanding_balance_brl=p["rural_credit_amount"] * random.uniform(0.3, 0.9),
            interest_rate_pct=round(random.uniform(7.5, 12.5), 2),
            start_date=(date.today() - timedelta(days=180)).isoformat(),
            due_date=(date.today() + timedelta(days=180)).isoformat(),
            status=p["rural_credit_status"],
            collateral_type="penhor_safra",
        ))

    return FinancialSummary(
        consent_id=consent_id,
        cpf_hash=p["cpf_hash"],
        months_of_history=months,
        total_accounts=random.randint(2, 4),
        total_balance_brl=round(monthly * random.uniform(0.5, 2.0), 2),
        avg_monthly_revenue_brl=round(monthly, 2),
        avg_monthly_expenses_brl=round(monthly * p["dti"] * 2, 2),
        avg_monthly_agro_revenue_brl=round(monthly * 0.85, 2),
        debt_to_income_ratio=p["dti"],
        rural_credit_operations=credit_ops,
        total_rural_credit_brl=p["rural_credit_amount"],
        defaulted_operations=p["defaulted"],
        data_quality_score=round(random.uniform(0.85, 0.98), 3),
    )


@app.get("/api/v1/consents/{consent_id}/transactions", response_model=list[Transaction])
async def get_transactions(
    consent_id: str,
    months: int = Query(default=3, ge=1, le=12),
    x_api_key: str = Header(default="mock-key"),
) -> list[Transaction]:
    """Extrato de transações por consentimento."""
    await asyncio.sleep(random.uniform(0.5, 2.0))

    if consent_id not in _PRODUCERS:
        raise HTTPException(status_code=404, detail="Consentimento não encontrado")

    p = _PRODUCERS[consent_id]
    return _gen_transactions(months, p["monthly_revenue"])


@app.post("/api/v1/consents")
async def create_consent(
    cpf_hash: str,
    permissions: list[str],
    x_api_key: str = Header(default="mock-key"),
) -> dict[str, Any]:
    """Cria consentimento Open Finance (simplificado para mock)."""
    return {
        "consent_id": f"CONSENT_{uuid.uuid4().hex[:8].upper()}",
        "status": "AUTHORISED",
        "expires_at": (datetime.now(UTC) + timedelta(days=180)).isoformat(),
        "permissions": permissions,
        "creation_date": datetime.now(UTC).isoformat(),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004, log_level="info")
