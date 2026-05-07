"""
AgroTrust AI – Mock Google Earth Engine Geo API.

Simula a Earth Engine REST/Geo API com séries temporais NDVI, detecção de
desmatamento (PRODES/DETER), classificação de uso do solo e alertas para
propriedades rurais (CARs). Coordenadas válidas de biomas brasileiros.

Referências:
  - Google Earth Engine Python API
  - INPE PRODES/DETER (alertas oficiais de desmatamento)
  - Mapbiomas (classes de uso do solo)
  - Marco do Código Florestal: 22/07/2008
"""
from __future__ import annotations

import asyncio
import hashlib
import random
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(
    title="Mock Google Earth Engine – Geo API",
    description=(
        "Simulação da Earth Engine API para análise espacial de propriedades rurais "
        "(NDVI, desmatamento, uso do solo, alertas PRODES/DETER)."
    ),
    version="1.0.0",
    docs_url="/docs",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

CODIGO_FLORESTAL_BASELINE: str = "2008-07-22"


# ─── Modelos de resposta ──────────────────────────────────────────────────────


class NDVIPoint(BaseModel):
    """Ponto único de série temporal NDVI (mensal)."""

    timestamp: str = Field(description="ISO-8601 (primeiro dia do mês de observação).")
    ndvi_mean: float = Field(ge=-1.0, le=1.0, description="Média mensal do NDVI.")
    ndvi_std: float = Field(ge=0.0, description="Desvio padrão do NDVI no mês.")
    cloud_cover_pct: float = Field(ge=0.0, le=100.0)
    pixel_count: int = Field(ge=0, description="Pixels válidos analisados.")


class NDVITimeSeries(BaseModel):
    car_number: str
    start_date: str
    end_date: str
    satellite_source: str = "Sentinel-2 + Landsat-9 (harmonizado)"
    spatial_resolution_m: int = 10
    series: list[NDVIPoint]
    biome: str
    summary: dict[str, float]


class GeoJSONPolygon(BaseModel):
    """GeoJSON Polygon padrão RFC 7946."""

    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[list[float]]]


class GeoJSONFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: GeoJSONPolygon
    properties: dict[str, Any]


class GeoJSONFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[GeoJSONFeature]


class DeforestationResult(BaseModel):
    car_number: str
    deforestation_detected: bool
    deforestation_area_ha: float = Field(ge=0.0)
    reference_baseline: str = CODIGO_FLORESTAL_BASELINE
    detection_period: str
    polygons: GeoJSONFeatureCollection
    confidence_score: float = Field(ge=0.0, le=1.0)
    biome: str
    analysis_timestamp: str


class LandUseClass(BaseModel):
    class_name: str  # "pastagem" | "agricultura" | "floresta_nativa" | "app" | "reserva_legal" | "outros"
    area_ha: float = Field(ge=0.0)
    percentage: float = Field(ge=0.0, le=100.0)


class LandUseResult(BaseModel):
    car_number: str
    total_area_ha: float
    classes: list[LandUseClass]
    classification_year: int
    source: str = "Mapbiomas Coleção 9 (simulado)"
    biome: str


class DeforestationAlert(BaseModel):
    alert_id: str
    source: Literal["PRODES", "DETER"]
    detected_at: str
    area_ha: float = Field(ge=0.0)
    severity: Literal["low", "medium", "high", "critical"]
    centroid_lat: float
    centroid_lon: float
    status: Literal["active", "investigating", "validated", "dismissed"]


class AlertsResponse(BaseModel):
    car_number: str
    active_alerts: list[DeforestationAlert]
    total_alerts: int
    biome: str


class BatchAnalyzeRequest(BaseModel):
    car_numbers: list[str] = Field(min_length=1, max_length=100)
    analysis_type: Literal["ndvi", "deforestation", "land_use", "alerts"] = "deforestation"


class BatchAnalyzeJobResult(BaseModel):
    car_number: str
    status: Literal["completed", "not_found", "error"]
    summary: dict[str, Any]


