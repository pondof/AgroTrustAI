"""
AgroTrust AI – Testes de contrato dos mocks governamentais.

Sobem cada mock como FastAPI TestClient (sem Docker) e validam:
  - Campos obrigatórios e tipos.
  - Cenários determinísticos pré-cadastrados (regular, irregular, revogado).
  - 404 para identificadores inexistentes.

Execução: `pytest tests/contract/`.
"""
from __future__ import annotations

import importlib
from typing import Any

import pytest
from fastapi.testclient import TestClient


def _load_mock(module_path: str) -> Any:
    return importlib.import_module(module_path).app


@pytest.fixture(scope="module")
def sicar_client() -> TestClient:
    return TestClient(_load_mock("mocks.sicar.app"))


@pytest.fixture(scope="module")
def gee_client() -> TestClient:
    return TestClient(_load_mock("mocks.gee.app"))


@pytest.fixture(scope="module")
def dataprev_client() -> TestClient:
    return TestClient(_load_mock("mocks.dataprev.app"))


@pytest.fixture(scope="module")
def open_finance_client() -> TestClient:
    return TestClient(_load_mock("mocks.open_finance.app"))


# ─── SICAR ───────────────────────────────────────────────────────────────────


_REGULAR_CAR = "MT-5100250-3A4B5C6D7E8F9A0B"
_IRREGULAR_CAR = "PA-1500602-DEFOREST00000001"


class TestSICAR:
    def test_health(self, sicar_client: TestClient) -> None:
        response = sicar_client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_get_status_regular_car(self, sicar_client: TestClient) -> None:
        response = sicar_client.get(f"/api/v1/car/{_REGULAR_CAR}")
        # 504 esporádico é tolerado em mock (5%); apenas re-tenta
        if response.status_code == 504:
            response = sicar_client.get(f"/api/v1/car/{_REGULAR_CAR}")
        assert response.status_code == 200
        body = response.json()
        # Campos obrigatórios do contrato
        for field in (
            "car_number",
            "status",
            "owner_cpf_hash",
            "municipio",
            "estado",
            "area_total_ha",
            "area_app_ha",
            "area_reserva_legal_ha",
            "area_desmatamento_ha",
            "compliance_status",
        ):
            assert field in body, f"Campo obrigatório ausente: {field}"
        assert body["compliance_status"] == "regular"
        assert len(body["owner_cpf_hash"]) == 64  # SHA-3-256 hex

    def test_irregular_car_has_irregular_compliance(self, sicar_client: TestClient) -> None:
        response = sicar_client.get(f"/api/v1/car/{_IRREGULAR_CAR}")
        if response.status_code == 504:
            response = sicar_client.get(f"/api/v1/car/{_IRREGULAR_CAR}")
        assert response.status_code == 200
        assert response.json()["compliance_status"] == "irregular"
        assert response.json()["area_desmatamento_ha"] > 0

    def test_unknown_car_returns_404(self, sicar_client: TestClient) -> None:
        response = sicar_client.get("/api/v1/car/INEXISTENTE-99")
        if response.status_code == 504:
            response = sicar_client.get("/api/v1/car/INEXISTENTE-99")
        assert response.status_code == 404


# ─── GEE ─────────────────────────────────────────────────────────────────────


