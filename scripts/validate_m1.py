"""
AgroTrust AI – Validacao do Marco M1.

Executa 50 dossies sinteticos contra o orquestrador LangGraph com mocks HTTP
de SICAR / GEE / Dataprev / Open Finance via respx. Criterios M1:

  (1) Cada dossie produz um SubscriptionVerdictEvent valido (Pydantic).
  (2) xai_consolidated_rationale presente com as 4 chaves obrigatorias
      (scores, esg_rationale, financial_rationale, security_rationale).
  (3) rejection_reasons obrigatorio quando verdict='rejected' (LGPD Art. 20).
  (4) processing_time_ms < 30000 (30s) por dossie.

Uso:
  python -m scripts.validate_m1
  python scripts/validate_m1.py

Exit codes:
  0  -- todos os criterios satisfeitos
  1  -- qualquer falha de validacao ou erro de execucao
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# ─── Bootstrap de sys.path: permite rodar via "python scripts/validate_m1.py" ─
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ─── Env vars dos mocks devem estar setadas ANTES de importar core/agents ─────
os.environ.setdefault("GOV_SICAR_BASE_URL", "http://localhost:8001")
os.environ.setdefault("GOV_GEE_BASE_URL", "http://localhost:8002")
os.environ.setdefault("GOV_DATAPREV_BASE_URL", "http://localhost:8003")
os.environ.setdefault("GOV_OPEN_FINANCE_BASE_URL", "http://localhost:8004")

import respx  # noqa: E402  -- import depois do path bootstrap
import structlog  # noqa: E402

from agents.financial.tools import _get_model  # noqa: E402
from agents.orchestrator.graph import get_orchestrator_graph  # noqa: E402
from core.config.settings import get_settings  # noqa: E402
from scripts.m1.mocks import register_mocks  # noqa: E402
from scripts.m1.report import aggregate, render_report  # noqa: E402
from scripts.m1.runner import run_all  # noqa: E402
from scripts.m1.scenarios import generate_scenarios  # noqa: E402

logger = structlog.get_logger("scripts.validate_m1")


async def _run() -> int:
    # Garante que as env vars sejam refletidas no cache de settings
    get_settings.cache_clear()

    # Warm-up: treina XGBoost e compila LangGraph antes do paralelismo
    logger.info("m1_warmup_starting")
    _get_model()
    get_orchestrator_graph()
    logger.info("m1_warmup_done")

    scenarios = generate_scenarios()
    logger.info(
        "m1_scenarios_generated",
        count=len(scenarios),
        by_category={
            "approved": sum(1 for s in scenarios if s.category == "approved"),
            "manual_review": sum(1 for s in scenarios if s.category == "manual_review"),
            "rejected_esg": sum(1 for s in scenarios if s.category == "rejected_esg"),
            "rejected_fraud": sum(1 for s in scenarios if s.category == "rejected_fraud"),
        },
    )

    with respx.mock(assert_all_called=False, assert_all_mocked=False) as router:
        register_mocks(router, scenarios)
        results = await run_all(scenarios, max_concurrent=10)

    report = aggregate(results)
    render_report(report)
    return 0 if report.passed else 1


def cli() -> int:
    """Entry-point CLI."""
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(cli())
