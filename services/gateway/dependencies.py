"""
AgroTrust AI – Dependências FastAPI reutilizáveis do Gateway.

  - get_identity: extrai ServiceIdentity injetada pelo JWTAuthMiddleware.
  - require_scope: factory que retorna Depends() exigindo scope específico.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException, Request, status

from core.security.iam import Scope, ServiceIdentity


def get_identity(request: Request) -> ServiceIdentity:
    """
    Retorna a ServiceIdentity injetada pelo middleware JWT.
    Lança 401 se não houver identidade (rota pública mal configurada).
    """
    identity: ServiceIdentity | None = getattr(request.state, "identity", None)
    if identity is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identidade não autenticada para este endpoint",
        )
    return identity


def require_scope(required: Scope) -> Callable[[Request], ServiceIdentity]:
    """
    Factory: retorna função pronta para uso como FastAPI Depends() que
    valida se a identidade autenticada possui o scope exigido.

    Exemplo:
        @router.post("/x", dependencies=[Depends(require_scope(Scope.X))])
        async def x(...): ...
    """

    def _checker(request: Request) -> ServiceIdentity:
        identity = get_identity(request)
        if not identity.has_scope(required):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Scope '{required.value}' necessário",
            )
        return identity

    _checker.__name__ = f"require_scope_{required.value}"
    return _checker
