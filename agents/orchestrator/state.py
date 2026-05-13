"""
AgroTrust AI – DossieState: estado compartilhado entre todos os nós do orquestrador.

Contém os campos do SubscriptionInitiatedEvent + saídas dos 3 agentes + veredicto.
TypedDict com total=False: todos os campos são opcionais para inicialização incremental.
"""

from __future__ import annotations

from typing import TypedDict

# Importações diretas: LangGraph resolve get_type_hints() em runtime via StateGraph(DossieState).
# TYPE_CHECKING causaria NameError. Não há import circular nesta cadeia.
from agents.esg.schemas import ESGOutput
from agents.financial.schemas import FinancialOutput
from agents.security.schemas import SecurityOutput
from core.events.schemas import SubscriptionVerdictEvent


class DossieState(TypedDict, total=False):
    # ─── Campos do SubscriptionInitiatedEvent ────────────────────────────────
    dossie_id: str
    correlation_id: str
    tenant_id: str
    producer_cpf_hash: str  # SHA-3-256 – nunca CPF em claro
    car_number: str
    property_area_ha: float
    location_lat: float
    location_lon: float
    location_estado: str
    credit_amount_brl: float
    credit_purpose: str
    requested_by: str

    # ─── Campos derivados / resolução de identidade (não vêm no evento Kafka) ─
    holder_did: str  # DID Dataprev do produtor
    open_finance_consent_id: str
    session_id: str  # ID da sessão biométrica
    media_url: str  # URL do vídeo/foto (criptografada)

    # ─── Saídas dos agentes ──────────────────────────────────────────────────
    esg_output: ESGOutput | None
    financial_output: FinancialOutput | None
    security_output: SecurityOutput | None

    # ─── Veredicto final ─────────────────────────────────────────────────────
    verdict: SubscriptionVerdictEvent | None

    # ─── Controle de execução ────────────────────────────────────────────────
    start_time_unix: float  # epoch para calcular processing_time_ms
    short_circuit_reason: str  # preenchido quando security SHORT-CIRCUIT
    error: str | None
