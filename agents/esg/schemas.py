"""AgroTrust AI – Schemas de entrada e saída do Agente ESG."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from core.events.schemas import ESGComplianceStatus


class ESGInput(BaseModel):
    dossie_id: str
    correlation_id: str
    tenant_id: str
    car_number: str
    holder_did: str                # DID Dataprev do produtor
    property_area_ha: float
    location_lat: float
    location_lon: float
    location_estado: str


class ESGOutput(BaseModel):
    dossie_id: str
    car_status: str                # ativo | pendente | cancelado | suspenso
    car_verified_at: str           # ISO-8601
    deforestation_detected: bool
    deforestation_area_ha: float = Field(default=0.0, ge=0.0)
    gee_satellite_images_used: int = Field(default=0, ge=0)
    vc_credential_valid: bool
    compliance_status: ESGComplianceStatus
    confidence_score: float = Field(ge=0.0, le=1.0)
    xai_rationale: dict[str, Any]
