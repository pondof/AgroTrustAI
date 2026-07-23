"""
AgroTrust AI – AuditRepository persistido (PostgreSQL append-only).

Mesma interface pública de core.security.audit.AuditRepository (append, verify_chain,
get_by_resource, export_jsonlines, head_hash), porém com backend PostgreSQL:
  - INSERT em audit_log; UPDATE/DELETE bloqueados por RLS (migração 001).
  - Hash chain SHA-3-256 idêntico ao da versão in-memory (mesmo AuditEntry).

get_audit_repo() (em core.security.audit) devolve esta implementação quando a env
var DB_URL está configurada; caso contrário, a versão in-memory (testes/dev).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.db.engine import get_engine
from core.db.repositories._common import as_dict, json_param
from core.security.audit import AuditEntry, AuditEventType
from core.security.crypto import sha3_256

logger = structlog.get_logger(__name__)

_GENESIS_HASH = sha3_256(b"agrotrust-genesis-block-2026")


class PersistedAuditRepository:
    """Trilha de auditoria imutável sobre PostgreSQL (append-only via RLS)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession] | None = None) -> None:
        # Cada operação abre sua própria sessão (o repo é um singleton de processo).
        self._session_factory = session_factory or async_sessionmaker(
            bind=get_engine(), class_=AsyncSession, expire_on_commit=False
        )
        # Serializa appends do processo para não bifurcar a hash chain sob concorrência.
        self._append_lock = asyncio.Lock()

    @property
    def head_hash(self) -> str:
        """Placeholder síncrono (a versão persistida encadeia via query no append)."""
        return _GENESIS_HASH

    async def _head_hash(self, session: AsyncSession) -> str:
        result = await session.execute(text("SELECT entry_hash FROM audit_log ORDER BY id DESC LIMIT 1"))
        row = result.first()
        return row[0] if row is not None else _GENESIS_HASH

    async def append(
        self,
        event_type: AuditEventType,
        subject: str,
        tenant_id: str,
        resource_id: str,
        outcome: str,
        details: dict[str, Any],
    ) -> AuditEntry:
        async with self._append_lock, self._session_factory() as session:
            previous_hash = await self._head_hash(session)
            entry = AuditEntry(
                event_id=str(uuid.uuid4()),
                timestamp=datetime.now(UTC).isoformat(),
                event_type=event_type,
                subject=subject,
                tenant_id=tenant_id,
                resource_id=resource_id,
                outcome=outcome,
                details=details,
                previous_hash=previous_hash,
            )
            entry.entry_hash = entry.compute_hash()

            stmt = text(
                "INSERT INTO audit_log "
                "(event_id, timestamp, event_type, subject, tenant_id, resource_id, "
                " outcome, details, previous_hash, entry_hash) "
                "VALUES (:event_id, :timestamp, :event_type, :subject, :tenant_id, :resource_id, "
                "        :outcome, :details, :previous_hash, :entry_hash)"
            ).bindparams(json_param("details"))
            await session.execute(
                stmt,
                {
                    "event_id": entry.event_id,
                    "timestamp": entry.timestamp,
                    "event_type": entry.event_type.value,
                    "subject": entry.subject,
                    "tenant_id": entry.tenant_id,
                    "resource_id": entry.resource_id,
                    "outcome": entry.outcome,
                    "details": entry.details,
                    "previous_hash": entry.previous_hash,
                    "entry_hash": entry.entry_hash,
                },
            )
            await session.commit()

        logger.info(
            "audit_entry",
            event_id=entry.event_id,
            event_type=entry.event_type.value,
            subject=entry.subject,
            tenant_id=entry.tenant_id,
            resource_id=entry.resource_id,
            outcome=entry.outcome,
            entry_hash=entry.entry_hash[:16] + "…",
        )
        return entry

    async def verify_chain(self) -> tuple[bool, str]:
        """Relê toda a cadeia (ORDER BY id ASC), recalcula hashes e compara."""
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT event_id, timestamp, event_type, subject, tenant_id, resource_id, "
                    "       outcome, details, previous_hash, entry_hash "
                    "FROM audit_log ORDER BY id ASC"
                )
            )
            rows = result.fetchall()

        prev_hash = _GENESIS_HASH
        for i, row in enumerate(rows):
            entry = self._row_to_entry(row)
            if entry.previous_hash != prev_hash:
                return False, f"Cadeia quebrada na entrada #{i} (event_id={entry.event_id})"
            if entry.compute_hash() != entry.entry_hash:
                return False, f"Hash inválido na entrada #{i}: adulteração detectada"
            prev_hash = entry.entry_hash
        return True, ""

    async def get_by_resource(self, resource_id: str, tenant_id: str | None = None) -> list[AuditEntry]:
        """Entradas de um recurso, opcionalmente filtradas por tenant (isolamento)."""
        where = "WHERE resource_id = :resource_id"
        params: dict[str, Any] = {"resource_id": resource_id}
        if tenant_id is not None:
            where += " AND tenant_id = :tenant_id"
            params["tenant_id"] = tenant_id
        async with self._session_factory() as session:
            # _where só concatena identificadores internos + placeholders; valores via params.
            query = (
                "SELECT event_id, timestamp, event_type, subject, tenant_id, resource_id, "  # noqa: S608
                f"       outcome, details, previous_hash, entry_hash FROM audit_log {where} "
                "ORDER BY id ASC"
            )
            result = await session.execute(text(query), params)
            rows = result.fetchall()
        return [self._row_to_entry(row) for row in rows]

    async def export_jsonlines(self) -> str:
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT event_id, timestamp, event_type, subject, tenant_id, resource_id, "
                    "       outcome, details, previous_hash, entry_hash FROM audit_log ORDER BY id ASC"
                )
            )
            rows = result.fetchall()
        return "\n".join(json.dumps(self._row_to_entry(row).to_dict()) for row in rows)

    @staticmethod
    def _row_to_entry(row: Any) -> AuditEntry:
        m = row._mapping
        entry = AuditEntry(
            event_id=str(m["event_id"]),
            timestamp=_iso(m["timestamp"]),
            event_type=AuditEventType(m["event_type"]),
            subject=m["subject"],
            tenant_id=m["tenant_id"],
            resource_id=m["resource_id"],
            outcome=m["outcome"],
            details=as_dict(m["details"]),
            previous_hash=m["previous_hash"],
        )
        entry.entry_hash = m["entry_hash"]
        return entry


def _iso(value: Any) -> str:
    """Normaliza timestamp lido do banco para a mesma string ISO usada no hash."""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
