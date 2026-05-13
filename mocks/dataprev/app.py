"""
AgroTrust AI – Mock Dataprev / DaaS (Digital-Identity-as-a-Service).

Simula a API do programa de Identidade Digital governamental brasileiro
(DaaS – Digital-Identity-as-a-Service, MGI/Dataprev) para verificação de
Credenciais Verificáveis (W3C Verifiable Credentials) de produtores rurais.

Referências:
  - Biometric Update: Brazil adopts DaaS for verifiable credentials (2026)
  - Gov.br: Carteira de Identidade Nacional (CIN)
  - W3C VC Data Model v2.0
"""

from __future__ import annotations

import asyncio
import hashlib
import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI(
    title="Mock Dataprev DaaS – Verifiable Credentials API",
    description="Simulação da API DaaS/Dataprev para verificação de credenciais de produtores rurais",
    version="1.0.0",
)


# ─── Modelos ──────────────────────────────────────────────────────────────────


class VerifiableCredential(BaseModel):
    """W3C VC Data Model v2.0 simplificado."""

    context: list[str]
    id: str
    type: list[str]
    issuer: str
    issuance_date: str
    expiration_date: str
    credential_subject: dict[str, Any]
    proof: dict[str, Any]


class CredentialVerificationResult(BaseModel):
    credential_id: str
    holder_did: str  # Decentralized Identifier do produtor
    verified: bool
    verification_method: str
    verification_timestamp: str
    credential_type: str
    issuer: str
    is_revoked: bool
    revocation_reason: str | None
    claims: dict[str, Any]  # Claims verificados (sem PII em claro)
    signature_valid: bool
    chain_of_trust: list[str]  # Cadeia de confiança até raiz gov.br


class ProducerDAASProfile(BaseModel):
    holder_did: str
    cin_verified: bool  # Carteira de Identidade Nacional
    car_linked: bool  # CAR vinculado na identidade digital
    rural_producer_credential: VerifiableCredential | None
    biometric_enrolled: bool
    last_verification: str
    trust_level: str  # "high" | "medium" | "low" | "unverified"


# ─── Base de dados simulada ───────────────────────────────────────────────────


def _did(seed: str) -> str:
    h = hashlib.sha3_256(seed.encode()).hexdigest()[:32]
    return f"did:gov:br:{h}"


_PRODUCER_DATABASE: dict[str, dict[str, Any]] = {
    "DID_REGULAR_PRODUCER_001": {
        "holder_did": _did("producer-001"),
        "cin_verified": True,
        "car_linked": True,
        "car_number": "MT-5100250-3A4B5C6D7E8F9A0B",
        "biometric_enrolled": True,
        "trust_level": "high",
        "is_revoked": False,
        "claims": {
            "rural_producer": True,
            "activity": "soja",
            "states": ["MT"],
            "car_status": "ativo",
            "cin_issuer": "DETRAN-MT",
        },
    },
    "DID_PENDING_PRODUCER_002": {
        "holder_did": _did("producer-002"),
        "cin_verified": True,
        "car_linked": False,  # CAR não vinculado ainda
        "car_number": None,
        "biometric_enrolled": True,
        "trust_level": "medium",
        "is_revoked": False,
        "claims": {
            "rural_producer": True,
            "activity": "pecuaria",
            "states": ["GO"],
            "car_status": "pendente",
        },
    },
    "DID_REVOKED_PRODUCER_003": {
        "holder_did": _did("producer-003"),
        "cin_verified": True,
        "car_linked": True,
        "car_number": "PA-1500602-DEFOREST00000001",
        "biometric_enrolled": True,
        "trust_level": "low",
        "is_revoked": True,
        "revocation_reason": "Embargo IBAMA por desmatamento ilegal",
        "claims": {"rural_producer": True, "activity": "madeireira", "states": ["PA"]},
    },
}


