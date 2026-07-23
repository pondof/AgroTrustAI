"""
Testes unitários – PersistedAuditRepository (backend SQLite async in-memory).

Cobre: append encadeado, verify_chain íntegro, detecção de adulteração,
get_by_resource com isolamento por tenant, export_jsonlines.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.db.repositories.audit import PersistedAuditRepository
from core.security.audit import AuditEventType


async def _seed(repo: PersistedAuditRepository) -> None:
    await repo.append(
        event_type=AuditEventType.SUBSCRIPTION_INITIATED,
        subject="analista-1",
        tenant_id="tenant-alpha",
        resource_id="DOS-1",
        outcome="success",
        details={"car_number": "MT-1"},
    )
    await repo.append(
        event_type=AuditEventType.SUBSCRIPTION_APPROVED,
        subject="agent-runner",
        tenant_id="tenant-alpha",
        resource_id="DOS-1",
        outcome="success",
        details={"verdict": "approved"},
    )
    await repo.append(
        event_type=AuditEventType.SUBSCRIPTION_REJECTED,
        subject="agent-runner",
        tenant_id="tenant-beta",
        resource_id="DOS-2",
        outcome="success",
        details={"verdict": "rejected"},
    )


@pytest.mark.asyncio
async def test_append_chains_and_verifies(
    sqlite_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    repo = PersistedAuditRepository(session_factory=sqlite_sessionmaker)
    await _seed(repo)

    ok, msg = await repo.verify_chain()
    assert ok, msg
    assert msg == ""


@pytest.mark.asyncio
async def test_tamper_breaks_chain(
    sqlite_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    repo = PersistedAuditRepository(session_factory=sqlite_sessionmaker)
    await _seed(repo)

    # Simula adulteração retroativa (no PostgreSQL a RLS bloquearia este UPDATE).
    async with sqlite_sessionmaker() as session:
        await session.execute(
            text("UPDATE audit_log SET details = :d WHERE id = 1"),
            {"d": json.dumps({"car_number": "TAMPERED"})},
        )
        await session.commit()

    ok, msg = await repo.verify_chain()
    assert ok is False
    assert "adultera" in msg.lower() or "quebrada" in msg.lower()


@pytest.mark.asyncio
async def test_get_by_resource_tenant_isolation(
    sqlite_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    repo = PersistedAuditRepository(session_factory=sqlite_sessionmaker)
    await _seed(repo)

    entries = await repo.get_by_resource("DOS-1")
    assert len(entries) == 2
    assert {e.event_type for e in entries} == {
        AuditEventType.SUBSCRIPTION_INITIATED,
        AuditEventType.SUBSCRIPTION_APPROVED,
    }

    # Filtro por tenant: DOS-1 pertence a tenant-alpha, não a tenant-beta.
    leaked = await repo.get_by_resource("DOS-1", tenant_id="tenant-beta")
    assert leaked == []

    owned = await repo.get_by_resource("DOS-1", tenant_id="tenant-alpha")
    assert len(owned) == 2


@pytest.mark.asyncio
async def test_export_jsonlines(
    sqlite_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    repo = PersistedAuditRepository(session_factory=sqlite_sessionmaker)
    await _seed(repo)

    exported = await repo.export_jsonlines()
    lines = exported.splitlines()
    assert len(lines) == 3
    first = json.loads(lines[0])
    assert first["resource_id"] == "DOS-1"
    assert first["event_type"] == "subscription.initiated"
    # Nunca expõe CPF em claro – apenas o que foi gravado em details.
    assert "cpf" not in exported.lower() or "cpf_hash" in exported.lower()
