"""
AgroTrust AI – LangGraph do Orquestrador Multiagente.

Fluxo:
  dispatch → security_check → [condicional] → parallel_agents → verdict
                                    ↘ verdict (short-circuit se fraud crítico)

Fan-out paralelo: ESG + Financeiro rodam via asyncio.gather no nó parallel_agents.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog
from langgraph.graph import END, StateGraph

from agents.esg.agent import ESGAuditorAgent
from agents.esg.schemas import ESGInput
from agents.financial.agent import FinancialAnalystAgent
from agents.financial.schemas import FinancialInput
from agents.orchestrator.state import DossieState
from agents.orchestrator.verdict import VerdictEngine
from agents.security.agent import SecurityGuardAgent
from agents.security.schemas import SecurityInput

logger = structlog.get_logger(__name__)

# ─── Identidades derivadas (mock) ─────────────────────────────────────────────


def _derive_holder_did(cpf_hash: str) -> str:
    """Em produção: consulta registro de identidade. No mock: deriva do cpf_hash."""
    return f"did:gov:br:{cpf_hash[:32]}"


def _derive_consent_id(car_number: str) -> str:
    """Em produção: obtido via fluxo Open Finance. No mock: mapeado por CAR."""
    if "DEFOREST" in car_number or "CANCELADO" in car_number:
        return "CONSENT_HIGH_DTI_002"
    return "CONSENT_REGULAR_001"


def _derive_session_id(dossie_id: str) -> str:
    return f"session-{dossie_id}"


def _derive_media_url(dossie_id: str) -> str:
    return f"https://biometria.agrotrust.ai/media/{dossie_id}.enc"


# ─── Nós do grafo ─────────────────────────────────────────────────────────────


async def _node_dispatch(state: DossieState) -> dict[str, Any]:
    """Valida e complementa o estado com campos derivados."""
    updates: dict[str, Any] = {"start_time_unix": time.time()}

    if not state.get("holder_did"):
        updates["holder_did"] = _derive_holder_did(state.get("producer_cpf_hash", ""))
    if not state.get("open_finance_consent_id"):
        updates["open_finance_consent_id"] = _derive_consent_id(state.get("car_number", ""))
    if not state.get("session_id"):
        updates["session_id"] = _derive_session_id(state.get("dossie_id", ""))
    if not state.get("media_url"):
        updates["media_url"] = _derive_media_url(state.get("dossie_id", ""))

    logger.info(
        "orchestrator_dispatch",
        dossie_id=state.get("dossie_id"),
        correlation_id=state.get("correlation_id"),
    )
    return updates


async def _node_security_check(state: DossieState) -> dict[str, Any]:
    """Executa SecurityGuardAgent. Se fraude crítica → sinaliza short-circuit."""
    agent = SecurityGuardAgent()
    sec_input = SecurityInput(
        dossie_id=state["dossie_id"],
        correlation_id=state["correlation_id"],
        tenant_id=state["tenant_id"],
        session_id=state.get("session_id", ""),
        media_url=state.get("media_url", ""),
        car_number=state["car_number"],
        owner_cpf_hash=state["producer_cpf_hash"],
    )
    sec_output = await agent.run(sec_input)
    updates: dict[str, Any] = {"security_output": sec_output}

    if sec_output.fraud_risk_level == "critical":
        updates["short_circuit_reason"] = (
            f"Fraude crítica: liveness={sec_output.liveness_passed} "
            f"deepfake={sec_output.deepfake_probability:.2f}"
        )
    return updates


def _security_router(state: DossieState) -> str:
    """Roteamento pós-security: short-circuit ou continua para ESG+Financeiro."""
    reason = state.get("short_circuit_reason", "")
    if reason:
        logger.warning(
            "orchestrator_short_circuit",
            dossie_id=state.get("dossie_id"),
            reason=reason,
        )
        return "verdict"
    return "parallel_agents"


async def _node_parallel_agents(state: DossieState) -> dict[str, Any]:
    """Fan-out paralelo: ESG + Financeiro em asyncio.gather."""
    esg_agent = ESGAuditorAgent()
    fin_agent = FinancialAnalystAgent()

    esg_input = ESGInput(
        dossie_id=state["dossie_id"],
        correlation_id=state["correlation_id"],
        tenant_id=state["tenant_id"],
        car_number=state["car_number"],
        holder_did=state.get("holder_did", ""),
        property_area_ha=state.get("property_area_ha", 0.0),
        location_lat=state.get("location_lat", 0.0),
        location_lon=state.get("location_lon", 0.0),
        location_estado=state.get("location_estado", ""),
    )
    fin_input = FinancialInput(
        dossie_id=state["dossie_id"],
        correlation_id=state["correlation_id"],
        tenant_id=state["tenant_id"],
        open_finance_consent_id=state.get("open_finance_consent_id", ""),
        requested_amount_brl=state.get("credit_amount_brl", 0.0),
    )

    esg_result, fin_result = await asyncio.gather(
        esg_agent.run(esg_input),
        fin_agent.run(fin_input),
    )

    logger.info(
        "parallel_agents_completed",
        dossie_id=state.get("dossie_id"),
        esg_compliance=esg_result.compliance_status.value,
        trust_score=fin_result.trust_score,
    )
    return {"esg_output": esg_result, "financial_output": fin_result}


async def _node_verdict(state: DossieState) -> dict[str, Any]:
    """Computa o veredicto final via VerdictEngine."""
    engine = VerdictEngine()
    verdict = engine.compute(state)
    logger.info(
        "orchestrator_verdict",
        dossie_id=state.get("dossie_id"),
        verdict=verdict.verdict,
        composite=verdict.composite_score,
    )
    return {"verdict": verdict}


# ─── Compilação do grafo ──────────────────────────────────────────────────────


def _build_orchestrator_graph() -> Any:
    graph: StateGraph = StateGraph(DossieState)  # type: ignore[type-arg]

    graph.add_node("dispatch", _node_dispatch)
    graph.add_node("security_check", _node_security_check)
    graph.add_node("parallel_agents", _node_parallel_agents)
    graph.add_node("verdict", _node_verdict)

    graph.set_entry_point("dispatch")
    graph.add_edge("dispatch", "security_check")
    graph.add_conditional_edges(
        "security_check",
        _security_router,
        {"verdict": "verdict", "parallel_agents": "parallel_agents"},
    )
    graph.add_edge("parallel_agents", "verdict")
    graph.add_edge("verdict", END)

    return graph.compile()


_ORCHESTRATOR_GRAPH: Any = None


def get_orchestrator_graph() -> Any:
    """Singleton do grafo compilado (thread-safe via GIL para leitura)."""
    global _ORCHESTRATOR_GRAPH
    if _ORCHESTRATOR_GRAPH is None:
        _ORCHESTRATOR_GRAPH = _build_orchestrator_graph()
    return _ORCHESTRATOR_GRAPH


async def run_orchestrator(initial_state: DossieState) -> DossieState:
    """Entry-point para execução do orquestrador completo."""
    graph = get_orchestrator_graph()
    result: DossieState = await graph.ainvoke(initial_state)
    return result