class BatchAnalyzeResponse(BaseModel):
    job_id: str
    submitted_at: str
    total_requested: int
    total_processed: int
    results: list[BatchAnalyzeJobResult]


# ─── Base de dados simulada (coordenadas reais de biomas) ─────────────────────


_CAR_GEO_DATABASE: dict[str, dict[str, Any]] = {
    # MT – Cerrado (Sorriso) – Regular
    "MT-5100250-3A4B5C6D7E8F9A0B": {
        "biome": "Cerrado",
        "estado": "MT",
        "centroid": (-12.5450, -55.7117),
        "area_total_ha": 2450.5,
        "deforestation_area_ha": 0.0,
        "land_use": [
            {"class_name": "agricultura", "area_ha": 1715.3},
            {"class_name": "pastagem", "area_ha": 245.0},
            {"class_name": "floresta_nativa", "area_ha": 245.05},
            {"class_name": "app", "area_ha": 245.0},
            {"class_name": "reserva_legal", "area_ha": 0.15},
        ],
        "ndvi_baseline": 0.78,
        "deforestation_polygons": [],
        "alerts": [],
    },
    # RS – Mata Atlântica/Pampa (Cruz Alta) – Regular
    "RS-4300158-1F2E3D4C5B6A7890": {
        "biome": "Pampa",
        "estado": "RS",
        "centroid": (-28.6386, -53.6058),
        "area_total_ha": 380.0,
        "deforestation_area_ha": 0.0,
        "land_use": [
            {"class_name": "agricultura", "area_ha": 266.0},
            {"class_name": "pastagem", "area_ha": 38.0},
            {"class_name": "floresta_nativa", "area_ha": 38.0},
            {"class_name": "app", "area_ha": 38.0},
        ],
        "ndvi_baseline": 0.65,
        "deforestation_polygons": [],
        "alerts": [],
    },
    # PA – Amazônia (Altamira) – Irregular (desmatamento detectado)
    "PA-1500602-DEFOREST00000001": {
        "biome": "Amazônia",
        "estado": "PA",
        "centroid": (-3.2030, -52.2094),
        "area_total_ha": 1200.0,
        "deforestation_area_ha": 87.3,
        "land_use": [
            {"class_name": "pastagem", "area_ha": 612.7},
            {"class_name": "floresta_nativa", "area_ha": 240.0},
            {"class_name": "agricultura", "area_ha": 60.0},
            {"class_name": "app", "area_ha": 200.0},
            {"class_name": "reserva_legal", "area_ha": 0.0},
            {"class_name": "outros", "area_ha": 87.3},
        ],
        "ndvi_baseline": 0.82,
        "deforestation_polygons": [
            [
                [-52.2150, -3.1990],
                [-52.2080, -3.1990],
                [-52.2080, -3.2070],
                [-52.2150, -3.2070],
                [-52.2150, -3.1990],
            ]
        ],
        "alerts": [
            {
                "source": "PRODES",
                "area_ha": 54.2,
                "severity": "critical",
                "status": "validated",
                "days_ago": 45,
            },
            {
                "source": "DETER",
                "area_ha": 33.1,
                "severity": "high",
                "status": "active",
                "days_ago": 12,
            },
        ],
    },
    # GO – Cerrado (Rio Verde) – Pendência menor
    "GO-5201405-PENDENTE00000001": {
        "biome": "Cerrado",
        "estado": "GO",
        "centroid": (-17.7975, -50.9322),
        "area_total_ha": 850.0,
        "deforestation_area_ha": 0.0,
        "land_use": [
            {"class_name": "agricultura", "area_ha": 595.0},
            {"class_name": "pastagem", "area_ha": 85.0},
            {"class_name": "floresta_nativa", "area_ha": 85.0},
            {"class_name": "app", "area_ha": 85.0},
        ],
        "ndvi_baseline": 0.72,
        "deforestation_polygons": [],
        "alerts": [],
    },
    # MS – Cerrado (Dourados) – Cancelado
    "MS-5000203-CANCELADO0000001": {
        "biome": "Cerrado",
        "estado": "MS",
        "centroid": (-22.2231, -54.8056),
        "area_total_ha": 420.0,
        "deforestation_area_ha": 0.0,
        "land_use": [
            {"class_name": "agricultura", "area_ha": 294.0},
            {"class_name": "pastagem", "area_ha": 42.0},
            {"class_name": "floresta_nativa", "area_ha": 42.0},
            {"class_name": "app", "area_ha": 42.0},
        ],
        "ndvi_baseline": 0.70,
        "deforestation_polygons": [],
        "alerts": [],
    },
}


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _seeded_random(car_number: str) -> random.Random:
    """Gera RNG determinístico por CAR para reprodutibilidade dos cenários."""
    seed_int = int(hashlib.sha3_256(car_number.encode()).hexdigest()[:16], 16)
    return random.Random(seed_int)


