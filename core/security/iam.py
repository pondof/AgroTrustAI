"""
AgroTrust AI – Identity & Access Management (Zero Trust).

Princípios:
  - Nenhum serviço confia em outro sem token JWT verificado (mTLS em prod).
  - Todo request carrega identidade: service_id + scopes + tenant_id.
  - Autorização baseada em scopes granulares (não papéis genéricos).
  - Tokens de serviço (S2S) têm TTL curto e são rotacionados automaticamente.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from core.config.settings import get_settings

# ─── Scopes ──────────────────────────────────────────────────────────────────


class Scope(str, Enum):
    """Escopos de autorização granulares por operação crítica."""

    # Subscrição
    SUBSCRIPTION_READ = "subscription:read"
    SUBSCRIPTION_WRITE = "subscription:write"
    SUBSCRIPTION_APPROVE = "subscription:approve"  # apenas gestores FIAGRO
    SUBSCRIPTION_REJECT = "subscription:reject"

    # Agentes
    AGENT_ESG_RUN = "agent:esg:run"
    AGENT_FINANCIAL_RUN = "agent:financial:run"
    AGENT_SECURITY_RUN = "agent:security:run"
    AGENT_ORCHESTRATE = "agent:orchestrate"

    # Auditoria
    AUDIT_READ = "audit:read"
    AUDIT_EXPORT = "audit:export"

    # Administração
    ADMIN_PARAMS = "admin:params"  # parametrização tolerância risco
    ADMIN_USERS = "admin:users"

    # Integrações governamentais
    GOV_CAR_READ = "gov:car:read"
    GOV_GEE_READ = "gov:gee:read"
    GOV_DATAPREV_READ = "gov:dataprev:read"
    GOV_OPENFINANCE_READ = "gov:openfinance:read"


# ─── Identidade ───────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ServiceIdentity:
    """Identidade verificada de um serviço ou usuário humano."""

    subject: str  # service_id ou user_id
    tenant_id: str  # cooperativa / FIAGRO / banco
    scopes: frozenset[Scope]
    is_service: bool = False  # True = token S2S entre microsserviços
    metadata: dict[str, Any] = field(default_factory=dict)

    def has_scope(self, scope: Scope) -> bool:
        return scope in self.scopes

    def require_scope(self, scope: Scope) -> None:
        """Lança PermissionError se o scope não estiver presente."""
        if not self.has_scope(scope):
            raise PermissionError(
                f"Acesso negado: scope '{scope.value}' necessário para subject='{self.subject}'"
            )


# ─── Token JWT ────────────────────────────────────────────────────────────────


class TokenService:
    """Emite e valida tokens JWT para autenticação S2S e usuário."""

    def __init__(self) -> None:
        settings = get_settings()
        self._secret = settings.security.jwt_secret.get_secret_value()
        self._algorithm = settings.security.jwt_algorithm
        self._expire_minutes = settings.security.jwt_expire_minutes

    def issue_service_token(
        self,
        service_id: str,
        tenant_id: str,
        scopes: list[Scope],
        ttl_minutes: int = 15,
    ) -> str:
        """Emite token S2S de curta duração (15min padrão)."""
        now = int(time.time())
        payload = {
            "sub": service_id,
            "tid": tenant_id,
            "scp": [s.value for s in scopes],
            "svc": True,
            "iat": now,
            "exp": now + ttl_minutes * 60,
            "jti": f"{service_id}:{now}",
        }
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def issue_user_token(
        self,
        user_id: str,
        tenant_id: str,
        scopes: list[Scope],
    ) -> str:
        """Emite token de usuário humano."""
        now = int(time.time())
        payload = {
            "sub": user_id,
            "tid": tenant_id,
            "scp": [s.value for s in scopes],
            "svc": False,
            "iat": now,
            "exp": now + self._expire_minutes * 60,
        }
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def verify(self, token: str) -> ServiceIdentity:
        """Valida token JWT e retorna ServiceIdentity. Lança se inválido/expirado."""
        try:
            payload = jwt.decode(token, self._secret, algorithms=[self._algorithm])
        except JWTError as exc:
            raise PermissionError(f"Token inválido ou expirado: {exc}") from exc

        scopes = frozenset(Scope(s) for s in payload.get("scp", []) if s in Scope._value2member_map_)
        return ServiceIdentity(
            subject=payload["sub"],
            tenant_id=payload["tid"],
            scopes=scopes,
            is_service=payload.get("svc", False),
        )


# ─── Password Hashing (usuários humanos) ─────────────────────────────────────

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


# ─── Roles pré-definidos para onboarding rápido ──────────────────────────────

ROLE_SCOPES: dict[str, list[Scope]] = {
    "gestor_fiagro": [
        Scope.SUBSCRIPTION_READ,
        Scope.SUBSCRIPTION_APPROVE,
        Scope.SUBSCRIPTION_REJECT,
        Scope.AUDIT_READ,
        Scope.ADMIN_PARAMS,
    ],
    "analista_cooperativa": [
        Scope.SUBSCRIPTION_READ,
        Scope.SUBSCRIPTION_WRITE,
        Scope.AGENT_ESG_RUN,
        Scope.AGENT_FINANCIAL_RUN,
        Scope.AGENT_SECURITY_RUN,
        Scope.AUDIT_READ,
    ],
    "orchestrator_service": [
        Scope.AGENT_ORCHESTRATE,
        Scope.AGENT_ESG_RUN,
        Scope.AGENT_FINANCIAL_RUN,
        Scope.AGENT_SECURITY_RUN,
        Scope.GOV_CAR_READ,
        Scope.GOV_GEE_READ,
        Scope.GOV_DATAPREV_READ,
        Scope.GOV_OPENFINANCE_READ,
    ],
    "audit_service": [Scope.AUDIT_READ, Scope.AUDIT_EXPORT],
}
