"""
AgroTrust AI – Camada de persistência (PostgreSQL asyncpg + SQLAlchemy Core).

Convenções (ver RESTRIÇÕES da Fase 2):
  - SQLAlchemy Core apenas (text() + bindparam()), sem ORM declarativo.
  - Todos os métodos de repositório são async e recebem AsyncSession.
  - Todo acesso filtra por tenant_id no WHERE (row-level isolation).
  - Migrações são SQL puro, numeradas em core/db/migrations/.
"""

from __future__ import annotations

from core.db.engine import get_engine, get_session, healthcheck

__all__ = ["get_engine", "get_session", "healthcheck"]
