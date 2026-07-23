"""
AgroTrust AI – RiskParamsRepository: parametrização de tolerância a risco por tenant.

Além do CRUD, este módulo mantém um cache process-local (RiskParamsCache) consultado
sincronicamente pelo VerdictEngine – que roda dentro do grafo LangGraph e não possui
uma AsyncSession à mão. O fluxo é:

  PUT /api/v1/params  → upsert no banco + RiskParamsCache.put(tenant, params)
  VerdictEngine       → RiskParamsCache.get(tenant) or defaults hardcoded (0.35/0.45/0.20)

Isolamento por tenant: toda query filtra por tenant_id (UNIQUE).
"""

from __future__ import annotations

from typing import Any

import structlog
from pydantic import BaseModel, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# Defaults hardcoded – fallback quando não há registro de risk_params para o tenant.
DEFAULT_W_ESG = 0.35
DEFAULT_W_FINANCIAL = 0.45
DEFAULT_W_SECURITY = 0.20
DEFAULT_APPROVE_THRESHOLD = 600.0
DEFAULT_MANUAL_THRESHOLD = 450.0
DEFAULT_MAX_DTI = 0.65
DEFAULT_MAX_CREDIT_MULTIPLIER = 12.0

_WEIGHT_SUM_TOLERANCE = 1e-6


class RiskParams(BaseModel):
    """Parâmetros de tolerância a risco de um tenant."""

    tenant_id: str
    w_esg: float = DEFAULT_W_ESG
    w_financial: float = DEFAULT_W_FINANCIAL
    w_security: float = DEFAULT_W_SECURITY
    approve_threshold: float = DEFAULT_APPROVE_THRESHOLD
    manual_threshold: float = DEFAULT_MANUAL_THRESHOLD
    max_dti: float = DEFAULT_MAX_DTI
    max_credit_multiplier: float = DEFAULT_MAX_CREDIT_MULTIPLIER
    updated_by: str = "system"

    @model_validator(mode="after")
    def validate_weights(self) -> RiskParams:
        total = self.w_esg + self.w_financial + self.w_security
        if abs(total - 1.0) > _WEIGHT_SUM_TOLERANCE:
            raise ValueError(f"Pesos devem somar exatamente 1.0 (recebido {total:.4f})")
        return self

    @classmethod
    def defaults(cls, tenant_id: str) -> RiskParams:
        return cls(tenant_id=tenant_id)


# ─── Cache process-local consultado pelo VerdictEngine ───────────────────────


class RiskParamsCache:
    """Cache in-memory {tenant_id: RiskParams}. Único por processo."""

    _store: dict[str, RiskParams] = {}

    @classmethod
    def get(cls, tenant_id: str) -> RiskParams | None:
        return cls._store.get(tenant_id)

    @classmethod
    def put(cls, params: RiskParams) -> None:
        cls._store[params.tenant_id] = params

    @classmethod
    def invalidate(cls, tenant_id: str) -> None:
        cls._store.pop(tenant_id, None)

    @classmethod
    def clear(cls) -> None:
        cls._store.clear()


def resolve_params(tenant_id: str) -> RiskParams:
    """Params do cache ou defaults hardcoded (usado pelo VerdictEngine, síncrono)."""
    return RiskParamsCache.get(tenant_id) or RiskParams.defaults(tenant_id)


# ─── Repositório ─────────────────────────────────────────────────────────────


class RiskParamsRepository:
    """CRUD (get + upsert) da tabela `risk_params`, com isolamento por tenant."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_tenant(self, tenant_id: str) -> RiskParams | None:
        stmt = text(
            "SELECT tenant_id, w_esg, w_financial, w_security, approve_threshold, "
            "       manual_threshold, max_dti, max_credit_multiplier, updated_by "
            "FROM risk_params WHERE tenant_id = :tenant_id"
        )
        result = await self._session.execute(stmt, {"tenant_id": tenant_id})
        row = result.first()
        if row is None:
            return None
        m = row._mapping
        params = RiskParams(
            tenant_id=m["tenant_id"],
            w_esg=float(m["w_esg"]),
            w_financial=float(m["w_financial"]),
            w_security=float(m["w_security"]),
            approve_threshold=float(m["approve_threshold"]),
            manual_threshold=float(m["manual_threshold"]),
            max_dti=float(m["max_dti"]),
            max_credit_multiplier=float(m["max_credit_multiplier"]),
            updated_by=m["updated_by"],
        )
        RiskParamsCache.put(params)
        return params

    async def get_or_defaults(self, tenant_id: str) -> RiskParams:
        return await self.get_by_tenant(tenant_id) or RiskParams.defaults(tenant_id)

    async def upsert(self, params: RiskParams) -> RiskParams:
        """
        Insere ou atualiza os parâmetros do tenant (UPSERT por tenant_id UNIQUE),
        atualizando o cache in-memory consultado pelo VerdictEngine.
        """
        values: dict[str, Any] = {
            "tenant_id": params.tenant_id,
            "w_esg": params.w_esg,
            "w_financial": params.w_financial,
            "w_security": params.w_security,
            "approve_threshold": params.approve_threshold,
            "manual_threshold": params.manual_threshold,
            "max_dti": params.max_dti,
            "max_credit_multiplier": params.max_credit_multiplier,
            "updated_by": params.updated_by,
        }
        stmt = text(
            "INSERT INTO risk_params "
            "(tenant_id, w_esg, w_financial, w_security, approve_threshold, "
            " manual_threshold, max_dti, max_credit_multiplier, updated_by) "
            "VALUES (:tenant_id, :w_esg, :w_financial, :w_security, :approve_threshold, "
            "        :manual_threshold, :max_dti, :max_credit_multiplier, :updated_by) "
            "ON CONFLICT (tenant_id) DO UPDATE SET "
            "  w_esg = EXCLUDED.w_esg, "
            "  w_financial = EXCLUDED.w_financial, "
            "  w_security = EXCLUDED.w_security, "
            "  approve_threshold = EXCLUDED.approve_threshold, "
            "  manual_threshold = EXCLUDED.manual_threshold, "
            "  max_dti = EXCLUDED.max_dti, "
            "  max_credit_multiplier = EXCLUDED.max_credit_multiplier, "
            "  updated_by = EXCLUDED.updated_by, "
            "  updated_at = CURRENT_TIMESTAMP"
        )
        await self._session.execute(stmt, values)
        await self._session.commit()
        RiskParamsCache.put(params)
        logger.info("risk_params_upserted", tenant_id=params.tenant_id, updated_by=params.updated_by)
        return params
