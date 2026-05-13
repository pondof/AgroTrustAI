"""
Tests unitários – agents/esg/spatial.py (Shapely + GeoPandas + pyproj).

Cobre:
  - PropertyPolygon.from_centroid: geometria, validações, área aproximada
  - PropertyPolygon.from_geojson: FeatureCollection, Feature, Polygon, casos inválidos
  - PropertyPolygon.to_geojson: serialização inversa
  - analyze_deforestation_spatial: cálculo de área (EPSG:5641), centroide, overlap
  - SpatialAnalysisResult: campos e ranges (Pydantic)
"""

from __future__ import annotations

import math

import pytest
from shapely.geometry import MultiPolygon, Polygon

from agents.esg.spatial import (
    PropertyPolygon,
    SpatialAnalysisResult,
    analyze_deforestation_spatial,
)

# ─── PropertyPolygon.from_centroid ───────────────────────────────────────────


class TestFromCentroid:
    def test_creates_square_centered_at_lat_lon(self) -> None:
        lat, lon, area_ha = -12.5, -55.3, 100.0
        poly = PropertyPolygon.from_centroid(lat=lat, lon=lon, area_ha=area_ha)

        assert isinstance(poly.geometry, Polygon)
        assert poly.source == "centroid_fallback"

        centroid = poly.geometry.centroid
        assert centroid.x == pytest.approx(lon, abs=1e-3)
        assert centroid.y == pytest.approx(lat, abs=1e-3)

    def test_area_matches_input_approximately(self) -> None:
        """O centroide deve produzir um quadrado com área próxima ao solicitado."""
        area_ha_in = 250.0
        poly = PropertyPolygon.from_centroid(lat=-15.0, lon=-50.0, area_ha=area_ha_in)
        # Calculamos area via analisador (que reprojeta para métrico)
        result = analyze_deforestation_spatial(poly)
        # Aceitamos tolerância de 10% (conversão grau→metro + reprojeção
        # WGS84→SIRGAS Polyconic introduzem distorção métrica conhecida).
        assert result.area_ha_calculated == pytest.approx(area_ha_in, rel=0.10)

    def test_zero_area_raises(self) -> None:
        with pytest.raises(ValueError, match="area_ha deve ser positivo"):
            PropertyPolygon.from_centroid(lat=0.0, lon=0.0, area_ha=0.0)

    def test_negative_area_raises(self) -> None:
        with pytest.raises(ValueError, match="area_ha deve ser positivo"):
            PropertyPolygon.from_centroid(lat=0.0, lon=0.0, area_ha=-10.0)

    def test_polar_latitude_does_not_divide_by_zero(self) -> None:
        """cos(90°)≈0 — fallback clamp evita ZeroDivisionError."""
        poly = PropertyPolygon.from_centroid(lat=89.99, lon=0.0, area_ha=10.0)
        assert poly.geometry.is_valid


# ─── PropertyPolygon.from_geojson ────────────────────────────────────────────


_VALID_FEATURE_COLLECTION = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[-55.3, -12.5], [-55.29, -12.5], [-55.29, -12.49], [-55.3, -12.49], [-55.3, -12.5]]],
            },
            "properties": {"area_ha": 1.0},
        }
    ],
}


class TestFromGeoJSON:
    def test_parses_feature_collection(self) -> None:
        poly = PropertyPolygon.from_geojson(_VALID_FEATURE_COLLECTION)
        assert poly.source == "geojson"
        assert isinstance(poly.geometry, Polygon)

    def test_parses_single_feature(self) -> None:
        feature = _VALID_FEATURE_COLLECTION["features"][0]
        poly = PropertyPolygon.from_geojson(feature)
        assert poly.source == "geojson"
        assert isinstance(poly.geometry, Polygon)

    def test_parses_bare_polygon(self) -> None:
        polygon_geojson = _VALID_FEATURE_COLLECTION["features"][0]["geometry"]
        poly = PropertyPolygon.from_geojson(polygon_geojson)
        assert poly.source == "geojson"
        assert isinstance(poly.geometry, Polygon)

    def test_feature_collection_with_multiple_features_yields_multipolygon(self) -> None:
        fc = {
            "type": "FeatureCollection",
            "features": [
                _VALID_FEATURE_COLLECTION["features"][0],
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [[-55.0, -12.0], [-54.99, -12.0], [-54.99, -11.99], [-55.0, -11.99], [-55.0, -12.0]]
                        ],
                    },
                    "properties": {"area_ha": 1.0},
                },
            ],
        }
        poly = PropertyPolygon.from_geojson(fc)
        assert isinstance(poly.geometry, MultiPolygon)

    def test_rejects_non_dict_input(self) -> None:
        with pytest.raises(ValueError, match="geojson deve ser dict"):
            PropertyPolygon.from_geojson("not a dict")  # type: ignore[arg-type]

    def test_rejects_unknown_type(self) -> None:
        with pytest.raises(ValueError, match="Tipo GeoJSON não suportado"):
            PropertyPolygon.from_geojson({"type": "GeometryCollection", "geometries": []})

    def test_empty_feature_collection_raises(self) -> None:
        with pytest.raises(ValueError, match="sem features válidas"):
            PropertyPolygon.from_geojson({"type": "FeatureCollection", "features": []})


