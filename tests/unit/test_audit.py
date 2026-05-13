"""Testes unitários – core/security/audit.py (hash chain imutável)"""

from __future__ import annotations

import pytest

from core.security.audit import AuditEventType, AuditRepository


@pytest.fixture
def repo() -> AuditRepository:
    return AuditRepository()


@pytest.mark.asyncio
async def test_append_single_entry(repo: AuditRepository) -> None:
    entry = await repo.append(
        event_type=AuditEventType.SUBSCRIPTION_INITIATED,
        subject="user-analyst-001",
        tenant_id="sicredi-pilot",
        resource_id="dossie-abc-123",
        outcome="success",
        details={"credit_amount": 450000},
    )
    assert entry.event_id
    assert entry.previous_hash == repo._genesis_hash
    assert entry.entry_hash == entry.compute_hash()


@pytest.mark.asyncio
async def test_chain_integrity_multiple_entries(repo: AuditRepository) -> None:
    for i in range(5):
        await repo.append(
            event_type=AuditEventType.AGENT_INVOKED,
            subject=f"orchestrator-{i}",
            tenant_id="sicredi-pilot",
            resource_id=f"dossie-{i}",
            outcome="success",
            details={"step": i},
        )
    is_valid, msg = await repo.verify_chain()
    assert is_valid, f"Cadeia inválida: {msg}"


@pytest.mark.asyncio
async def test_chain_broken_by_tampering(repo: AuditRepository) -> None:
    await repo.append(
        event_type=AuditEventType.SUBSCRIPTION_APPROVED,
        subject="orchestrator",
        tenant_id="fiagro-xyz",
        resource_id="dossie-tamper-test",
        outcome="success",
        details={},
    )
    # Adultera o hash da entrada (simula ataque)
    repo._entries[0].entry_hash = "0" * 64  # type: ignore[attr-defined]

    # Adiciona segunda entrada com hash errado da anterior
    await repo.append(
        event_type=AuditEventType.SUBSCRIPTION_REJECTED,
        subject="orchestrator",
        tenant_id="fiagro-xyz",
        resource_id="dossie-tamper-test",
        outcome="failure",
        details={"reason": "esg_failed"},
    )
    is_valid, msg = await repo.verify_chain()
    assert not is_valid, "Deveria detectar adulteração"


@pytest.mark.asyncio
async def test_get_by_resource(repo: AuditRepository) -> None:
    for event_type in [
        AuditEventType.SUBSCRIPTION_INITIATED,
        AuditEventType.SUBSCRIPTION_ESG_RESULT,
        AuditEventType.SUBSCRIPTION_APPROVED,
    ]:
        await repo.append(
            event_type=event_type,
            subject="orchestrator",
            tenant_id="tenant-x",
            resource_id="dossie-rastreavel",
            outcome="success",
            details={},
        )
    entries = await repo.get_by_resource("dossie-rastreavel")
    assert len(entries) == 3


@pytest.mark.asyncio
async def test_export_jsonlines(repo: AuditRepository) -> None:
    await repo.append(
        event_type=AuditEventType.AUTH_SUCCESS,
        subject="gestor-fiagro",
        tenant_id="fiagro-001",
        resource_id="session-xyz",
        outcome="success",
        details={"ip": "10.0.0.1"},
    )
    jsonl = await repo.export_jsonlines()
    assert '"event_type"' in jsonl
    assert "auth.success" in jsonl


@pytest.mark.asyncio
async def test_empty_chain_is_valid(repo: AuditRepository) -> None:
    is_valid, msg = await repo.verify_chain()
    assert is_valid
    assert msg == ""
