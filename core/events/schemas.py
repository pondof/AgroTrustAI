"""
AgroTrust AI – Schemas de eventos Kafka (contratos imutáveis).

Convenções:
  - Todos os eventos são Pydantic v2 BaseModel com validação estrita.
  - Versão do schema inclusa em todo evento (para evolução sem breaking change).
  - Campos obrigatórios nunca removidos (apenas deprecados + novos adicionados).
  - Serialização: JSON (AVRO para produção via Schema Registry).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

# ─── Base de evento ───────────────────────────────────────────────────────────


class BaseEvent(BaseModel):
    """Envelope padrão para todos os eventos do sistema."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    schema_version: str = "1.0"
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    correlation_id: str  # Liga todos os eventos de um mesmo dossiê
    tenant_id: str  # Cooperativa / FIAGRO / banco


# ─── Tópico: subscription.initiated ─────────────────────────────────────────


class PropertyLocation(BaseModel):
    latitude: float
    longitude: float
    municipio: str
    estado: str  # UF (ex: "MT", "RS")
    biome: str | None = None  # "Cerrado", "Amazônia", "Pampa"...


class SubscriptionInitiatedEvent(BaseEvent):
    event_type: Literal["subscription.initiated"] = "subscription.initiated"
    dossie_id: str
    producer_cpf_hash: str  # SHA-3-256 do CPF – nunca o CPF em claro
    car_number: str  # Número CAR da propriedade
    property_area_ha: float  # Área em hectares
    location: PropertyLocation
    credit_amount_brl: float
    credit_purpose: str  # "custeio" | "investimento" | "comercialização"
    requested_by: str  # user_id do analista que abriu o dossiê


# ─── Tópico: agent.esg.result ────────────────────────────────────────────────


class ESGComplianceStatus(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    PENDING_DOCS = "pending_docs"
    WARNING = "warning"


class ESGAgentResultEvent(BaseEvent):
    event_type: Literal["agent.esg.result"] = "agent.esg.result"
    dossie_id: str
    car_status: str  # "regular" | "pendente" | "cancelado" | "suspenso"
    car_verified_at: str  # ISO timestamp
    deforestation_detected: bool
    deforestation_area_ha: float = 0.0
    reference_year_baseline: int = 2008  # Marco legal Código Florestal
    gee_satellite_images_used: int = 0
    vc_credential_valid: bool  # Credencial verificável Dataprev
    compliance_status: ESGComplianceStatus
    # XAI – racional estruturado (anti-death-by-AI)
    xai_rationale: dict[str, Any] = Field(description="Fatores que levaram à decisão ESG, ordenados por peso.")
    confidence_score: float = Field(ge=0.0, le=1.0)


# ─── Tópico: agent.financial.result ─────────────────────────────────────────


class FinancialAgentResultEvent(BaseEvent):
    event_type: Literal["agent.financial.result"] = "agent.financial.result"
    dossie_id: str
    trust_score: float = Field(ge=0.0, le=1000.0, description="Trust Score+ (0-1000)")
    open_finance_data_months: int  # Meses de histórico coletados
    avg_monthly_revenue_brl: float
    debt_to_income_ratio: float  # DTI
    existing_rural_credit_brl: float
    recommended_credit_limit_brl: float
    risk_tier: str  # "A" | "B" | "C" | "D" | "E"
    xai_rationale: dict[str, Any]
    open_finance_consent_id: str  # ID do consentimento Open Finance BR


# ─── Tópico: agent.security.result ──────────────────────────────────────────


class SecurityAgentResultEvent(BaseEvent):
    event_type: Literal["agent.security.result"] = "agent.security.result"
    dossie_id: str
    liveness_passed: bool
    deepfake_probability: float = Field(ge=0.0, le=1.0)
    voice_clone_probability: float = Field(ge=0.0, le=1.0)
    digital_mask_probability: float = Field(ge=0.0, le=1.0)
    title_verified_on_blockchain: bool
    blockchain_tx_hash: str | None = None
    fraud_risk_level: str  # "low" | "medium" | "high" | "critical"
    kyc_passed: bool


# ─── Tópico: subscription.verdict ────────────────────────────────────────────


class SubscriptionVerdictEvent(BaseEvent):
    event_type: Literal["subscription.verdict"] = "subscription.verdict"
    dossie_id: str
    verdict: str  # "approved" | "rejected" | "manual_review"
    approved_amount_brl: float | None = None
    rejection_reasons: list[str] = Field(default_factory=list)
    esg_score: float
    financial_score: float
    security_score: float
    composite_score: float
    # XAI consolidado – obrigatório para evitar "death by AI"
    xai_consolidated_rationale: dict[str, Any]
    requires_human_review: bool = False
    human_reviewer_id: str | None = None
    processing_time_ms: int

    @model_validator(mode="after")
    def validate_rejection_has_reasons(self) -> SubscriptionVerdictEvent:
        if self.verdict == "rejected" and not self.rejection_reasons:
            raise ValueError("Veredicto 'rejected' deve ter ao menos um rejection_reason (LGPD Art. 20)")
        return self


# ─── Mapa de tópicos → schemas ───────────────────────────────────────────────

TOPIC_SCHEMAS: dict[str, type[BaseEvent]] = {
    "agrotrust.subscription.initiated": SubscriptionInitiatedEvent,
    "agrotrust.agent.esg.result": ESGAgentResultEvent,
    "agrotrust.agent.financial.result": FinancialAgentResultEvent,
    "agrotrust.agent.security.result": SecurityAgentResultEvent,
    "agrotrust.subscription.verdict": SubscriptionVerdictEvent,
}
