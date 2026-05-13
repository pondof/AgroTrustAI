"""
AgroTrust AI – Ferramentas do Agente ESG.

Cada função async chama um mock via httpx.AsyncClient.
Todas têm retry automático com backoff exponencial (tenacity).

detect_deforestation: além de consultar o mock GEE, parseia o GeoJSON retornado
e enriquece o resultado com análise espacial real (Shapely + GeoPandas + pyproj).
"""

from __future__ import annotations

import asyncio

import structlog
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential

from agents.esg.spatial import (
    PropertyPolygon,
    SpatialAnalysisResult,
    analyze_deforestation_spatial,
)
from core.credentials import VCVerifier, build_vc_from_dataprev_payload

logger = structlog.get_logger(__name__)


# ─── Modelos de retorno das ferramentas ──────────────────────────────────────


class CARStatusResult(BaseModel):
    car_number: str
    status: str  # ativo | pendente | cancelado | suspenso
    compliance_status: str  # regular | com_pendencia | irregular
    area_desmatamento_ha: float = Field(default=0.0, ge=0.0)
    area_total_ha: float


class GEEDeforestationResult(BaseModel):
    car_number: str
    deforestation_detected: bool
    deforestation_area_ha: float = Field(default=0.0, ge=0.0)
    gee_images_count: int = Field(default=0, ge=0)
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    biome: str
    # Campo opcional – mantém compatibilidade com chamadores existentes
    spatial_analysis: SpatialAnalysisResult | None = None


class VCCredentialResult(BaseModel):
    holder_did: str
    is_valid: bool
    is_revoked: bool
    chain_of_trust: list[str]
    # Detalhamento da verificação W3C VC (opcional → preserva compatibilidade)
    checks_passed: list[str] = Field(default_factory=list)
    checks_failed: list[str] = Field(default_factory=list)
    verified_at: str | None = None
    issuer: str | None = None
    credential_type: str | None = None


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


def _build_property_polygon(
    geojson_polygons: dict,
    fallback_lat: float,
    fallback_lon: float,
    fallback_area_ha: float,
) -> PropertyPolygon:
    """
    Tenta construir PropertyPolygon do GeoJSON retornado pelo mock GEE.
    Se features estiverem vazias ou inválidas, faz fallback para from_centroid().
    """
    features = (geojson_polygons or {}).get("features") or []
    if features:
        try:
            return PropertyPolygon.from_geojson(geojson_polygons)
        except (ValueError, KeyError, TypeError) as exc:
            logger.warning(
                "spatial_geojson_parse_failed_fallback_to_centroid",
                error=str(exc),
            )
    return PropertyPolygon.from_centroid(
        lat=fallback_lat,
        lon=fallback_lon,
        area_ha=fallback_area_ha,
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
    Detecção de desmatamento via GEE mock + análise espacial real (Shapely/GeoPandas).

    Pipeline:
      1. HTTP GET no mock → resposta com flag de desmatamento + GeoJSON dos polígonos.
      2. Constrói PropertyPolygon (do GeoJSON ou fallback centroide+área).
      3. analyze_deforestation_spatial() em thread (CPU-bound) → SpatialAnalysisResult.
      4. Resultado enriquecido retornado em GEEDeforestationResult.spatial_analysis.

    Args:
      car_number:  identificador da propriedade (chave do mock).
      lat/lon:     centroide para fallback geométrico.
      area_ha:     área declarada (para fallback).
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

    features = (data.get("polygons") or {}).get("features") or []
    images_count = sum(1 for f in features if f.get("properties", {}).get("area_ha", 0) > 0)

    # Análise espacial (CPU-bound → thread pool)
    polygon = _build_property_polygon(
        geojson_polygons=data.get("polygons") or {},
        fallback_lat=lat,
        fallback_lon=lon,
        fallback_area_ha=max(area_ha, 1.0),
    )
    try:
        spatial_result = await asyncio.to_thread(analyze_deforestation_spatial, polygon, 2008)
    except Exception as exc:
        # Tolerância a falhas espaciais: log + segue sem enriquecer
        logger.warning("spatial_analysis_failed", error=str(exc), car_number=car_number)
        spatial_result = None

    return GEEDeforestationResult(
        car_number=car_number,
        deforestation_detected=data["deforestation_detected"],
        deforestation_area_ha=float(data["deforestation_area_ha"]),
        gee_images_count=max(images_count, int(data["deforestation_detected"])),
        confidence_score=float(data.get("confidence_score", 0.95)),
        biome=data.get("biome", ""),
        spatial_analysis=spatial_result,
    )


@_retry
async def verify_vc_credential(
    holder_did: str,
    base_url: str,
    timeout: int = 30,
) -> VCCredentialResult:
    """
    Verifica Credencial Verificável W3C do produtor no Dataprev DaaS mock.

    Pipeline:
      1. HTTP GET no mock Dataprev → payload com claims + verification flags.
      2. build_vc_from_dataprev_payload() → estrutura VerifiableCredential W3C.
      3. VCVerifier().verify() → checa @context, type, issuer, proofValue, expiração.
      4. is_valid = (mock.verified) AND (verifier.valid) AND (not is_revoked).

    A `chain_of_trust` retornada vem da resolução do issuer DID pelo VCVerifier.
    """
    import httpx

    async with httpx.AsyncClient(base_url=base_url, timeout=float(timeout)) as client:
        resp = await client.get(
            f"/api/v1/credentials/{holder_did}/verify",
            headers={"X-Api-Key": "mock-key"},
        )
        resp.raise_for_status()
        data = resp.json()

    vc = build_vc_from_dataprev_payload(data, holder_did)
    verification = VCVerifier().verify(vc)

    is_revoked = bool(data.get("is_revoked", False))
    mock_verified = bool(data.get("verified", False))
    is_valid = verification.valid and mock_verified and not is_revoked

    logger.info(
        "vc_credential_verified",
        holder_did=holder_did[:16] + "…",
        mock_verified=mock_verified,
        revoked=is_revoked,
        w3c_valid=verification.valid,
        is_valid=is_valid,
        checks_passed=len(verification.checks_passed),
        checks_failed=len(verification.checks_failed),
    )

    # Fallback: se o mock devolveu chain_of_trust e o verificador não montou
    # (caso de inválido), preserve a cadeia do mock para debug.
    chain = verification.chain_of_trust or list(data.get("chain_of_trust", []))

    return VCCredentialResult(
        holder_did=holder_did,
        is_valid=is_valid,
        is_revoked=is_revoked,
        chain_of_trust=chain,
        checks_passed=verification.checks_passed,
        checks_failed=verification.checks_failed,
        verified_at=verification.verified_at,
        issuer=vc.issuer,
        credential_type=next(
            (t for t in vc.type if t != "VerifiableCredential"),
            None,
        ),
    )