def _maybe_inject_failure() -> None:
    """4% timeout (504); 2% rate limit (429)."""
    r = random.random()
    if r < 0.04:
        raise HTTPException(status_code=504, detail="Gateway Timeout – Earth Engine indisponível")
    if r < 0.06:
        raise HTTPException(
            status_code=429,
            detail="Rate limit excedido – tente novamente em 60s",
            headers={"Retry-After": "60"},
        )


def _get_property_or_404(car_number: str) -> dict[str, Any]:
    if car_number not in _CAR_GEO_DATABASE:
        raise HTTPException(
            status_code=404,
            detail=f"CAR '{car_number}' sem cobertura GEE indexada",
        )
    return _CAR_GEO_DATABASE[car_number]


def _bbox_polygon(lat: float, lon: float, area_ha: float) -> list[list[list[float]]]:
    """Bounding box aproximado para o CAR (apenas para visualização)."""
    side_deg = (area_ha**0.5) / 1000.0  # ~1 grau ≈ 111km
    half = side_deg / 2.0
    coords = [
        [lon - half, lat - half],
        [lon + half, lat - half],
        [lon + half, lat + half],
        [lon - half, lat + half],
        [lon - half, lat - half],
    ]
    return [coords]


def _build_ndvi_series(
    rng: random.Random,
    baseline: float,
    start: date,
    end: date,
    deforestation_event_offset_months: int | None,
) -> list[NDVIPoint]:
    series: list[NDVIPoint] = []
    cursor = date(start.year, start.month, 1)
    months = 0
    while cursor <= end and months < 240:  # cap 20 anos
        seasonal = 0.08 * (1 if cursor.month in {11, 12, 1, 2, 3} else -0.5)
        noise = rng.uniform(-0.04, 0.04)
        ndvi = baseline + seasonal + noise
        if (
            deforestation_event_offset_months is not None
            and months >= deforestation_event_offset_months
        ):
            ndvi -= 0.35  # queda abrupta após desmatamento
        ndvi = max(-1.0, min(1.0, ndvi))
        series.append(
            NDVIPoint(
                timestamp=cursor.isoformat() + "T00:00:00Z",
                ndvi_mean=round(ndvi, 4),
                ndvi_std=round(rng.uniform(0.02, 0.09), 4),
                cloud_cover_pct=round(rng.uniform(0.0, 25.0), 1),
                pixel_count=rng.randint(2_500, 35_000),
            )
        )
        # avança 1 mês
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)
        months += 1
    return series


# ─── Endpoints ────────────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check leve para liveness/readiness probes."""
    return {"status": "ok", "service": "mock-gee"}