def _build_vc(holder_did: str, data: dict[str, Any]) -> VerifiableCredential:
    vc_id = f"urn:uuid:{uuid.uuid4()}"
    now = datetime.now(UTC)
    return VerifiableCredential(
        context=[
            "https://www.w3.org/2018/credentials/v2",
            "https://schema.gov.br/agro/v1",
        ],
        id=vc_id,
        type=["VerifiableCredential", "RuralProducerCredential"],
        issuer="did:gov:br:dataprev:mgi",
        issuance_date=now.isoformat(),
        expiration_date=(now + timedelta(days=365)).isoformat(),
        credential_subject={
            "id": holder_did,
            **{k: v for k, v in data["claims"].items() if k != "cpf"},
        },
        proof={
            "type": "Ed25519Signature2020",
            "created": now.isoformat(),
            "verificationMethod": "did:gov:br:dataprev:mgi#key-1",
            "proofPurpose": "assertionMethod",
            "proofValue": f"mock-proof-{hashlib.sha3_256(holder_did.encode()).hexdigest()[:32]}",
        },
    )


# ─── Endpoints ────────────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "mock-dataprev-daas"}


@app.get("/api/v1/credentials/{holder_did}/verify", response_model=CredentialVerificationResult)
async def verify_credential(
    holder_did: str,
    credential_type: str = "RuralProducerCredential",
    x_api_key: str = Header(default="mock-key"),
) -> CredentialVerificationResult:
    """
    Verifica a autenticidade e validade de uma Credencial Verificável de produtor rural.
    Simula delay de validação criptográfica (200ms – 800ms).
    """
    await asyncio.sleep(random.uniform(0.2, 0.8))

    # Simula indisponibilidade esporádica (3%)
    if random.random() < 0.03:
        raise HTTPException(status_code=503, detail="Dataprev DaaS temporariamente indisponível")

    producer = next((v for v in _PRODUCER_DATABASE.values() if v["holder_did"] == holder_did), None)
    if not producer:
        raise HTTPException(status_code=404, detail=f"DID '{holder_did}' não encontrado no DaaS")

    return CredentialVerificationResult(
        credential_id=f"urn:uuid:{uuid.uuid4()}",
        holder_did=holder_did,
        verified=not producer["is_revoked"],
        verification_method="Ed25519Signature2020",
        verification_timestamp=datetime.now(UTC).isoformat(),
        credential_type=credential_type,
        issuer="did:gov:br:dataprev:mgi",
        is_revoked=producer["is_revoked"],
        revocation_reason=producer.get("revocation_reason"),
        claims=producer["claims"],
        signature_valid=True,
        chain_of_trust=["did:gov:br:dataprev:mgi", "did:gov:br:iti", "did:gov:br:root"],
    )


@app.get("/api/v1/producers/{holder_did}/profile", response_model=ProducerDAASProfile)
async def get_producer_profile(
    holder_did: str,
    x_api_key: str = Header(default="mock-key"),
) -> ProducerDAASProfile:
    """Retorna perfil DaaS completo do produtor incluindo credencial rural."""
    await asyncio.sleep(random.uniform(0.3, 1.2))

    producer = next((v for v in _PRODUCER_DATABASE.values() if v["holder_did"] == holder_did), None)
    if not producer:
        raise HTTPException(status_code=404, detail=f"DID '{holder_did}' não encontrado")

    vc = _build_vc(holder_did, producer) if producer["cin_verified"] else None

    return ProducerDAASProfile(
        holder_did=holder_did,
        cin_verified=producer["cin_verified"],
        car_linked=producer["car_linked"],
        rural_producer_credential=vc,
        biometric_enrolled=producer["biometric_enrolled"],
        last_verification=datetime.now(UTC).isoformat(),
        trust_level=producer["trust_level"],
    )


@app.post("/api/v1/credentials/issue", response_model=VerifiableCredential)
async def issue_credential(
    holder_did: str,
    credential_type: str = "RuralProducerCredential",
    x_api_key: str = Header(default="mock-key"),
) -> VerifiableCredential:
    """Emite nova credencial verificável (usado no onboarding)."""
    await asyncio.sleep(random.uniform(0.5, 2.0))
    data: dict[str, Any] = {"claims": {"rural_producer": True, "new_enrollment": True}}
    return _build_vc(holder_did, data)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8003, log_level="info")
