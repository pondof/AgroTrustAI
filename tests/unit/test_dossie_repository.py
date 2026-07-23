"""
Testes unitários – DossieRepository (backend SQLite async in-memory).

Cobre: create, update_verdict, get_by_id (isolamento por tenant), list_by_tenant,
get_stats. O mesmo código de repositório roda em PostgreSQL em produção.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.repositories.dossie import DossieCreateDTO, DossieRepository
from core.events.schemas import SubscriptionVerdictEvent

_CPF_HASH = "a3f5b8c2d1e4f7a0b3c6d9e2f5a8b1c4d7e0f3a6b9c2d5e8f1a4b7c0d3e6f9ab"
_TENANT = "tenant-alpha"


def _dto(dossie_id: str, tenant_id: str = _TENANT) -> DossieCreateDTO:
    return DossieCreateDTO(
        dossie_id=dossie_id,
        correlation_id="11111111-1111-1111-1111-111111111111",
        tenant_id=tenant_id,
        producer_cpf_hash=_CPF_HASH,
        car_number="MT-5107602-ABC",
        property_area_ha=300.0,
        credit_amount_brl=120_000.0,
        credit_purpose="custeio",
        requested_by="analista-1",
    )


def _verdict(dossie_id: str, tenant_id: str = _TENANT) -> SubscriptionVerdictEvent:
    return SubscriptionVerdictEvent(
        correlation_id="11111111-1111-1111-1111-111111111111",
        tenant_id=tenant_id,
        dossie_id=dossie_id,
        verdict="rejected",
        approved_amount_brl=None,
        rejection_reasons=["DTI acima do limite: 80%", "Trust Score+ insuficiente"],
        esg_score=1000.0,
        financial_score=200.0,
        security_score=950.0,
        composite_score=630.0,
        xai_consolidated_rationale={
            "scores": {"esg": 1000.0, "financial": 200.0, "security": 950.0, "composite": 630.0},
            "esg_rationale": {"car": "regular"},
            "financial_rationale": {"dti": 0.8},
            "security_rationale": {"fraud": "low"},
        },
        processing_time_ms=1234,
    )


@pytest.mark.asyncio
async def test_create_and_get_by_id(db_session: AsyncSession) -> None:
    repo = DossieRepository(db_session)
    record = await repo.create(_dto("DOS-000000000001"))

    assert record.dossie_id == "DOS-000000000001"
    assert record.status == "initiated"
    assert record.tenant_id == _TENANT
    assert record.producer_cpf_hash == _CPF_HASH
    assert record.rejection_reasons == []
    assert record.xai_consolidated_rationale == {}

    fetched = await repo.get_by_id("DOS-000000000001", _TENANT)
    assert fetched is not None
    assert fetched.id == record.id


@pytest.mark.asyncio
async def test_get_by_id_enforces_tenant_isolation(db_session: AsyncSession) -> None:
    repo = DossieRepository(db_session)
    await repo.create(_dto("DOS-000000000002", tenant_id="tenant-alpha"))

    # Outro tenant não pode ler o dossiê (row-level isolation).
    leaked = await repo.get_by_id("DOS-000000000002", "tenant-beta")
    assert leaked is None

    owner = await repo.get_by_id("DOS-000000000002", "tenant-alpha")
    assert owner is not None


@pytest.mark.asyncio
async def test_update_verdict_persists_scores_and_reasons(db_session: AsyncSession) -> None:
    repo = DossieRepository(db_session)
    await repo.create(_dto("DOS-000000000003"))

    updated = await repo.update_verdict("DOS-000000000003", _verdict("DOS-000000000003"))
    assert updated is not None
    assert updated.verdict == "rejected"
    assert updated.status == "rejected"
    assert updated.composite_score == pytest.approx(630.0)
    assert updated.esg_score == pytest.approx(1000.0)
    assert updated.rejection_reasons == ["DTI acima do limite: 80%", "Trust Score+ insuficiente"]
    assert updated.xai_consolidated_rationale["scores"]["composite"] == 630.0
    assert updated.processing_time_ms == 1234


@pytest.mark.asyncio
async def test_update_verdict_missing_dossie_returns_none(db_session: AsyncSession) -> None:
    repo = DossieRepository(db_session)
    result = await repo.update_verdict("DOS-DOESNOTEXIST", _verdict("DOS-DOESNOTEXIST"))
    assert result is None


@pytest.mark.asyncio
async def test_list_by_tenant_pagination_and_filter(db_session: AsyncSession) -> None:
    repo = DossieRepository(db_session)
    for i in range(5):
        await repo.create(_dto(f"DOS-00000000010{i}"))
    # Um dossiê de outro tenant não deve aparecer.
    await repo.create(_dto("DOS-000000000199", tenant_id="tenant-beta"))

    all_alpha = await repo.list_by_tenant(_TENANT, limit=10)
    assert len(all_alpha) == 5
    assert all(r.tenant_id == _TENANT for r in all_alpha)

    page = await repo.list_by_tenant(_TENANT, limit=2, offset=0)
    assert len(page) == 2

    # Filtro por status
    await repo.update_verdict("DOS-000000000100", _verdict("DOS-000000000100"))
    rejected = await repo.list_by_tenant(_TENANT, status_filter="rejected")
    assert len(rejected) == 1
    assert rejected[0].dossie_id == "DOS-000000000100"


@pytest.mark.asyncio
async def test_get_stats_aggregates(db_session: AsyncSession) -> None:
    repo = DossieRepository(db_session)
    for i in range(3):
        await repo.create(_dto(f"DOS-00000000020{i}"))
    await repo.update_verdict("DOS-000000000200", _verdict("DOS-000000000200"))

    stats = await repo.get_stats(_TENANT)
    assert stats.tenant_id == _TENANT
    assert stats.total == 3
    assert stats.rejected == 1
    assert stats.approved == 0
    assert stats.manual_review == 0
    assert stats.avg_processing_ms == pytest.approx(1234.0)
    assert stats.avg_composite_score == pytest.approx(630.0)

    # Tenant sem dossiês → zeros e médias nulas.
    empty = await repo.get_stats("tenant-empty")
    assert empty.total == 0
    assert empty.avg_processing_ms is None