@app.get("/api/v1/ndvi/{car_number}", response_model=NDVITimeSeries)
async def get_ndvi_timeseries(
    car_number: str,
    start_date: str = Query(default="2024-01-01", description="ISO-8601 (YYYY-MM-DD)."),
    end_date: str = Query(default="2026-04-01"),
    x_api_key: str = Header(default="mock-key"),
) -> NDVITimeSeries:
    """
    Retorna série temporal mensal de NDVI (Normalized Difference Vegetation Index)
    derivada de composição Sentinel-2 + Landsat-9 harmonizada (10m).

    Em produção: chama `ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')`.
    """
    await asyncio.sleep(random.uniform(2.0, 8.0))
    _maybe_inject_failure()
    prop = _get_property_or_404(car_number)

    try:
        s = date.fromisoformat(start_date)
        e = date.fromisoformat(end_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Data inválida: {exc}") from exc
    if e < s:
        raise HTTPException(status_code=400, detail="end_date anterior a start_date")

    rng = _seeded_random(car_number)
    deforest_offset: int | None = None
    if prop["deforestation_area_ha"] > 0:
        # injeta queda em ponto aleatório >= 25% da série
        delta_months = max(1, ((e.year - s.year) * 12 + (e.month - s.month)) // 4)
        deforest_offset = delta_months

    series = _build_ndvi_series(rng, prop["ndvi_baseline"], s, e, deforest_offset)
    if not series:
        raise HTTPException(status_code=400, detail="Intervalo gera série vazia")

    ndvi_values = [pt.ndvi_mean for pt in series]
    summary = {
        "ndvi_min": round(min(ndvi_values), 4),
        "ndvi_max": round(max(ndvi_values), 4),
        "ndvi_mean": round(sum(ndvi_values) / len(ndvi_values), 4),
        "points": float(len(series)),
    }

    return NDVITimeSeries(
        car_number=car_number,
        start_date=s.isoformat(),
        end_date=e.isoformat(),
        series=series,
        biome=prop["biome"],
        summary=summary,
    )


@app.get("/api/v1/deforestation/{car_number}", response_model=DeforestationResult)
async def get_deforestation(
    car_number: str,
    x_api_key: str = Header(default="mock-key"),
) -> DeforestationResult:
    """
    Detecção de desmatamento com cruzamento PRODES/DETER e baseline 2008
    (marco Código Florestal). Retorna polígonos GeoJSON RFC 7946.
    """
    await asyncio.sleep(random.uniform(2.5, 7.0))
    _maybe_inject_failure()
    prop = _get_property_or_404(car_number)
    detected = prop["deforestation_area_ha"] > 0

    features: list[GeoJSONFeature] = []
    if detected and prop["deforestation_polygons"]:
        for idx, ring in enumerate(prop["deforestation_polygons"]):
            features.append(
                GeoJSONFeature(
                    geometry=GeoJSONPolygon(coordinates=[ring]),
                    properties={
                        "polygon_id": f"{car_number}-defo-{idx}",
                        "area_ha": prop["deforestation_area_ha"],
                        "detection_year": 2025,
                        "source": "PRODES/DETER cross-reference",
                    },
                )
            )
    else:
        # propriedade regular: bounding box informativo, sem desmatamento
        lat, lon = prop["centroid"]
        features.append(
            GeoJSONFeature(
                geometry=GeoJSONPolygon(
                    coordinates=_bbox_polygon(lat, lon, prop["area_total_ha"])
                ),
                properties={"polygon_id": f"{car_number}-bbox", "area_ha": 0.0},
            )
        )

    return DeforestationResult(
        car_number=car_number,
        deforestation_detected=detected,
        deforestation_area_ha=prop["deforestation_area_ha"],
        detection_period=f"{CODIGO_FLORESTAL_BASELINE}/{date.today().isoformat()}",
        polygons=GeoJSONFeatureCollection(features=features),
        confidence_score=round(random.uniform(0.92, 0.99), 3),
        biome=prop["biome"],
        analysis_timestamp=datetime.now(UTC).isoformat(),
    )


@app.get("/api/v1/land-use/{car_number}", response_model=LandUseResult)
async def get_land_use(
    car_number: str,
    year: int = Query(default=2025, ge=2008, le=2026),
    x_api_key: str = Header(default="mock-key"),
) -> LandUseResult:
    """
    Classificação de uso do solo (pastagem/agricultura/floresta nativa/APP/RL).
    Em produção: cruzamento Mapbiomas + Sentinel-2 supervisionado.
    """
    await asyncio.sleep(random.uniform(2.0, 6.0))
    _maybe_inject_failure()
    prop = _get_property_or_404(car_number)
    total = prop["area_total_ha"]

    classes = [
        LandUseClass(
            class_name=c["class_name"],
            area_ha=c["area_ha"],
            percentage=round((c["area_ha"] / total) * 100.0, 2) if total > 0 else 0.0,
        )
        for c in prop["land_use"]
    ]

    return LandUseResult(
        car_number=car_number,
        total_area_ha=total,
        classes=classes,
        classification_year=year,
        biome=prop["biome"],
    )


@app.get("/api/v1/alerts/{car_number}", response_model=AlertsResponse)
async def get_alerts(
    car_number: str,
    x_api_key: str = Header(default="mock-key"),
) -> AlertsResponse:
    """Alertas PRODES/DETER ativos sobre o polígono do CAR."""
    await asyncio.sleep(random.uniform(2.0, 5.0))
    _maybe_inject_failure()
    prop = _get_property_or_404(car_number)
    rng = _seeded_random(car_number)

    alerts: list[DeforestationAlert] = []
    lat, lon = prop["centroid"]
    for raw in prop["alerts"]:
        alerts.append(
            DeforestationAlert(
                alert_id=f"{raw['source']}-{rng.randint(100000, 999999)}",
                source=raw["source"],
                detected_at=(
                    datetime.now(UTC) - timedelta(days=raw["days_ago"])
                ).isoformat(),
                area_ha=raw["area_ha"],
                severity=raw["severity"],
                centroid_lat=round(lat + rng.uniform(-0.005, 0.005), 6),
                centroid_lon=round(lon + rng.uniform(-0.005, 0.005), 6),
                status=raw["status"],
            )
        )

    return AlertsResponse(
        car_number=car_number,
        active_alerts=alerts,
        total_alerts=len(alerts),
        biome=prop["biome"],
    )


@app.post("/api/v1/batch-analyze", response_model=BatchAnalyzeResponse)
async def batch_analyze(
    request: BatchAnalyzeRequest,
    x_api_key: str = Header(default="mock-key"),
) -> BatchAnalyzeResponse:
    """
    Análise em lote de múltiplos CARs em paralelo (otimização de custo de inferência).

    Trade-off: latência por item maior (1-3s) mas throughput agregado superior
    a chamadas individuais.
    """
    await asyncio.sleep(random.uniform(3.0, 8.0))

    results: list[BatchAnalyzeJobResult] = []
    for car in request.car_numbers:
        if car not in _CAR_GEO_DATABASE:
            results.append(
                BatchAnalyzeJobResult(
                    car_number=car,
                    status="not_found",
                    summary={"reason": "CAR não indexado"},
                )
            )
            continue
        prop = _CAR_GEO_DATABASE[car]
        if request.analysis_type == "deforestation":
            summary: dict[str, Any] = {
                "deforestation_detected": prop["deforestation_area_ha"] > 0,
                "deforestation_area_ha": prop["deforestation_area_ha"],
                "biome": prop["biome"],
            }
        elif request.analysis_type == "land_use":
            summary = {
                "classes": [c["class_name"] for c in prop["land_use"]],
                "biome": prop["biome"],
            }
        elif request.analysis_type == "alerts":
            summary = {"total_alerts": len(prop["alerts"]), "biome": prop["biome"]}
        else:  # ndvi
            summary = {"ndvi_baseline": prop["ndvi_baseline"], "biome": prop["biome"]}

        results.append(
            BatchAnalyzeJobResult(car_number=car, status="completed", summary=summary)
        )

    processed = sum(1 for r in results if r.status == "completed")
    return BatchAnalyzeResponse(
        job_id=f"gee-batch-{hashlib.sha3_256(','.join(request.car_numbers).encode()).hexdigest()[:12]}",
        submitted_at=datetime.now(UTC).isoformat(),
        total_requested=len(request.car_numbers),
        total_processed=processed,
        results=results,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8002, log_level="info")
