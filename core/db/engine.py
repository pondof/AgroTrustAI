"""
AgroTrust AI – Engine assíncrona SQLAlchemy Core (asyncpg).

  - get_engine(): AsyncEngine singleton (lru_cache) com pool configurado.
  - get_session(): AsyncGenerator[AsyncSession] – dependency FastAPI.
  - healthcheck(): SELECT 1 com timeout, retorna bool.

NUNCA usamos ORM declarativo. Repositórios usam text() + bindparam() (Core),
mais previsível para queries JSONB do PostgreSQL.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from functools import lru_cache

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.config.settings import get_settings

logger = structlog.get_logger(__name__)

_HEALTHCHECK_TIMEOUT_SEC = 5.0


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """
    AsyncEngine singleton (lazy). Lê DB_URL e parâmetros de pool das settings.

    O pool só é criado na primeira conexão real, então importar este módulo em
    testes/CI sem PostgreSQL é seguro.
    """
    settings = get_settings()
    db = settings.database
    url = db.url.get_secret_value()

    engine = create_async_engine(
        url,
        pool_size=db.pool_size,
        max_overflow=db.max_overflow,
        pool_timeout=db.pool_timeout,
        pool_pre_ping=True,
        echo=settings.debug,
        future=True,
    )
    logger.info(
        "db_engine_created",
        pool_size=db.pool_size,
        max_overflow=db.max_overflow,
        # Nunca logamos a URL completa (contém credenciais).
        backend=engine.url.get_backend_name(),
    )
    return engine


@lru_cache(maxsize=1)
def _get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency FastAPI: fornece uma AsyncSession por request e garante rollback
    em caso de exceção não tratada. O commit é responsabilidade do repositório
    (ou da rota) para manter as transações explícitas.
    """
    session_factory = _get_sessionmaker()
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def healthcheck() -> bool:
    """SELECT 1 com timeout de 5s. Retorna True se o banco responde."""
    try:
        async with asyncio.timeout(_HEALTHCHECK_TIMEOUT_SEC):
            engine = get_engine()
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning("db_healthcheck_failed", error=str(exc))
        return False


def reset_engine_cache() -> None:
    """Limpa os singletons de engine/sessionmaker (usado em testes)."""
    get_engine.cache_clear()
    _get_sessionmaker.cache_clear()
