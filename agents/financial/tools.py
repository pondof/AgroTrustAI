"""
AgroTrust AI – Ferramentas do Agente Financeiro.

Trust Score+ usa Ridge treinado em dados sintéticos com SHAP para XAI.
SHAP é síncrono → executado em thread pool via asyncio.to_thread.
"""
from __future__ import annotations

import asyncio
from typing import Any

import numpy as np
import numpy.typing as npt
import structlog
from pydantic import BaseModel, Field
from sklearn.linear_model import Ridge
from tenacity import retry, stop_after_attempt, wait_exponential

logger = structlog.get_logger(__name__)

# ─── Constantes do modelo ─────────────────────────────────────────────────────

FEATURE_NAMES: list[str] = [
    "avg_revenue_norm",     # receita média normalizada (0-1)
    "dti_inverted",         # 1 - DTI  (quanto menor o DTI, maior o score)
    "history_months_norm",  # meses de histórico / 24
    "default_rate_inverted",# 1 - taxa_inadimplência
]

_REVENUE_MAX: float = 500_000.0   # R$ 500k/mês como teto de normalização
_MONTHS_MAX: float = 24.0

RISK_TIERS: list[tuple[float, str]] = [
    (800.0, "A"),
    (650.0, "B"),
    (500.0, "C"),
    (350.0, "D"),
    (0.0,   "E"),
]


# ─── Modelo Ridge (singleton lazy-loaded) ────────────────────────────────────

_MODEL: Ridge | None = None
_BACKGROUND: npt.NDArray[np.float64] | None = None


def _generate_synthetic_dataset(n: int = 1000) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Dados sintéticos para treinar o Ridge e servir como background SHAP."""
    rng = np.random.default_rng(42)
    avg_rev = rng.uniform(0.0, 1.0, n).astype(np.float64)
    dti_inv = 1.0 - rng.uniform(0.0, 1.0, n).astype(np.float64)
    hist_norm = rng.uniform(0.0, 1.0, n).astype(np.float64)
    default_inv = 1.0 - rng.uniform(0.0, 0.5, n).astype(np.float64)
    X: npt.NDArray[np.float64] = np.column_stack(
        [avg_rev, dti_inv, hist_norm, default_inv]
    ).astype(np.float64)
    y: npt.NDArray[np.float64] = np.clip(
        0.30 * avg_rev * 1000
        + 0.35 * dti_inv * 1000
        + 0.20 * hist_norm * 1000
        + 0.15 * default_inv * 1000
        + rng.normal(0, 25, n),
        0.0,
        1000.0,
    ).astype(np.float64)
    return X, y


def _get_model() -> tuple[Ridge, npt.NDArray[np.float64]]:
    global _MODEL, _BACKGROUND
    if _MODEL is None:
        X, y = _generate_synthetic_dataset()
        _MODEL = Ridge(alpha=1.0)
        _MODEL.fit(X, y)
        _BACKGROUND = X
    assert _BACKGROUND is not None  # noqa: S101 – invariante de inicialização
    return _MODEL, _BACKGROUND


# ─── Modelos de dado ─────────────────────────────────────────────────────────


class OpenFinanceData(BaseModel):
    consent_id: str
    months_of_history: int
    avg_monthly_revenue_brl: float
    debt_to_income_ratio: float = Field(ge=0.0)
    defaulted_operations: int = Field(ge=0)
    total_rural_credit_brl: float = Field(ge=0.0)
    data_quality_score: float = Field(ge=0.0, le=1.0)


# ─── Retry decorator ──────────────────────────────────────────────────────────

_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)


# ─── Ferramentas ──────────────────────────────────────────────────────────────


@_retry
async def fetch_open_finance(
    consent_id: str,
    base_url: str,
    timeout: int = 30,
) -> OpenFinanceData:
    """Coleta dados financeiros via consentimento Open Finance BR."""
    import httpx

    async with httpx.AsyncClient(base_url=base_url, timeout=float(timeout)) as client:
        resp = await client.get(
            f"/api/v1/consents/{consent_id}/summary",
            params={"months": 12},
            headers={"X-Api-Key": "mock-key"},
        )
        resp.raise_for_status()
        d = resp.json()
        logger.info(
            "open_finance_fetched",
            consent_id=consent_id,
            dti=d["debt_to_income_ratio"],
            months=d["months_of_history"],
        )
        return OpenFinanceData(
            consent_id=consent_id,
            months_of_history=int(d["months_of_history"]),
            avg_monthly_revenue_brl=float(d["avg_monthly_revenue_brl"]),
            debt_to_income_ratio=float(d["debt_to_income_ratio"]),
            defaulted_operations=int(d.get("defaulted_operations", 0)),
            total_rural_credit_brl=float(d.get("total_rural_credit_brl", 0.0)),
            data_quality_score=float(d.get("data_quality_score", 0.9)),
        )


def _compute_shap_sync(
    model: Ridge,
    background: npt.NDArray[np.float64],
    x: npt.NDArray[np.float64],
) -> dict[str, float]:
    import shap  # type: ignore[import]

    explainer = shap.LinearExplainer(model, background)
    shap_vals: npt.NDArray[np.float64] = explainer.shap_values(x)
    return {FEATURE_NAMES[i]: float(shap_vals[0][i]) for i in range(len(FEATURE_NAMES))}


async def calculate_trust_score_plus(
    data: OpenFinanceData,
) -> tuple[float, dict[str, Any]]:
    """
    Calcula Trust Score+ (0-1000) + SHAP feature importances.

    Retorna (trust_score, xai_factors) onde xai_factors é dict feature→shap_value.
    SHAP roda em thread pool (evita bloquear o event loop).
    """
    model, background = _get_model()

    avg_rev_norm = min(data.avg_monthly_revenue_brl / _REVENUE_MAX, 1.0)
    dti_inv = max(0.0, 1.0 - data.debt_to_income_ratio)
    hist_norm = min(data.months_of_history / _MONTHS_MAX, 1.0)
    default_rate = min(data.defaulted_operations / 5.0, 1.0)
    default_inv = 1.0 - default_rate

    x: npt.NDArray[np.float64] = np.array(
        [[avg_rev_norm, dti_inv, hist_norm, default_inv]], dtype=np.float64
    )

    raw_score: float = float(model.predict(x)[0])
    trust_score = max(0.0, min(1000.0, raw_score))

    shap_values: dict[str, float] = await asyncio.to_thread(
        _compute_shap_sync, model, background, x
    )

    logger.info(
        "trust_score_calculated",
        trust_score=round(trust_score, 2),
        dti=data.debt_to_income_ratio,
        avg_rev=data.avg_monthly_revenue_brl,
    )

    xai_factors: dict[str, Any] = {
        "input_features": {
            "avg_revenue_norm": round(avg_rev_norm, 4),
            "dti_inverted": round(dti_inv, 4),
            "history_months_norm": round(hist_norm, 4),
            "default_rate_inverted": round(default_inv, 4),
        },
        "shap_values": {k: round(v, 4) for k, v in shap_values.items()},
    }
    return trust_score, xai_factors


def assess_risk_tier(trust_score: float) -> str:
    """Enquadra o Trust Score+ em tier de risco A-E."""
    for threshold, tier in RISK_TIERS:
        if trust_score >= threshold:
            return tier
    return "E"
