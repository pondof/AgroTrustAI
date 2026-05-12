"""
AgroTrust AI – Ferramentas do Agente Financeiro (Trust Score+ XGBoost).

Modelo:        XGBoost Regressor (n=200 árvores, depth=4, lr=0.05)
Features:      avg_revenue_norm, dti_inverted, history_months_norm, default_rate_inverted
Target:        Trust Score+ (0-1000) – ordinal contínuo (cutoff 600 = aprovado)
Dataset:       5000 amostras sintéticas (seed=42) com não-linearidades realistas:
                 - bônus multiplicativo: receita alta × DTI baixo
                 - penalidade quadrática: inadimplência > 0
Métricas:      AUC-ROC binário (threshold=600) deve ser ≥ 0.82 no hold-out 20%.
XAI:           SHAP TreeExplainer (compatível com XGBoost, exato em vez de aproximado).
Geração:       2026-05-11 — dataset regenerado a cada cold start (lazy singleton).

SHAP é síncrono → executado em thread pool via asyncio.to_thread().
"""
from __future__ import annotations

import asyncio
from typing import Any

import numpy as np
import numpy.typing as npt
import structlog
import xgboost as xgb
from pydantic import BaseModel, Field
from sklearn.metrics import mean_squared_error, roc_auc_score
from sklearn.model_selection import train_test_split
from tenacity import retry, stop_after_attempt, wait_exponential

logger = structlog.get_logger(__name__)

# ─── Constantes do modelo ─────────────────────────────────────────────────────

FEATURE_NAMES: list[str] = [
    "avg_revenue_norm",      # receita média normalizada (0-1)
    "dti_inverted",          # 1 - DTI  (quanto menor o DTI, maior o score)
    "history_months_norm",   # meses de histórico / 24
    "default_rate_inverted", # 1 - taxa_inadimplência
]

_REVENUE_MAX: float = 500_000.0   # R$ 500k/mês como teto de normalização
_MONTHS_MAX: float = 24.0
_APPROVAL_THRESHOLD: float = 600.0   # cutoff binário para AUC-ROC
_TARGET_AUC: float = 0.82
_DATASET_SIZE: int = 5000

RISK_TIERS: list[tuple[float, str]] = [
    (800.0, "A"),
    (650.0, "B"),
    (500.0, "C"),
    (350.0, "D"),
    (0.0,   "E"),
]

# XGBoost hyperparameters (especificação Fase 1)
_XGB_PARAMS: dict[str, Any] = {
    "n_estimators": 200,
    "max_depth": 4,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "random_state": 42,
    "n_jobs": -1,
    "objective": "reg:squarederror",
    "tree_method": "hist",
}


# ─── Modelo XGBoost (singleton lazy-loaded) ───────────────────────────────────

_MODEL: xgb.XGBRegressor | None = None
_BACKGROUND: npt.NDArray[np.float64] | None = None


def _generate_synthetic_dataset(
    n: int = _DATASET_SIZE,
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """
    Dataset sintético com não-linearidades — justifica o uso de tree-based model:

      base score (linear):  0.30*rev + 0.35*dti_inv + 0.20*hist + 0.15*default_inv
      bônus multiplicativo: +150 quando (rev >= 0.6 AND dti_inv >= 0.7)
      penalidade quadrática: -200 * (1 - default_inv)^2   (inadimplência custa mais que linear)

    Saída: (X, y) com X.shape=(n,4) e y em [0, 1000].
    """
    rng = np.random.default_rng(42)
    avg_rev = rng.uniform(0.0, 1.0, n).astype(np.float64)
    dti_inv = 1.0 - rng.uniform(0.0, 1.0, n).astype(np.float64)
    hist_norm = rng.uniform(0.0, 1.0, n).astype(np.float64)
    default_inv = 1.0 - rng.uniform(0.0, 0.5, n).astype(np.float64)

    X: npt.NDArray[np.float64] = np.column_stack(
        [avg_rev, dti_inv, hist_norm, default_inv]
    ).astype(np.float64)

    base: npt.NDArray[np.float64] = (
        0.30 * avg_rev * 1000.0
        + 0.35 * dti_inv * 1000.0
        + 0.20 * hist_norm * 1000.0
        + 0.15 * default_inv * 1000.0
    )

    # Não-linearidade 1: bônus multiplicativo para "produtor forte"
    multiplicative_bonus = np.where((avg_rev >= 0.6) & (dti_inv >= 0.7), 150.0, 0.0)

    # Não-linearidade 2: penalidade quadrática por inadimplência
    default_rate = 1.0 - default_inv
    quadratic_penalty = 200.0 * (default_rate**2)

    noise = rng.normal(0.0, 20.0, n)
    y_raw = base + multiplicative_bonus - quadratic_penalty + noise
    y: npt.NDArray[np.float64] = np.clip(y_raw, 0.0, 1000.0).astype(np.float64)

    return X, y


def _get_model() -> tuple[xgb.XGBRegressor, npt.NDArray[np.float64]]:
    """
    Treina o XGBoost lazy. Valida em hold-out 20%:
      - AUC-ROC binário (threshold=600) deve ser >= 0.82
      - RMSE registrado em log estruturado

    Retorna (model, background_X) onde background_X é o train set para SHAP.
    """
    global _MODEL, _BACKGROUND
    if _MODEL is not None and _BACKGROUND is not None:
        return _MODEL, _BACKGROUND

    X, y = _generate_synthetic_dataset()
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    model = xgb.XGBRegressor(**_XGB_PARAMS)
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    rmse = float(np.sqrt(mean_squared_error(y_test, y_pred)))

    y_true_binary = (y_test >= _APPROVAL_THRESHOLD).astype(int)
    if len(np.unique(y_true_binary)) > 1:
        auc = float(roc_auc_score(y_true_binary, y_pred))
    else:
        auc = float("nan")

    logger.info(
        "trust_score_model_trained",
        model="XGBRegressor",
        n_estimators=_XGB_PARAMS["n_estimators"],
        max_depth=_XGB_PARAMS["max_depth"],
        n_train=int(X_train.shape[0]),
        n_test=int(X_test.shape[0]),
        rmse=round(rmse, 4),
        auc_roc=round(auc, 4),
        threshold=_APPROVAL_THRESHOLD,
    )

    if not np.isnan(auc) and auc < _TARGET_AUC:
        logger.warning(
            "trust_score_auc_below_target",
            auc_roc=round(auc, 4),
            target=_TARGET_AUC,
            recommendation="rever features ou aumentar dataset/profundidade",
        )

    _MODEL = model
    _BACKGROUND = X_train
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
    model: xgb.XGBRegressor,
    background: npt.NDArray[np.float64],
    x: npt.NDArray[np.float64],
) -> dict[str, float]:
    """
    SHAP TreeExplainer: cálculo exato (não aproximado) para árvores.
    Background opcionalmente usado para baseline (XGBoost intercept).
    """
    import shap

    explainer = shap.TreeExplainer(model, data=background, feature_perturbation="interventional")
    shap_vals = explainer.shap_values(x)
    if shap_vals.ndim == 2:
        row = shap_vals[0]
    else:
        row = shap_vals
    return {FEATURE_NAMES[i]: float(row[i]) for i in range(len(FEATURE_NAMES))}


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
