"""
AgroTrust AI – DossieRepository: projeção de leitura dos dossiês.

O Kafka é a fonte de verdade; esta tabela é uma projeção materializada para
consultas rápidas (status/history, estatísticas por tenant).

  - SQLAlchemy Core (text() + bindparam()), sem ORM declarativo.
  - Todo acesso filtra por tenant_id no WHERE (row-level isolation).
  - Nunca expõe CPF em claro (apenas producer_cpf_hash SHA-3-256).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, cast

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import CursorResult, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.repositories._common import array_param, as_dict, as_list, json_param
from core.events.schemas import SubscriptionVerdictEvent

logger = structlog.get_logger(__name__)


# ─── DTOs (espelham a tabela / endpoints) ────────────────────────────────────


class DossieCreateDTO(BaseModel):
    """Dados mínimos para materializar um dossiê recém-iniciado."""

    dossie_id: str
    correlation_id: str
    tenant_id: str
    producer_cpf_hash: str = Field(min_length=64, max_length=64)
    car_number: str
    property_area_ha: float
    credit_amount_brl: float
    credit_purpose: str
    requested_by: str
    status: str = "initiated"


class DossieRecord(BaseModel):
    """Espelho de uma linha da tabela `dossies`."""

    id: str
    dossie_id: str
    correlation_id: str
    tenant_id: str
    producer_cpf_hash: str
    car_number: str
    property_area_ha: float
    credit_amount_brl: float
    credit_purpose: str
    requested_by: str
    status: str
    verdict: str | None = None
    composite_score: float | None = None
    esg_score: float | None = None
    financial_score: float | None = None
    security_score: float | None = None
    approved_amount_brl: float | None = None
    rejection_reasons: list[str] = Field(default_factory=list)
    xai_consolidated_rationale: dict[str, Any] = Field(default_factory=dict)
    processing_time_ms: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DossieStatsDTO(BaseModel):
    """Estatísticas agregadas por tenant (endpoint /api/v1/stats)."""

    tenant_id: str
    total: int
    approved: int
    rejected: int
    manual_review: int
    avg_processing_ms: float | None = None
    avg_composite_score: float | None = None


# ─── Repositório ─────────────────────────────────────────────────────────────

_COLUMNS = (
    "id, dossie_id, correlation_id, tenant_id, producer_cpf_hash, car_number, "
    "property_area_ha, credit_amount_brl, credit_purpose, requested_by, status, "
    "verdict, composite_score, esg_score, financial_score, security_score, "
    "approved_amount_brl, rejection_reasons, xai_consolidated_rationale, "
    "processing_time_ms, created_at, updated_at"
)


def _row_to_record(row: Any) -> DossieRecord:
    m = row._mapping
    return DossieRecord(
        id=str(m["id"]),
        dossie_id=m["dossie_id"],
        correlation_id=str(m["correlation_id"]),
        tenant_id=m["tenant_id"],
        producer_cpf_hash=m["producer_cpf_hash"],
        car_number=m["car_number"],
        property_area_ha=float(m["property_area_ha"]),
        credit_amount_brl=float(m["credit_amount_brl"]),
        credit_purpose=m["credit_purpose"],
        requested_by=m["requested_by"],
        status=m["status"],
        verdict=m["verdict"],
        composite_score=_opt_float(m["composite_score"]),
        esg_score=_opt_float(m["esg_score"]),
        financial_score=_opt_float(m["financial_score"]),
        security_score=_opt_float(m["security_score"]),
        approved_amount_brl=_opt_float(m["approved_amount_brl"]),
        rejection_reasons=as_list(m["rejection_reasons"]),
        xai_consolidated_rationale=as_dict(m["xai_consolidated_rationale"]),
        processing_time_ms=_opt_int(m["processing_time_ms"]),
        created_at=_opt_dt(m["created_at"]),
        updated_at=_opt_dt(m["updated_at"]),
    )


def _opt_float(v: Any) -> float | None:
    return float(v) if v is not None else None


def _opt_int(v: Any) -> int | None:
    return int(v) if v is not None else None


def _opt_dt(v: Any) -> datetime | None:
    if v is None or isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v))
    except ValueError:
        return None


class DossieRepository:
    """CRUD + projeções da tabela `dossies`. Recebe uma AsyncSession por uso."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, dossie: DossieCreateDTO) -> DossieRecord:
        """Materializa um novo dossiê. Idempotente por dossie_id (UNIQUE)."""
        stmt = text(
            "INSERT INTO dossies "
            "(id, dossie_id, correlation_id, tenant_id, producer_cpf_hash, car_number, "
            " property_area_ha, credit_amount_brl, credit_purpose, requested_by, status) "
            "VALUES "
            "(:id, :dossie_id, :correlation_id, :tenant_id, :producer_cpf_hash, :car_number, "
            " :property_area_ha, :credit_amount_brl, :credit_purpose, :requested_by, :status)"
        )
        await self._session.execute(
            stmt,
            {
                "id": str(uuid.uuid4()),
                "dossie_id": dossie.dossie_id,
                "correlation_id": dossie.correlation_id,
                "tenant_id": dossie.tenant_id,
                "producer_cpf_hash": dossie.producer_cpf_hash,
                "car_number": dossie.car_number,
                "property_area_ha": dossie.property_area_ha,
                "credit_amount_brl": dossie.credit_amount_brl,
                "credit_purpose": dossie.credit_purpose,
                "requested_by": dossie.requested_by,
                "status": dossie.status,
            },
        )
        await self._session.commit()
        logger.info("dossie_created", dossie_id=dossie.dossie_id, tenant_id=dossie.tenant_id)
        record = await self.get_by_id(dossie.dossie_id, dossie.tenant_id)
        assert record is not None  # acabou de ser inserido
        return record

    async def update_status(
        self,
        dossie_id: str,
        status: str,
        **kwargs: Any,
    ) -> DossieRecord | None:
        """Atualiza o status (e colunas simples opcionais via kwargs) do dossiê."""
        allowed = {
            "verdict",
            "composite_score",
            "esg_score",
            "financial_score",
            "security_score",
            "approved_amount_brl",
            "processing_time_ms",
        }
        sets = ["status = :status", "updated_at = CURRENT_TIMESTAMP"]
        params: dict[str, Any] = {"status": status, "dossie_id": dossie_id}
        for key, value in kwargs.items():
            if key not in allowed:
                raise ValueError(f"Coluna não atualizável via update_status: {key}")
            sets.append(f"{key} = :{key}")
            params[key] = value

        stmt = text(f"UPDATE dossies SET {', '.join(sets)} WHERE dossie_id = :dossie_id")  # noqa: S608
        result = cast("CursorResult[Any]", await self._session.execute(stmt, params))
        await self._session.commit()
        if result.rowcount == 0:
            return None
        return await self._get_any_tenant(dossie_id)

    async def update_verdict(
        self,
        dossie_id: str,
        verdict: SubscriptionVerdictEvent,
    ) -> DossieRecord | None:
        """
        Persiste o veredicto do orquestrador na projeção. O status passa a refletir
        o veredicto (approved|rejected|manual_review). Retorna None se o dossiê não
        existir (projeção é best-effort; o Kafka permanece a fonte de verdade).
        """
        stmt = text(
            "UPDATE dossies SET "
            "  status = :status, "
            "  verdict = :verdict, "
            "  composite_score = :composite_score, "
            "  esg_score = :esg_score, "
            "  financial_score = :financial_score, "
            "  security_score = :security_score, "
            "  approved_amount_brl = :approved_amount_brl, "
            "  rejection_reasons = :rejection_reasons, "
            "  xai_consolidated_rationale = :xai_consolidated_rationale, "
            "  processing_time_ms = :processing_time_ms, "
            "  updated_at = CURRENT_TIMESTAMP "
            "WHERE dossie_id = :dossie_id"
        ).bindparams(
            array_param("rejection_reasons", self._session),
            json_param("xai_consolidated_rationale"),
        )
        result = cast(
            "CursorResult[Any]",
            await self._session.execute(
                stmt,
                {
                    "status": verdict.verdict,
                    "verdict": verdict.verdict,
                    "composite_score": verdict.composite_score,
                    "esg_score": verdict.esg_score,
                    "financial_score": verdict.financial_score,
                    "security_score": verdict.security_score,
                    "approved_amount_brl": verdict.approved_amount_brl,
                    "rejection_reasons": list(verdict.rejection_reasons),
                    "xai_consolidated_rationale": verdict.xai_consolidated_rationale,
                    "processing_time_ms": verdict.processing_time_ms,
                    "dossie_id": dossie_id,
                },
            ),
        )
        await self._session.commit()
        if result.rowcount == 0:
            logger.warning("dossie_update_verdict_miss", dossie_id=dossie_id)
            return None
        logger.info("dossie_verdict_persisted", dossie_id=dossie_id, verdict=verdict.verdict)
        return await self._get_any_tenant(dossie_id)

    async def get_by_id(self, dossie_id: str, tenant_id: str) -> DossieRecord | None:
        """Busca um dossiê garantindo isolamento por tenant (WHERE tenant_id)."""
        stmt = text(
            f"SELECT {_COLUMNS} FROM dossies "  # noqa: S608 – _COLUMNS é constante interna
            "WHERE dossie_id = :dossie_id AND tenant_id = :tenant_id"
        )
        result = await self._session.execute(stmt, {"dossie_id": dossie_id, "tenant_id": tenant_id})
        row = result.first()
        return _row_to_record(row) if row is not None else None

    async def list_by_tenant(
        self,
        tenant_id: str,
        limit: int = 20,
        offset: int = 0,
        status_filter: str | None = None,
    ) -> list[DossieRecord]:
        """Lista dossiês do tenant, mais recentes primeiro, com paginação."""
        where = "WHERE tenant_id = :tenant_id"
        params: dict[str, Any] = {"tenant_id": tenant_id, "limit": limit, "offset": offset}
        if status_filter is not None:
            where += " AND status = :status_filter"
            params["status_filter"] = status_filter

        stmt = text(
            f"SELECT {_COLUMNS} FROM dossies {where} "  # noqa: S608
            "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        )
        result = await self._session.execute(stmt, params)
        return [_row_to_record(row) for row in result.fetchall()]

    async def get_stats(self, tenant_id: str) -> DossieStatsDTO:
        """Agrega contadores e médias para o dashboard do tenant."""
        stmt = text(
            "SELECT "
            "  COUNT(*) AS total, "
            "  SUM(CASE WHEN verdict = 'approved' THEN 1 ELSE 0 END) AS approved, "
            "  SUM(CASE WHEN verdict = 'rejected' THEN 1 ELSE 0 END) AS rejected, "
            "  SUM(CASE WHEN verdict = 'manual_review' THEN 1 ELSE 0 END) AS manual_review, "
            "  AVG(processing_time_ms) AS avg_processing_ms, "
            "  AVG(composite_score) AS avg_composite_score "
            "FROM dossies WHERE tenant_id = :tenant_id"
        )
        # SUM(CASE ...) em vez de COUNT(*) FILTER: portável entre PostgreSQL e SQLite.
        result = await self._session.execute(stmt, {"tenant_id": tenant_id})
        row = result.first()
        assert row is not None  # agregação COUNT/AVG sempre retorna exatamente uma linha
        m = row._mapping
        return DossieStatsDTO(
            tenant_id=tenant_id,
            total=int(m["total"] or 0),
            approved=int(m["approved"] or 0),
            rejected=int(m["rejected"] or 0),
            manual_review=int(m["manual_review"] or 0),
            avg_processing_ms=_opt_float(m["avg_processing_ms"]),
            avg_composite_score=_opt_float(m["avg_composite_score"]),
        )

    async def _get_any_tenant(self, dossie_id: str) -> DossieRecord | None:
        """Uso interno pós-UPDATE: relê a linha sem exigir tenant (já validada)."""
        stmt = text(f"SELECT {_COLUMNS} FROM dossies WHERE dossie_id = :dossie_id")  # noqa: S608
        result = await self._session.execute(stmt, {"dossie_id": dossie_id})
        row = result.first()
        return _row_to_record(row) if row is not None else None
