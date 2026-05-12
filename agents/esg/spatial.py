"""
AgroTrust AI – Análise espacial real (Shapely + GeoPandas + pyproj).

Implementa operações topológicas sobre o GeoJSON de desmatamento retornado pelo mock GEE:
  - construção de PropertyPolygon (da resposta GeoJSON ou de centroide+área)
  - reprojeção para SIRGAS 2000 / Brazil Polyconic (EPSG:5641) para cálculo métrico
  - cálculo de área real em hectares, validade topológica, centroide canônico
  - simulação de overlap com buffer de áreas protegidas (APP/RL)

Operações GeoPandas são síncronas/CPU-bound → sempre chame
analyze_deforestation_spatial via asyncio.to_thread() no caller.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import geopandas as gpd
import structlog
from pydantic import BaseModel, Field
from shapely.geometry import MultiPolygon, Polygon, mapping, shape

logger = structlog.get_logger(__name__)

# ─── Constantes de projeção ──────────────────────────────────────────────────

# WGS84 lat/lon — sistema do GeoJSON RFC 7946
_CRS_WGS84 = "EPSG:4326"

# SIRGAS 2000 / Brazil Polyconic — projeção métrica oficial para áreas no Brasil
_CRS_BRAZIL_METRIC = "EPSG:5641"

# 1 grau de latitude ≈ 111.32 km no Brasil (aproximação para fallback from_centroid)
_DEG_LAT_TO_M = 111_320.0


# ─── Modelos de retorno ──────────────────────────────────────────────────────


class SpatialAnalysisResult(BaseModel):
    """Resultado da análise espacial enriquecendo o output do GEE."""
    area_ha_calculated: float = Field(ge=0.0)
    centroid_lat: float
    centroid_lon: float
    polygon_valid: bool
    overlap_with_buffer_ha: float = Field(default=0.0, ge=0.0)
    spatial_confidence: float = Field(ge=0.0, le=1.0)
    crs_used: str = _CRS_BRAZIL_METRIC
    source: str   # "geojson" | "centroid_fallback"


# ─── PropertyPolygon ──────────────────────────────────────────────────────────


@dataclass(slots=True)
class PropertyPolygon:
    """
    Representação da propriedade rural como geometria Shapely + metadados.

    Sempre armazenada em WGS84 (EPSG:4326). Conversões métricas são feitas
    on-demand via GeoPandas em analyze_deforestation_spatial().
    """
    geometry: Polygon | MultiPolygon
    source: str  # "geojson" | "centroid_fallback"

    @classmethod
    def from_centroid(
        cls,
        lat: float,
        lon: float,
        area_ha: float,
    ) -> "PropertyPolygon":
        """
        Gera um quadrado aproximado centrado em (lat, lon) com a área desejada (ha).

        Conversão: 1 ha = 10.000 m² → lado = sqrt(área_m²).
        Conversão grau ↔ metro varia com latitude (cosseno) — usamos o cosseno do centroide.
        """
        if area_ha <= 0:
            raise ValueError(f"area_ha deve ser positivo, recebido {area_ha}")

        side_m = math.sqrt(area_ha * 10_000.0)
        half_side_m = side_m / 2.0

        # Conversão latitude (constante) e longitude (depende da latitude)
        dlat = half_side_m / _DEG_LAT_TO_M
        cos_lat = max(math.cos(math.radians(lat)), 0.01)   # evita /0 nos polos
        dlon = half_side_m / (_DEG_LAT_TO_M * cos_lat)

        poly = Polygon([
            (lon - dlon, lat - dlat),
            (lon + dlon, lat - dlat),
            (lon + dlon, lat + dlat),
            (lon - dlon, lat + dlat),
            (lon - dlon, lat - dlat),
        ])
        return cls(geometry=poly, source="centroid_fallback")

    @classmethod
    def from_geojson(cls, geojson: dict[str, Any]) -> "PropertyPolygon":
        """
        Carrega de um FeatureCollection ou Feature/Polygon GeoJSON.
        Se vier FeatureCollection, faz union dos polígonos em MultiPolygon.
        """
        if not isinstance(geojson, dict):
            raise ValueError("geojson deve ser dict")

        gtype = geojson.get("type")
        if gtype == "FeatureCollection":
            features = geojson.get("features", []) or []
            geoms = [shape(f["geometry"]) for f in features if f.get("geometry")]
            if not geoms:
                raise ValueError("FeatureCollection sem features válidas")
            unified = geoms[0] if len(geoms) == 1 else MultiPolygon(
                [g for g in geoms if isinstance(g, Polygon)]
            )
            return cls(geometry=unified, source="geojson")

        if gtype == "Feature":
            geom = shape(geojson["geometry"])
            return cls(geometry=geom, source="geojson")

        if gtype in {"Polygon", "MultiPolygon"}:
            return cls(geometry=shape(geojson), source="geojson")

        raise ValueError(f"Tipo GeoJSON não suportado: {gtype}")

    def to_geojson(self) -> dict[str, Any]:
        return mapping(self.geometry)  # type: ignore[no-any-return]


# ─── Análise espacial ─────────────────────────────────────────────────────────


def _simulate_protected_buffer_overlap(
    gdf_metric: gpd.GeoDataFrame,
) -> float:
    """
    Simula overlap com buffer de Áreas de Preservação Permanente (APP) ou Reserva Legal (RL).
    Em produção: leitura do shapefile MapBiomas / SFB. Aqui: buffer interno de 5% como proxy.
    """
    geom_m = gdf_metric.geometry.iloc[0]
    if geom_m.is_empty:
        return 0.0
    # Buffer interno = encolhe a geometria em ~5% do "raio" característico
    char_radius_m = math.sqrt(geom_m.area / math.pi)
    inset_m = char_radius_m * 0.05
    eroded = geom_m.buffer(-inset_m) if inset_m > 0 else geom_m
    if eroded.is_empty:
        return 0.0
    overlap_m2 = geom_m.area - eroded.area
    return float(max(0.0, overlap_m2) / 10_000.0)


def analyze_deforestation_spatial(
    polygon: PropertyPolygon,
    reference_year: int = 2008,
) -> SpatialAnalysisResult:
    """
    Executa análise espacial sobre o polígono da propriedade.

    Pipeline:
      1. Constrói GeoDataFrame em WGS84.
      2. Valida topologia (Shapely is_valid).
      3. Reprojeta para EPSG:5641 (métrico) → calcula área em ha.
      4. Calcula centroide em WGS84.
      5. Simula overlap com buffer (proxy de APP/RL).

    Args:
      polygon:        PropertyPolygon (WGS84).
      reference_year: marco do Código Florestal (default 2008) — registrado para auditoria.

    Returns:
      SpatialAnalysisResult com area_ha, centroide, validade e confiança espacial.
    """
    gdf_wgs = gpd.GeoDataFrame({"geometry": [polygon.geometry]}, crs=_CRS_WGS84)
    is_valid = bool(gdf_wgs.geometry.iloc[0].is_valid)

    # Reprojeção para métrico (área correta no Brasil)
    gdf_metric = gdf_wgs.to_crs(_CRS_BRAZIL_METRIC)
    area_m2 = float(gdf_metric.geometry.iloc[0].area)
    area_ha = area_m2 / 10_000.0

    centroid_wgs = gdf_wgs.geometry.iloc[0].centroid
    centroid_lat = float(centroid_wgs.y)
    centroid_lon = float(centroid_wgs.x)

    overlap_ha = _simulate_protected_buffer_overlap(gdf_metric)

    # Confiança espacial: validade topológica × qualidade da geometria
    base_conf = 0.98 if polygon.source == "geojson" else 0.75
    confidence = base_conf if is_valid else max(0.30, base_conf - 0.40)

    logger.info(
        "spatial_analysis_completed",
        source=polygon.source,
        area_ha=round(area_ha, 4),
        polygon_valid=is_valid,
        overlap_buffer_ha=round(overlap_ha, 4),
        reference_year=reference_year,
    )

    return SpatialAnalysisResult(
        area_ha_calculated=round(area_ha, 4),
        centroid_lat=round(centroid_lat, 6),
        centroid_lon=round(centroid_lon, 6),
        polygon_valid=is_valid,
        overlap_with_buffer_ha=round(overlap_ha, 4),
        spatial_confidence=round(confidence, 4),
        source=polygon.source,
    )
