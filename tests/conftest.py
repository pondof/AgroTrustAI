"""
AgroTrust AI – Configuração global de testes.

- Garante que as variáveis de ambiente das APIs governamentais apontem para os mocks locais.
- Silencia o structlog durante toda a suíte (sem poluição de stdout).
- Limpa o cache de get_settings() para que as env vars sejam refletidas.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

# ─── URLs dos mocks locais ────────────────────────────────────────────────────

_GOV_ENV_VARS: dict[str, str] = {
    "GOV_SICAR_BASE_URL": "http://localhost:8001",
    "GOV_GEE_BASE_URL": "http://localhost:8002",
    "GOV_DATAPREV_BASE_URL": "http://localhost:8003",
    "GOV_OPEN_FINANCE_BASE_URL": "http://localhost:8004",
}


def _drop_all_structlog_events(logger: object, method: str, event_dict: dict) -> dict:  # pragma: no cover
    raise structlog.DropEvent()


@pytest.fixture(autouse=True, scope="session")
def configure_test_environment() -> None:
    """
    Fixture de sessão aplicada automaticamente a todos os testes.

    1. Seta env vars das APIs gov para os mocks localhost.
    2. Limpa o cache de get_settings() para refletir as novas vars.
    3. Configura structlog para descartar todos os eventos (sem output verboso).
    """
    for key, val in _GOV_ENV_VARS.items():
        os.environ[key] = val

    # Limpa o singleton de configurações para que as env vars sejam lidas novamente
    from core.config.settings import get_settings

    get_settings.cache_clear()

    # Silencia structlog durante toda a suíte
    structlog.configure(processors=[_drop_all_structlog_events])

    # Silencia o logging padrão do Python também
    logging.getLogger().setLevel(logging.CRITICAL)


# ─── Banco SQLite async in-memory (substitui asyncpg nos testes) ─────────────
#
# DDL portável equivalente a core/db/migrations/001_initial.sql: tipos PostgreSQL
# (UUID/JSONB/TEXT[]/TIMESTAMPTZ) viram TEXT/REAL/INTEGER no SQLite. Os repositórios
# serializam JSON/array via tipos genéricos SQLAlchemy, então o mesmo código roda
# nos dois backends.

_SQLITE_DDL: tuple[str, ...] = (
    """
    CREATE TABLE dossies (
        id                          TEXT PRIMARY KEY,
        dossie_id                   TEXT UNIQUE NOT NULL,
        correlation_id              TEXT NOT NULL,
        tenant_id                   TEXT NOT NULL,
        producer_cpf_hash           TEXT NOT NULL,
        car_number                  TEXT NOT NULL,
        property_area_ha            REAL NOT NULL,
        credit_amount_brl           REAL NOT NULL,
        credit_purpose              TEXT NOT NULL,
        requested_by                TEXT NOT NULL,
        status                      TEXT NOT NULL DEFAULT 'initiated',
        verdict                     TEXT,
        composite_score             REAL,
        esg_score                   REAL,
        financial_score             REAL,
        security_score              REAL,
        approved_amount_brl         REAL,
        rejection_reasons           TEXT,
        xai_consolidated_rationale  TEXT,
        processing_time_ms          INTEGER,
        created_at                  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at                  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE audit_log (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id       TEXT NOT NULL UNIQUE,
        timestamp      TEXT NOT NULL,
        event_type     TEXT NOT NULL,
        subject        TEXT NOT NULL,
        tenant_id      TEXT NOT NULL,
        resource_id    TEXT NOT NULL,
        outcome        TEXT NOT NULL,
        details        TEXT NOT NULL,
        previous_hash  TEXT NOT NULL,
        entry_hash     TEXT NOT NULL UNIQUE
    )
    """,
    """
    CREATE TABLE risk_params (
        id                     TEXT PRIMARY KEY,
        tenant_id              TEXT NOT NULL UNIQUE,
        w_esg                  REAL NOT NULL DEFAULT 0.35,
        w_financial            REAL NOT NULL DEFAULT 0.45,
        w_security             REAL NOT NULL DEFAULT 0.20,
        approve_threshold      REAL NOT NULL DEFAULT 600.0,
        manual_threshold       REAL NOT NULL DEFAULT 450.0,
        max_dti                REAL NOT NULL DEFAULT 0.65,
        max_credit_multiplier  REAL NOT NULL DEFAULT 12.0,
        updated_by             TEXT NOT NULL DEFAULT 'system',
        updated_at             TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
)


@pytest_asyncio.fixture
async def sqlite_sessionmaker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """
    async_sessionmaker ligado a um SQLite in-memory com as tabelas da Fase 2 criadas.

    StaticPool + uma única conexão garante que o `:memory:` persista entre as
    sessões abertas pelos repositórios durante o teste.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        for ddl in _SQLITE_DDL:
            await conn.execute(text(ddl))

    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield maker
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(
    sqlite_sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Uma AsyncSession pronta para uso pelos repositórios."""
    async with sqlite_sessionmaker() as session:
        yield session