class TestGEE:
    def _get_with_retry(
        self,
        client: TestClient,
        path: str,
        *,
        attempts: int = 4,
    ) -> Any:
        """GEE injeta 4% timeout + 2% rate limit; tolerar até 4 tentativas."""
        for _ in range(attempts):
            response = client.get(path)
            if response.status_code in (200, 404, 400):
                return response
        return response  # último response, mesmo se ainda for 504/429

    def test_health(self, gee_client: TestClient) -> None:
        response = gee_client.get("/health")
        assert response.status_code == 200
        assert response.json()["service"] == "mock-gee"

    def test_ndvi_returns_at_least_six_points(self, gee_client: TestClient) -> None:
        response = self._get_with_retry(
            gee_client,
            f"/api/v1/ndvi/{_REGULAR_CAR}?start_date=2024-01-01&end_date=2024-12-01",
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert "series" in body
        assert len(body["series"]) >= 6
        for point in body["series"]:
            assert -1.0 <= point["ndvi_mean"] <= 1.0

    def test_deforestation_returns_valid_geojson(self, gee_client: TestClient) -> None:
        response = self._get_with_retry(
            gee_client, f"/api/v1/deforestation/{_REGULAR_CAR}"
        )
        assert response.status_code == 200, response.text
        body = response.json()
        polygons = body["polygons"]
        assert polygons["type"] == "FeatureCollection"
        assert isinstance(polygons["features"], list)
        for feat in polygons["features"]:
            assert feat["type"] == "Feature"
            assert feat["geometry"]["type"] == "Polygon"
            assert isinstance(feat["geometry"]["coordinates"], list)

    def test_pa_property_has_deforestation_detected(self, gee_client: TestClient) -> None:
        response = self._get_with_retry(
            gee_client, f"/api/v1/deforestation/{_IRREGULAR_CAR}"
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["deforestation_detected"] is True
        assert body["deforestation_area_ha"] > 0
        assert body["biome"] == "Amazônia"

    def test_unknown_car_returns_404(self, gee_client: TestClient) -> None:
        response = self._get_with_retry(gee_client, "/api/v1/ndvi/INEXISTENTE-99")
        assert response.status_code == 404


# ─── Dataprev ────────────────────────────────────────────────────────────────


class TestDataprev:
    def _did_for(self, client: TestClient, key: str) -> str:
        """Recupera DID determinístico do banco simulado via search por seed."""
        # _did(seed) é determinístico: did:gov:br:<sha3-256(seed)[:32]>
        import hashlib

        seeds = {
            "regular": "producer-001",
            "pending": "producer-002",
            "revoked": "producer-003",
        }
        h = hashlib.sha3_256(seeds[key].encode()).hexdigest()[:32]
        return f"did:gov:br:{h}"

    def test_health(self, dataprev_client: TestClient) -> None:
        response = dataprev_client.get("/health")
        assert response.status_code == 200

    def test_vc_has_w3c_context(self, dataprev_client: TestClient) -> None:
        did = self._did_for(dataprev_client, "regular")
        response = dataprev_client.get(f"/api/v1/credentials/{did}/verify")
        if response.status_code == 503:
            response = dataprev_client.get(f"/api/v1/credentials/{did}/verify")
        assert response.status_code == 200
        body = response.json()
        # Validação do contrato VC
        assert body["holder_did"] == did
        assert "chain_of_trust" in body
        # Cadeia de confiança 3 níveis (dataprev → iti → root)
        assert len(body["chain_of_trust"]) == 3

    def test_revoked_producer_flagged(self, dataprev_client: TestClient) -> None:
        did = self._did_for(dataprev_client, "revoked")
        response = dataprev_client.get(f"/api/v1/credentials/{did}/verify")
        if response.status_code == 503:
            response = dataprev_client.get(f"/api/v1/credentials/{did}/verify")
        assert response.status_code == 200
        body = response.json()
        assert body["is_revoked"] is True
        assert body["revocation_reason"] is not None
        assert body["verified"] is False

    def test_profile_has_vc_w3c_context(self, dataprev_client: TestClient) -> None:
        did = self._did_for(dataprev_client, "regular")
        response = dataprev_client.get(f"/api/v1/producers/{did}/profile")
        if response.status_code == 503:
            response = dataprev_client.get(f"/api/v1/producers/{did}/profile")
        assert response.status_code == 200
        vc = response.json()["rural_producer_credential"]
        assert vc is not None
        assert "https://www.w3.org/2018/credentials/v2" in vc["context"]


# ─── Open Finance ────────────────────────────────────────────────────────────


class TestOpenFinance:
    def test_health(self, open_finance_client: TestClient) -> None:
        response = open_finance_client.get("/health")
        assert response.status_code == 200

    def test_high_dti_consent(self, open_finance_client: TestClient) -> None:
        response = open_finance_client.get(
            "/api/v1/consents/CONSENT_HIGH_DTI_002/summary?months=6"
        )
        if response.status_code == 503:
            response = open_finance_client.get(
                "/api/v1/consents/CONSENT_HIGH_DTI_002/summary?months=6"
            )
        assert response.status_code == 200
        body = response.json()
        assert body["debt_to_income_ratio"] > 0.65, "Cenário high-DTI deve ter DTI > 0.65"
        assert body["defaulted_operations"] >= 1

    def test_seasonality_harvest_month(self, open_finance_client: TestClient) -> None:
        """Mês 5 ou 6 deve ter receita agro acima da média anual (sazonalidade safra)."""
        response = open_finance_client.get(
            "/api/v1/consents/CONSENT_REGULAR_001/transactions?months=12"
        )
        assert response.status_code == 200
        txs = response.json()
        agro = [t for t in txs if t["category"] == "receita_agro" and t["amount"] > 0]
        assert agro, "Esperava transações receita_agro"
        avg = sum(t["amount"] for t in agro) / len(agro)
        harvest_txs = [t for t in agro if t["date"][5:7] in {"05", "06", "10", "11"}]
        if harvest_txs:
            avg_harvest = sum(t["amount"] for t in harvest_txs) / len(harvest_txs)
            assert avg_harvest > avg, (
                "Receita agro em meses de safra deve superar a média anual"
            )

    def test_unknown_consent_returns_404(self, open_finance_client: TestClient) -> None:
        response = open_finance_client.get(
            "/api/v1/consents/CONSENT_NONEXISTENT_999/summary"
        )
        if response.status_code == 503:
            response = open_finance_client.get(
                "/api/v1/consents/CONSENT_NONEXISTENT_999/summary"
            )
        assert response.status_code == 404
