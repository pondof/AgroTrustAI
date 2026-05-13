"""
AgroTrust AI – Configuração global de testes.

- Garante que as variáveis de ambiente das APIs governamentais apontem para os mocks locais.
- Silencia o structlog durante toda a suíte (sem poluição de stdout).
- Limpa o cache de get_settings() para que as env vars sejam refletidas.
"""

from __future__ import annotations

import logging
import os

import pytest
import structlog

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
