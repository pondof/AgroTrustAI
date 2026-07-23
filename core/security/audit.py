"""
AgroTrust AI – Log de Auditoria Imutável (Append-Only Hash Chain).

Arquitetura:
  - Cada entrada de auditoria encadeia o hash SHA-3-256 da entrada anterior.
  - Qualquer adulteração retroativa quebra a cadeia (verificável).
  - Storage: PostgreSQL append-only (DELETE/UPDATE revogados via RLS) + S3 Glacier.
  - Formato de linha compatível com exportação para SIEM (estruturado JSON).
  - Cumpre LGPD Art. 37 (registro de operações de tratamento) e exigências Bacen.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import structlog

from core.security.crypto import sha3_256

logger = structlog.get_logger(__name__)


# ─── Categorias de evento ─────────────────────────────────────────────────────


class AuditEventType(str, Enum):
    # Subscrição
    SUBSCRIPTION_INITIATED = "subscription.initiated"
    SUBSCRIPTION_ESG_RESULT = "subscription.esg_result"
    SUBSCRIPTION_FIN_RESULT = "subscription.financial_result"
    SUBSCRIPTION_APPROVED = "subscription.approved"
    SUBSCRIPTION_REJECTED = "subscription.rejected"

    # Segurança / Identidade
    BIOMETRIC_PASSED = "security.biometric_passed"
    BIOMETRIC_FAILED = "security.biometric_failed"
    DEEPFAKE_DETECTED = "security.deepfake_detected"
    TITLE_VERIFIED = "security.title_verified"
    TITLE_FRAUD_DETECTED = "security.title_fraud_detected"

    # Acesso
    AUTH_SUCCESS = "auth.success"
    AUTH_FAILURE = "auth.failure"
    PERMISSION_DENIED = "auth.permission_denied"

    # Dado sensível
    PII_ACCESSED = "data.pii_accessed"
    PII_EXPORTED = "data.pii_exported"

    # Sistema
    SYSTEM_CONFIG_CHANGED = "system.config_changed"
    AGENT_INVOKED = "system.agent_invoked"
    MOCK_USED = "system.mock_used"


# ─── Estrutura de entrada de auditoria ───────────────────────────────────────


@dataclass(slots=True)
class AuditEntry:
    event_id: str  # UUID v4
    timestamp: str  # ISO-8601 UTC
    event_type: AuditEventType
    subject: str  # quem executou (user_id ou service_id)
    tenant_id: str  # cooperativa / FIAGRO
    resource_id: str  # dossiê ID, propriedade ID etc.
    outcome: str  # "success" | "failure" | "warning"
    details: dict[str, Any]  # payload específico do evento (sem PII exposta em claro)
    previous_hash: str  # hash da entrada anterior (encadeamento)
    entry_hash: str = field(default="")  # preenchido após construção

    def compute_hash(self) -> str:
        """Hash SHA-3-256 desta entrada (sobre todos os campos exceto entry_hash)."""
        canonical = json.dumps(
            {
                "event_id": self.event_id,
                "timestamp": self.timestamp,
                "event_type": self.event_type,
                "subject": self.subject,
                "tenant_id": self.tenant_id,
                "resource_id": self.resource_id,
                "outcome": self.outcome,
                "details": self.details,
                "previous_hash": self.previous_hash,
            },
            sort_keys=True,
            ensure_ascii=True,
        )
        return sha3_256(canonical.encode())

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["event_type"] = self.event_type.value
        return d


# ─── Repositório de auditoria ─────────────────────────────────────────────────


class AuditRepository:
    """
    Interface do repositório. Em produção implementada com PostgreSQL (asyncpg)
    com política RLS que bloqueia UPDATE/DELETE para todos os roles de aplicação.
    Esta versão é uma implementação em memória para testes e dev.
    """

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []
        self._genesis_hash = sha3_256(b"agrotrust-genesis-block-2026")

    @property
    def head_hash(self) -> str:
        if not self._entries:
            return self._genesis_hash
        return self._entries[-1].entry_hash

    async def append(
        self,
        event_type: AuditEventType,
        subject: str,
        tenant_id: str,
        resource_id: str,
        outcome: str,
        details: dict[str, Any],
    ) -> AuditEntry:
        entry = AuditEntry(
            event_id=str(uuid.uuid4()),
            timestamp=datetime.now(UTC).isoformat(),
            event_type=event_type,
            subject=subject,
            tenant_id=tenant_id,
            resource_id=resource_id,
            outcome=outcome,
            details=details,
            previous_hash=self.head_hash,
        )
        entry.entry_hash = entry.compute_hash()
        self._entries.append(entry)

        logger.info(
            "audit_entry",
            event_id=entry.event_id,
            event_type=entry.event_type,
            subject=entry.subject,
            tenant_id=entry.tenant_id,
            resource_id=entry.resource_id,
            outcome=entry.outcome,
            entry_hash=entry.entry_hash[:16] + "…",
        )
        return entry

    async def verify_chain(self) -> tuple[bool, str]:
        """
        Verifica a integridade da cadeia completa.
        Retorna (True, "") se válida ou (False, "mensagem de erro") se adulterada.
        """
        prev_hash = self._genesis_hash
        for i, entry in enumerate(self._entries):
            if entry.previous_hash != prev_hash:
                return False, f"Cadeia quebrada na entrada #{i} (event_id={entry.event_id})"
            expected = entry.compute_hash()
            if entry.entry_hash != expected:
                return False, f"Hash inválido na entrada #{i}: adulteração detectada"
            prev_hash = entry.entry_hash
        return True, ""

    async def get_by_resource(self, resource_id: str) -> list[AuditEntry]:
        return [e for e in self._entries if e.resource_id == resource_id]

    async def export_jsonlines(self) -> str:
        """Exporta todas as entradas como JSONL para SIEM / S3 Glacier."""
        return "\n".join(json.dumps(e.to_dict()) for e in self._entries)


# ─── Singleton global ─────────────────────────────────────────────────────────

_audit_repo: Any | None = None


def get_audit_repo() -> Any:
    """
    Devolve o repositório de auditoria como singleton de processo.

    Quando a env var DB_URL está configurada (produção/staging), usa a implementação
    persistida em PostgreSQL (append-only via RLS). Caso contrário (testes/dev sem
    banco), usa a implementação in-memory desta módulo. Ambas expõem a mesma
    interface pública (append/verify_chain/get_by_resource/export_jsonlines).
    """
    global _audit_repo
    if _audit_repo is None:
        if os.environ.get("DB_URL"):
            # Import tardio: evita ciclo core.security.audit ↔ core.db.repositories.audit.
            from core.db.repositories.audit import PersistedAuditRepository

            _audit_repo = PersistedAuditRepository()
            logger.info("audit_repo_backend_selected", backend="postgres")
        else:
            _audit_repo = AuditRepository()
            logger.info("audit_repo_backend_selected", backend="in-memory")
    return _audit_repo


def reset_audit_repo() -> None:
    """Limpa o singleton (usado em testes que alternam backends)."""
    global _audit_repo
    _audit_repo = None


# ─── Decorator de auditoria automática ───────────────────────────────────────


def audited(
    event_type: AuditEventType,
    resource_id_kwarg: str = "dossie_id",
):
    """
    Decorator assíncrono que registra automaticamente chamadas de função na trilha de auditoria.
    Uso:
        @audited(AuditEventType.SUBSCRIPTION_INITIATED)
        async def iniciar_subscricao(dossie_id: str, identity: ServiceIdentity): ...
    """
    import functools

    def decorator(fn):  # type: ignore[no-untyped-def]
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            resource_id = kwargs.get(resource_id_kwarg, "unknown")
            identity = kwargs.get("identity")
            subject = identity.subject if identity else "system"
            tenant_id = identity.tenant_id if identity else "system"
            repo = get_audit_repo()
            try:
                result = await fn(*args, **kwargs)
                await repo.append(
                    event_type=event_type,
                    subject=subject,
                    tenant_id=tenant_id,
                    resource_id=str(resource_id),
                    outcome="success",
                    details={"function": fn.__name__},
                )
                return result
            except Exception as exc:
                await repo.append(
                    event_type=event_type,
                    subject=subject,
                    tenant_id=tenant_id,
                    resource_id=str(resource_id),
                    outcome="failure",
                    details={"function": fn.__name__, "error": type(exc).__name__},
                )
                raise

        return wrapper

    return decorator
