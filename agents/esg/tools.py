"""
AgroTrust AI – Ferramentas do Agente ESG.

Cada função async chama um mock via httpx.AsyncClient.
Todas têm retry automático com backoff exponencial (tenacity).
"""
from __future__ import annotations

import structlog
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential

logger = structlog.get_logger(__name__)


# ─── Modelos de retorno das ferramentas ──────────────────────────────────────


class CARStatusResult(BaseModel):
    car_number: str
    status: str                  # ativo | pendente | cancelado | suspenso
    compliance_status: str       # regular | com_pendencia | irregular
    area_desmatamento_ha: float = Field(default=0.0, ge=0.0)
    area_total_ha: float


class GEEDeforestationResult(BaseModel):
    car_number: str
    deforestation_detected: bool
    deforestation_area_ha: float = Field(default=0.0, ge=0.0)
    gee_images_count: int = Field(default=0, ge=0)
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    biome: str


class VCCredentialResult(BaseModel):
    holder_did: str
    is_valid: bool
    is_revoked: bool
    chain_of_trust: list[str]


# ─── Decorador de retry comum ─────────────────────────────────────────────────

_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)


# ─── Ferramentas ──────────────────────────────────────────────────────────────


@_retry
async def fetch_car_status(
    car_number: str,
    base_url: str,
    timeout: int = 30,
) -> CARStatusResult:
    """Consulta status do CAR no SICAR mock."""
    import httpx

    async with httpx.AsyncClient(base_url=base_url, timeout=float(timeout)) as client:
        resp = await client.get(
            f"/api/v1/car/{car_number}",
            headers={"X-Api-Key": "mock-key"},
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info(
            "car_status_fetched",
            car_number=car_number,
            status=data["status"],
            compliance=data["compliance_status"],
        )
        return CARStatusResult(
            car_number=car_number,
            status=data["status"],
            compliance_status=data["compliance_status"],
            area_desmatamento_ha=float(data.get("area_desmatamento_ha", 0.0)),
            area_total_ha=float(data["area_total_ha"]),
        )


@_retry
async def detect_deforestation(
    car_number: str,
    lat: float,
    lon: float,
    area_ha: float,
    base_url: str,
    timeout: int = 30,
) -> GEEDeforestationResult:
    """
    Detecção de desmatamento via GEE mock.
    lat/lon/area_ha são usados pela API real; o mock usa car_number.
    """
    import httpx

    async with httpx.AsyncClient(base_url=base_url, timeout=float(timeout)) as client:
        resp = await client.get(
            f"/api/v1/deforestation/{car_number}",
            headers={"X-Api-Key": "mock-key"},
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info(
            "gee_deforestation_checked",
            car_number=car_number,
            detected=data["deforestation_detected"],
            area_ha=data["deforestation_area_ha"],
        )
        features = data.get("polygons", {}).get("features", [])
        images_count = sum(
            1 for f in features if f.get("properties", {}).get("area_ha", 0) > 0
        )
        return GEEDeforestationResult(
            car_number=car_number,
            deforestation_detected=data["deforestation_detected"],
            deforestation_area_ha=float(data["deforestation_area_ha"]),
            gee_images_count=max(images_count, int(data["deforestation_detected"])),
            confidence_score=float(data.get("confidence_score", 0.95)),
            biome=data.get("biome", ""),
        )


@_retry
async def verify_vc_credential(
    holder_did: str,
    base_url: str,
    timeout: int = 30,
) -> VCCredentialResult:
    """Verifica Credencial Verificável W3C do produtor no Dataprev DaaS mock."""
    import httpx

    async with httpx.AsyncClient(base_url=base_url, timeout=float(timeout)) as client:
        resp = await client.get(
            f"/api/v1/credentials/{holder_did}/verify",
            headers={"X-Api-Key": "mock-key"},
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info(
            "vc_credential_verified",
            holder_did=holder_did[:16] + "…",
            verified=data["verified"],
            revoked=data["is_revoked"],
        )
        return VCCredentialResult(
            holder_did=holder_did,
            is_valid=data["verified"],
            is_revoked=data["is_revoked"],
            chain_of_trust=data.get("chain_of_trust", []),
        )
