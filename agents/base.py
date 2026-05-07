"""
AgroTrust AI – Classe base para todos os agentes.

Contratos:
  - run(input) -> output  (abstrato)
  - _build_xai_rationale() devolve estrutura padronizada (anti-death-by-AI)
  - Todo I/O de log usa structlog com correlation_id em contexto
  - Erros de execução são sempre AgentExecutionError (nunca raw exception)
"""
from __future__ import annotations

import abc
from datetime import UTC, datetime
from typing import Any

import structlog
from pydantic import BaseModel

logger = structlog.get_logger(__name__)

# ─── Erros ────────────────────────────────────────────────────────────────────


class AgentExecutionError(Exception):
    """Envelope para erros de agente — nunca propague raw exceptions para fora."""

    def __init__(
        self,
        correlation_id: str,
        agent_name: str,
        original_exception: Exception,
    ) -> None:
        self.correlation_id = correlation_id
        self.agent_name = agent_name
        self.original_exception = original_exception
        super().__init__(
            f"[{agent_name}:{correlation_id}] "
            f"{type(original_exception).__name__}: {original_exception}"
        )


# ─── XAI factor helper ────────────────────────────────────────────────────────


class XAIFactor(BaseModel):
    """Um único fator de explicabilidade da decisão."""

    name: str
    weight: float          # importância relativa (0-1), normalizada entre os fatores
    value: object          # valor real do fator no dossiê
    impact: str            # "positive" | "negative" | "neutral"


# ─── Base abstrata ────────────────────────────────────────────────────────────


class BaseAgent(abc.ABC):
    """
    ABC que todos os agentes do AgroTrust AI herdam.

    Subclasses devem definir:
      MODEL_VERSION: str   – versão do modelo/lógica para audit trail
    """

    MODEL_VERSION: str = "0.1.0"

    @abc.abstractmethod
    async def run(self, input_data: BaseModel) -> BaseModel:
        """
        Executa o agente de forma assíncrona.
        Deve capturar todas as exceções e relançá-las como AgentExecutionError.
        """

    def _build_xai_rationale(
        self,
        decision: str,
        factors: list[XAIFactor],
        confidence: float,
    ) -> dict[str, Any]:
        """
        Constrói racional XAI estruturado obrigatório por toda decisão.
        Lança TypeError se chamado sem fatores (prevenção de death-by-AI).
        """
        if not factors:
            raise TypeError(
                f"{self.__class__.__name__}: xai_rationale exige ao menos um fator "
                "– decisão sem explicabilidade não é permitida."
            )
        total_weight = sum(abs(f.weight) for f in factors) or 1.0
        return {
            "decision": decision,
            "factors": [
                {
                    "name": f.name,
                    "weight": round(abs(f.weight) / total_weight, 4),
                    "value": f.value,
                    "impact": f.impact,
                }
                for f in sorted(factors, key=lambda x: abs(x.weight), reverse=True)
            ],
            "confidence": round(max(0.0, min(1.0, confidence)), 4),
            "model_version": self.MODEL_VERSION,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def _log(self, event: str, **kwargs: object) -> None:
        logger.info(event, agent=self.__class__.__name__, **kwargs)

    def _log_error(self, event: str, **kwargs: object) -> None:
        logger.error(event, agent=self.__class__.__name__, **kwargs)
