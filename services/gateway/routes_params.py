"""
AgroTrust AI – Rotas de parametrização e leitura agregada (Fase 2).

Endpoints:
  - GET  /api/v1/params                       (lê risk_params do tenant)   [admin:params]
  - PUT  /api/v1/params                       (atualiza risk_params)       [admin:params]
  - GET  /api/v1/subscriptions/{id}/xai       (XAI completo do veredicto)  [subscription:read]
  - GET  /api/v1/stats                        (estatísticas do tenant)     [subscription:read]

Todo acesso é isolado por tenant (WHERE tenant_id). A parametrização de pesos exige
que w_esg + w_financial + w_security == 1.0 (validado no request e no CHECK do banco).
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.engine import get_session
from core.db.repositories.dossie import DossieRepository, DossieStatsDTO
from core.db.repositories.params import RiskParams, RiskParamsCache, RiskParamsRepository
from core.security.iam import Scope, ServiceIdentity

from .dependencies import require_scope

logger = structlog.get_logger(__name__)

params_router = APIRouter(prefix="/api/v1", tags=["params", "analytics"])

_WEIGHT_SUM_TOLERANCE = 1e-6


# ─── Modelos ──────────────────────────────────────────────────────────────────


class RiskParamsRequest(BaseModel):
    """Payload do PUT /params. Pesos devem somar exatamente 1.0."""

    w_esg: float = Field(ge=0.0, le=1.0)
    w_financial: float = Field(ge=0.0, le=1.0)
    w_security: float = Field(ge=0.0, le=1.0)
    approve_threshold: float = Field(gt=0.0, le=1000.0)
    manual_threshold: float = Field(gt=0.0, le=1000.0)
    max_dti: float = Field(gt=0.0, le=1.0)
    max_credit_multiplier: float = Field(gt=0.0)

    @model_validator(mode="after")
    def validate_weights(self) -> RiskParamsRequest:
        total = self.w_esg + self.w_financial + self.w_security
        if abs(total - 1.0) > _WEIGHT_SUM_TOLERANCE:
            raise ValueError(f"w_esg + w_financial + w_security deve ser exatamente 1.0 (recebido {total:.4f})")
        if self.manual_threshold > self.approve_threshold:
            raise ValueError("manual_threshold não pode exceder approve_threshold")
        return self


class RiskParamsResponse(BaseModel):
    tenant_id: str
    w_esg: float
    w_financial: float
    w_security: float
    approve_threshold: float
    manual_threshold: float
    max_dti: float
    max_credit_multiplier: float
    updated_by: str


class XaiDetailResponse(BaseModel):
    dossie_id: str
    verdict: str | None
    composite_score: float | None
    rationale: dict[str, Any]
    breakdown: dict[str, Any]


def _to_response(params: RiskParams) -> RiskParamsResponse:
    return RiskParamsResponse(**params.model_dump())


# ─── Parametrização de risco ─────────────────────────────────────────────────


@params_router.get("/params", response_model=RiskParamsResponse)
async def get_params(
    identity: ServiceIdentity = Depends(require_scope(Scope.ADMIN_PARAMS)),
    session: AsyncSession = Depends(get_session),
) -> RiskParamsResponse:
    """Lê os parâmetros de risco do tenant (ou os defaults, se não configurados)."""
    params = await RiskParamsRepository(session).get_or_defaults(identity.tenant_id)
    return _to_response(params)


@params_router.put("/params", response_model=RiskParamsResponse)
async def put_params(
    body: RiskParamsRequest,
    identity: ServiceIdentity = Depends(require_scope(Scope.ADMIN_PARAMS)),
    session: AsyncSession = Depends(get_session),
) -> RiskParamsResponse:
    """
    Atualiza os parâmetros de risco do tenant. Após salvar, invalida o cache do
    VerdictEngine para o tenant (o upsert já repovoa o cache com os novos valores).
    """
    params = RiskParams(
        tenant_id=identity.tenant_id,
        w_esg=body.w_esg,
        w_financial=body.w_financial,
        w_security=body.w_security,
        approve_threshold=body.approve_threshold,
        manual_threshold=body.manual_threshold,
        max_dti=body.max_dti,
        max_credit_multiplier=body.max_credit_multiplier,
        updated_by=identity.subject,
    )
    # Invalida explicitamente antes do upsert (idempotente com o put subsequente).
    RiskParamsCache.invalidate(identity.tenant_id)
    saved = await RiskParamsRepository(session).upsert(params)
    logger.info("risk_params_updated", tenant_id=identity.tenant_id, updated_by=identity.subject)
    return _to_response(saved)


# ─── XAI completo do veredicto ───────────────────────────────────────────────


@params_router.get(
    "/subscriptions/{dossie_id}/xai",
    response_model=XaiDetailResponse,
    responses={404: {"description": "Dossiê não encontrado"}},
)
async def get_subscription_xai(
    dossie_id: str,
    identity: ServiceIdentity = Depends(require_scope(Scope.SUBSCRIPTION_READ)),
    session: AsyncSession = Depends(get_session),
) -> XaiDetailResponse:
    """
    Detalhamento XAI completo do veredicto, formatado para consumo do frontend (Fase 3).
    Retorna o rationale consolidado + um breakdown por agente.
    """
    record = await DossieRepository(session).get_by_id(dossie_id, identity.tenant_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Dossiê '{dossie_id}' não encontrado")

    rationale = record.xai_consolidated_rationale
    breakdown = {
        "esg": {
            "score": record.esg_score,
            "rationale": rationale.get("esg_rationale", {}),
        },
        "financial": {
            "score": record.financial_score,
            "rationale": rationale.get("financial_rationale", {}),
        },
        "security": {
            "score": record.security_score,
            "rationale": rationale.get("security_rationale", {}),
        },
        "composite": {
            "score": record.composite_score,
            "verdict": record.verdict,
            "rejection_reasons": record.rejection_reasons,
        },
    }
    return XaiDetailResponse(
        dossie_id=record.dossie_id,
        verdict=record.verdict,
        composite_score=record.composite_score,
        rationale=rationale,
        breakdown=breakdown,
    )


# ─── Estatísticas do tenant ──────────────────────────────────────────────────


@params_router.get("/stats", response_model=DossieStatsDTO)
async def get_stats(
    identity: ServiceIdentity = Depends(require_scope(Scope.SUBSCRIPTION_READ)),
    session: AsyncSession = Depends(get_session),
) -> DossieStatsDTO:
    """Estatísticas agregadas dos dossiês do tenant (dashboard)."""
    return await DossieRepository(session).get_stats(identity.tenant_id)
