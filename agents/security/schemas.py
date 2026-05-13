"""AgroTrust AI – Schemas de entrada e saída do Agente de Segurança."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SecurityInput(BaseModel):
    dossie_id: str
    correlation_id: str
    tenant_id: str
    session_id: str  # ID da sessão biométrica
    media_url: str  # URL (criptografada) do vídeo/foto – nunca em claro
    car_number: str
    owner_cpf_hash: str  # SHA-3-256 do CPF, nunca CPF em claro


class SecurityOutput(BaseModel):
    dossie_id: str
    liveness_passed: bool
    deepfake_probability: float = Field(ge=0.0, le=1.0)
    voice_clone_probability: float = Field(ge=0.0, le=1.0)
    digital_mask_probability: float = Field(ge=0.0, le=1.0)
    title_verified_on_blockchain: bool
    blockchain_tx_hash: str | None
    fraud_risk_level: str  # "low" | "medium" | "high" | "critical"
    kyc_passed: bool
    xai_rationale: dict[str, Any]
