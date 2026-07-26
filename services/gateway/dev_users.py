"""
AgroTrust AI – Usuários mock para autenticação em DESENVOLVIMENTO.

⚠️  APENAS DEV. Esta lista hardcoded existe para permitir o login do frontend
    (POST /token) sem um Identity Provider real. Em produção, o /token deve
    delegar para Keycloak/Auth0/Cognito (OIDC) e esta lista NÃO deve ser usada.

Isolamento por tenant: ambos os usuários pertencem ao mesmo tenant de demonstração
(`coop-demo`), de modo que compartilham a mesma projeção de dossiês no ambiente dev.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass

from core.security.iam import Scope

DEV_TENANT_ID = "coop-demo"


@dataclass(frozen=True, slots=True)
class DevUser:
    username: str
    password: str  # DEV-ONLY: texto plano; comparado em tempo constante.
    tenant_id: str
    scopes: tuple[Scope, ...]


# Perfis alinhados ao ROLE_SCOPES de core.security.iam (analista_cooperativa / gestor_fiagro).
_DEV_USERS: dict[str, DevUser] = {
    "analista@agrotrust.ai": DevUser(
        username="analista@agrotrust.ai",
        password="analista123",  # noqa: S106 – credencial de desenvolvimento
        tenant_id=DEV_TENANT_ID,
        scopes=(
            Scope.SUBSCRIPTION_READ,
            Scope.SUBSCRIPTION_WRITE,
            Scope.AUDIT_READ,
        ),
    ),
    "gestor@agrotrust.ai": DevUser(
        username="gestor@agrotrust.ai",
        password="gestor123",  # noqa: S106 – credencial de desenvolvimento
        tenant_id=DEV_TENANT_ID,
        scopes=(
            Scope.SUBSCRIPTION_READ,
            Scope.SUBSCRIPTION_WRITE,
            Scope.ADMIN_PARAMS,
            Scope.AUDIT_READ,
            Scope.AUDIT_EXPORT,
        ),
    ),
}


def authenticate_dev_user(username: str, password: str) -> DevUser | None:
    """
    Valida credenciais contra a lista dev. Comparação de senha em tempo constante
    (hmac.compare_digest) para não vazar informação por timing, mesmo em dev.
    Retorna o DevUser em caso de sucesso ou None se usuário/senha inválidos.
    """
    user = _DEV_USERS.get(username.strip().lower())
    if user is None:
        # Compara contra um valor dummy para manter o tempo de resposta uniforme.
        hmac.compare_digest(password, "dummy-password-constant-time")
        return None
    if not hmac.compare_digest(password, user.password):
        return None
    return user
