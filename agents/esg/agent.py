"""
AgroTrust AI – ESGAuditorAgent (LangGraph state machine).

Grafo interno:
  validate_car → detect_deforestation → verify_vc → compute_compliance

Regra do Código Florestal: qualquer desmatamento pós-2008 → REJECTED automático.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, TypedDict

import structlog
from langgraph.graph import END, StateGraph
from pydantic import BaseModel

from agents.base import AgentExecutionError, BaseAgent, XAIFactor
from agents.esg.schemas import ESGInput, ESGOutput
from agents.esg.tools import (
    CARStatusResult,
    GEEDeforestationResult,
    VCCredentialResult,
    detect_deforestation,
    fetch_car_status,
    verify_vc_credential,
)
from core.config.settings import get_settings
from core.events.schemas import ESGComplianceStatus

logger = structlog.get_logger(__name__)


# ─── Estado interno do grafo ──────────────────────────────────────────────────


class ESGAgentState(TypedDict, total=False):
    # Inputs (populados na entrada do grafo)
    car_number: str
    holder_did: str
    lat: float
    lon: float
    area_ha: float
    correlation_id: str
    dossie_id: str

    # Resultados dos nós
    car_result: CARStatusResult | None
    deforestation_result: GEEDeforestationResult | None
    vc_result: VCCredentialResult | None

    # Saída final
    compliance_status: ESGComplianceStatus | None
    confidence_score: float | None
    xai_rationale: dict[str, Any] | None
    error: str | None


# ─── Nós do grafo ─────────────────────────────────────────────────────────────


async def _node_validate_car(state: ESGAgentState) -> dict[str, Any]:
    settings = get_settings()
    car_result = await fetch_car_status(
        car_number=state["car_number"],
        base_url=settings.gov_apis.sicar_base_url,
        timeout=settings.gov_apis.request_timeout,
    )
    return {"car_result": car_result}


async def _node_detect_deforestation(state: ESGAgentState) -> dict[str, Any]:
    settings = get_settings()
    defo_result = await detect_deforestation(
        car_number=state["car_number"],
        lat=state.get("lat", 0.0),
        lon=state.get("lon", 0.0),
        area_ha=state.get("area_ha", 0.0),
        base_url=settings.gov_apis.gee_base_url,
        timeout=settings.gov_apis.request_timeout,
    )
    return {"deforestation_result": defo_result}


async def _node_verify_vc(state: ESGAgentState) -> dict[str, Any]:
    settings = get_settings()
    vc_result = await verify_vc_credential(
        holder_did=state["holder_did"],
        base_url=settings.gov_apis.dataprev_base_url,
        timeout=settings.gov_apis.request_timeout,
    )
    return {"vc_result": vc_result}


async def _node_compute_compliance(state: ESGAgentState) -> dict[str, Any]:
    car: CARStatusResult = state.get("car_result")  # type: ignore[assignment]
    defo: GEEDeforestationResult = state.get("deforestation_result")  # type: ignore[assignment]
    vc: VCCredentialResult = state.get("vc_result")  # type: ignore[assignment]

    if not car or not defo or not vc:
        return {
            "compliance_status": ESGComplianceStatus.REJECTED,
            "confidence_score": 1.0,
            "xai_rationale": {
                "decision": "rejected",
                "factors": [{"name": "missing_data", "weight": 1.0, "value": None, "impact": "negative"}],
                "confidence": 1.0,
                "model_version": "0.1.0",
                "timestamp": datetime.now(UTC).isoformat(),
            },
        }

    # ── Regras de negócio (Código Florestal + CAR) ─────────────────────────
    reasons: list[str] = []

    car_inactive = car.status in {"cancelado", "suspenso"}
    defo_post_2008 = defo.deforestation_detected and defo.deforestation_area_ha > 0.0
    vc_invalid = not vc.is_valid or vc.is_revoked

    if car_inactive:
        reasons.append(f"CAR {car.status}")
    if defo_post_2008:
        reasons.append(f"Desmatamento pós-2008: {defo.deforestation_area_ha:.1f} ha")
    if vc_invalid:
        reasons.append("Credencial Dataprev inválida/revogada")

    pending = car.status == "pendente" or car.compliance_status == "com_pendencia"

    if car_inactive or defo_post_2008:
        compliance = ESGComplianceStatus.REJECTED
        confidence = 0.97
    elif vc_invalid:
        compliance = ESGComplianceStatus.PENDING_DOCS
        confidence = 0.90
    elif pending:
        compliance = ESGComplianceStatus.PENDING_DOCS
        confidence = 0.85
    else:
        compliance = ESGComplianceStatus.APPROVED
        confidence = 0.92 if vc.chain_of_trust else 0.88

    # ── XAI ────────────────────────────────────────────────────────────────
    factors = [
        XAIFactor(
            name="car_status",
            weight=0.40,
            value=car.status,
            impact="negative" if car_inactive else "positive",
        ),
        XAIFactor(
            name="deforestation_post_2008",
            weight=0.35,
            value=defo.deforestation_area_ha,
            impact="negative" if defo_post_2008 else "positive",
        ),
        XAIFactor(
            name="vc_credential_valid",
            weight=0.15,
            value=vc.is_valid,
            impact="negative" if vc_invalid else "positive",
        ),
        XAIFactor(
            name="compliance_status_sicar",
            weight=0.10,
            value=car.compliance_status,
            impact="negative" if car.compliance_status == "irregular" else "positive",
        ),
    ]
    # Reusa BaseAgent._build_xai_rationale via standalone helper
    xai: dict[str, Any] = {
        "decision": compliance.value,
        "reasons": reasons,
        "factors": [
            {
                "name": f.name,
                "weight": round(abs(f.weight) / sum(abs(x.weight) for x in factors), 4),
                "value": f.value,
                "impact": f.impact,
            }
            for f in sorted(factors, key=lambda x: abs(x.weight), reverse=True)
        ],
        "confidence": round(confidence, 4),
        "model_version": "0.1.0",
        "timestamp": datetime.now(UTC).isoformat(),
    }

    return {
        "compliance_status": compliance,
        "confidence_score": confidence,
        "xai_rationale": xai,
    }


# ─── Compilação do grafo ESG ──────────────────────────────────────────────────


def _build_esg_graph() -> Any:
    graph: StateGraph = StateGraph(ESGAgentState)  # type: ignore[type-arg]
    graph.add_node("validate_car", _node_validate_car)
    graph.add_node("detect_deforestation", _node_detect_deforestation)
    graph.add_node("verify_vc", _node_verify_vc)
    graph.add_node("compute_compliance", _node_compute_compliance)

    graph.set_entry_point("validate_car")
    graph.add_edge("validate_car", "detect_deforestation")
    graph.add_edge("detect_deforestation", "verify_vc")
    graph.add_edge("verify_vc", "compute_compliance")
    graph.add_edge("compute_compliance", END)

    return graph.compile()


_ESG_GRAPH: Any = None


def _get_esg_graph() -> Any:
    global _ESG_GRAPH
    if _ESG_GRAPH is None:
        _ESG_GRAPH = _build_esg_graph()
    return _ESG_GRAPH


# ─── Agente ───────────────────────────────────────────────────────────────────


class ESGAuditorAgent(BaseAgent):
    """
    Agente de conformidade ambiental (ESG).
    Executa o grafo LangGraph interno e devolve ESGOutput.
    """

    MODEL_VERSION = "esg-0.1.0"

    async def run(self, input_data: BaseModel) -> ESGOutput:
        if not isinstance(input_data, ESGInput):
            raise TypeError(f"Esperava ESGInput, recebeu {type(input_data)}")

        esg_input: ESGInput = input_data
        log = logger.bind(
            correlation_id=esg_input.correlation_id,
            dossie_id=esg_input.dossie_id,
        )
        log.info("esg_agent_started")

        initial_state: ESGAgentState = {
            "car_number": esg_input.car_number,
            "holder_did": esg_input.holder_did,
            "lat": esg_input.location_lat,
            "lon": esg_input.location_lon,
            "area_ha": esg_input.property_area_ha,
            "correlation_id": esg_input.correlation_id,
            "dossie_id": esg_input.dossie_id,
        }

        try:
            graph = _get_esg_graph()
            final_state: ESGAgentState = await graph.ainvoke(initial_state)
        except Exception as exc:
            log.error("esg_agent_failed", error=str(exc))
            raise AgentExecutionError(
                correlation_id=esg_input.correlation_id,
                agent_name="ESGAuditorAgent",
                original_exception=exc,
            ) from exc

        car_result: CARStatusResult | None = final_state.get("car_result")
        defo_result: GEEDeforestationResult | None = final_state.get("deforestation_result")
        vc_result: VCCredentialResult | None = final_state.get("vc_result")

        compliance = final_state.get("compliance_status") or ESGComplianceStatus.REJECTED
        confidence = final_state.get("confidence_score") or 0.0
        xai = final_state.get("xai_rationale") or {}

        log.info(
            "esg_agent_completed",
            compliance=compliance.value,
            confidence=confidence,
        )

        return ESGOutput(
            dossie_id=esg_input.dossie_id,
            car_status=car_result.status if car_result else "unknown",
            car_verified_at=datetime.now(UTC).isoformat(),
            deforestation_detected=defo_result.deforestation_detected if defo_result else False,
            deforestation_area_ha=defo_result.deforestation_area_ha if defo_result else 0.0,
            gee_satellite_images_used=defo_result.gee_images_count if defo_result else 0,
            vc_credential_valid=vc_result.is_valid if vc_result else False,
            compliance_status=compliance,
            confidence_score=confidence,
            xai_rationale=xai,
        )