# ─── PropertyPolygon.to_geojson ──────────────────────────────────────────────


class TestToGeoJSON:
    def test_roundtrip_polygon(self) -> None:
        original = PropertyPolygon.from_centroid(lat=-10.0, lon=-50.0, area_ha=50.0)
        gj = original.to_geojson()
        assert gj["type"] == "Polygon"
        assert "coordinates" in gj


# ─── analyze_deforestation_spatial ───────────────────────────────────────────


class TestAnalyzeDeforestationSpatial:
    def test_returns_result_with_required_fields(self) -> None:
        poly = PropertyPolygon.from_centroid(lat=-12.5, lon=-55.3, area_ha=120.0)
        result = analyze_deforestation_spatial(poly)

        assert isinstance(result, SpatialAnalysisResult)
        assert result.area_ha_calculated > 0
        assert -90 <= result.centroid_lat <= 90
        assert -180 <= result.centroid_lon <= 180
        assert result.polygon_valid is True
        assert 0.0 <= result.spatial_confidence <= 1.0
        assert result.crs_used == "EPSG:5641"

    def test_centroid_fallback_lower_confidence_than_geojson(self) -> None:
        poly_fb = PropertyPolygon.from_centroid(lat=-15.0, lon=-47.9, area_ha=200.0)
        poly_gj = PropertyPolygon.from_geojson(_VALID_FEATURE_COLLECTION)

        result_fb = analyze_deforestation_spatial(poly_fb)
        result_gj = analyze_deforestation_spatial(poly_gj)

        assert result_gj.spatial_confidence > result_fb.spatial_confidence
        assert result_fb.source == "centroid_fallback"
        assert result_gj.source == "geojson"

    def test_overlap_with_buffer_is_non_negative(self) -> None:
        poly = PropertyPolygon.from_centroid(lat=-12.5, lon=-55.3, area_ha=100.0)
        result = analyze_deforestation_spatial(poly)
        assert result.overlap_with_buffer_ha >= 0.0
        assert result.overlap_with_buffer_ha <= result.area_ha_calculated

    def test_reference_year_passed_through_logs(self) -> None:
        """reference_year é parâmetro de auditoria — não muda o output mas é aceito."""
        poly = PropertyPolygon.from_centroid(lat=-10.0, lon=-50.0, area_ha=50.0)
        r1 = analyze_deforestation_spatial(poly, reference_year=2008)
        r2 = analyze_deforestation_spatial(poly, reference_year=2020)
        # Resultado idêntico — apenas registrado no log estruturado
        assert r1.area_ha_calculated == r2.area_ha_calculated

    def test_invalid_polygon_reduces_confidence(self) -> None:
        """Polígono auto-intersectante (bowtie) → is_valid=False → confiança menor."""
        bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])
        poly = PropertyPolygon(geometry=bowtie, source="geojson")
        result = analyze_deforestation_spatial(poly)
        # GeoPandas/Shapely tipicamente flagga isso como inválido
        if not result.polygon_valid:
            assert result.spatial_confidence < 0.98


# ─── Tamanho métrico aproximado ──────────────────────────────────────────────


def test_one_hectare_is_10000_m2_via_pipeline() -> None:
    """Sanidade: 1 ha = 10.000 m² → cálculo métrico deve confirmar."""
    poly = PropertyPolygon.from_centroid(lat=-10.0, lon=-50.0, area_ha=1.0)
    result = analyze_deforestation_spatial(poly)
    # área_m² = área_ha * 10_000 → resultado em ha deve voltar ~1.0
    # Tolerância 10% acomoda a distorção da projeção SIRGAS Polyconic.
    assert result.area_ha_calculated == pytest.approx(1.0, rel=0.10)
    assert math.isclose(result.area_ha_calculated, 1.0, rel_tol=0.10)
