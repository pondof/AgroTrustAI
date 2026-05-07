"""
AgroTrust AI – Mock SICAR (Sistema Nacional de Cadastro Ambiental Rural).

Simula a API do SICAR/CAR com payloads realistas, delays variáveis e
cenários de erro pré-programados. Usado para desenvolver e testar o
Agente ESG antes da integração com a API governamental real.

Endpoint oficial (referência): https://www.car.gov.br/publico/municipios/downloads
"""
from __future__ import annotations

import asyncio
import hashlib
import random
from datetime import date, timedelta
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(
    title="Mock SICAR – CAR API",
    description="Simulação da API do Cadastro Ambiental Rural para desenvolvimento AgroTrust AI",
    version="1.0.0",
    docs_url="/docs",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ─── Modelos de resposta ──────────────────────────────────────────────────────

class CARStatus(BaseModel):
    car_number: str
    status: str                   # "ativo" | "pendente" | "cancelado" | "suspenso"
    owner_cpf_hash: str           # SHA-3-256 do CPF real
    municipio: str
    estado: str
    area_total_ha: float
    area_app_ha: float            # Área de Preservação Permanente
    area_reserva_legal_ha: float
    area_desmatamento_ha: float   # Área com desmatamento detectado pós-2008
    registration_date: str
    last_updated: str
    car_certificate_url: str | None
    pending_documents: list[str]
    compliance_status: str        # "regular" | "com_pendencia" | "irregular"


class CARVerificationResult(BaseModel):
    car_number: str
    verified: bool
    verification_timestamp: str
    gee_images_count: int
    deforestation_detected: bool
    deforestation_area_ha: float
    reference_baseline: str = "2008-07-22"   # Marco legal Código Florestal
    confidence_score: float
    satellite_source: str = "Landsat-9 + Sentinel-2 (Google Earth Engine)"
    details: dict[str, Any]


# ─── Dados simulados ──────────────────────────────────────────────────────────

_CAR_DATABASE: dict[str, dict[str, Any]] = {
    "MT-5100250-3A4B5C6D7E8F9A0B": {
        "status": "ativo", "municipio": "Sorriso", "estado": "MT",
        "area_total_ha": 2450.5, "area_app_ha": 245.0, "area_reserva_legal_ha": 735.15,
        "area_desmatamento_ha": 0.0, "compliance_status": "regular",
        "pending_documents": [],
    },
    "RS-4300158-1F2E3D4C5B6A7890": {
        "status": "ativo", "municipio": "Cruz Alta", "estado": "RS",
        "area_total_ha": 380.0, "area_app_ha": 38.0, "area_reserva_legal_ha": 76.0,
        "area_desmatamento_ha": 0.0, "compliance_status": "regular",
        "pending_documents": [],
    },
    "PA-1500602-DEFOREST00000001": {
        "status": "ativo", "municipio": "Altamira", "estado": "PA",
        "area_total_ha": 1200.0, "area_app_ha": 480.0, "area_reserva_legal_ha": 960.0,
        "area_desmatamento_ha": 87.3, "compliance_status": "irregular",
        "pending_documents": ["PRAD", "TAC"],
    },
    "GO-5201405-PENDENTE00000001": {
        "status": "pendente", "municipio": "Rio Verde", "estado": "GO",
        "area_total_ha": 850.0, "area_app_ha": 85.0, "area_reserva_legal_ha": 170.0,
        "area_desmatamento_ha": 0.0, "compliance_status": "com_pendencia",
        "pending_documents": ["Retificação de área", "Análise técnica SEMA"],
    },
    "MS-5000203-CANCELADO0000001": {
        "status": "cancelado", "municipio": "Dourados", "estado": "MS",
        "area_total_ha": 420.0, "area_app_ha": 42.0, "area_reserva_legal_ha": 84.0,
        "area_desmatamento_ha": 0.0, "compliance_status": "irregular",
        "pending_documents": ["Novo cadastro obrigatório"],
    },
}


def _hash_cpf(cpf: str) -> str:
    return hashlib.sha3_256(cpf.encode()).hexdigest()


def _make_car_response(car_number: str, data: dict[str, Any]) -> CARStatus:
    return CARStatus(
        car_number=car_number,
        status=data["status"],
        owner_cpf_hash=_hash_cpf(f"fake-cpf-for-{car_number}"),
        municipio=data["municipio"],
        estado=data["estado"],
        area_total_ha=data["area_total_ha"],
        area_app_ha=data["area_app_ha"],
        area_reserva_legal_ha=data["area_reserva_legal_ha"],
        area_desmatamento_ha=data["area_desmatamento_ha"],
        registration_date=(date.today() - timedelta(days=random.randint(365, 2000))).isoformat(),
        last_updated=(date.today() - timedelta(days=random.randint(1, 90))).isoformat(),
        car_certificate_url=(
            f"https://www.car.gov.br/publico/imoveis/index/{car_number}"
            if data["status"] == "ativo" else None
        ),
        pending_documents=data["pending_documents"],
        compliance_status=data["compliance_status"],
    )


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "mock-sicar"}


@app.get("/api/v1/car/{car_number}", response_model=CARStatus)
async def get_car_status(
    car_number: str,
    x_api_key: str = Header(default="mock-key"),
) -> CARStatus:
    """
    Retorna o status do CAR para o número informado.
    Simula delay de API governamental (200ms – 2s).
    """
    await asyncio.sleep(random.uniform(0.2, 2.0))

    # Simula timeout esporádico (5% das chamadas)
    if random.random() < 0.05:
        raise HTTPException(status_code=504, detail="Gateway Timeout – API SICAR indisponível")

    if car_number not in _CAR_DATABASE:
        raise HTTPException(status_code=404, detail=f"CAR '{car_number}' não encontrado no SICAR")

    return _make_car_response(car_number, _CAR_DATABASE[car_number])


@app.get("/api/v1/car/{car_number}/verify", response_model=CARVerificationResult)
async def verify_car_with_gee(
    car_number: str,
    start_year: int = Query(default=2008, ge=2008, le=2026),
    end_year: int = Query(default=2026, ge=2008, le=2026),
    x_api_key: str = Header(default="mock-key"),
) -> CARVerificationResult:
    """
    Verificação aprofundada com cruzamento de imagens satelitais (simulação GEE).
    Em produção: orquestra chamadas ao Google Earth Engine.
    """
    await asyncio.sleep(random.uniform(1.5, 4.0))   # GEE é mais lento

    if car_number not in _CAR_DATABASE:
        raise HTTPException(status_code=404, detail=f"CAR '{car_number}' não encontrado")

    data = _CAR_DATABASE[car_number]
    deforested = data["area_desmatamento_ha"] > 0

    return CARVerificationResult(
        car_number=car_number,
        verified=True,
        verification_timestamp=date.today().isoformat() + "T00:00:00Z",
        gee_images_count=random.randint(12, 48),
        deforestation_detected=deforested,
        deforestation_area_ha=data["area_desmatamento_ha"],
        confidence_score=round(random.uniform(0.91, 0.99), 3),
        details={
            "ndvi_change_detected": deforested,
            "cloud_cover_pct": round(random.uniform(0, 15), 1),
            "temporal_resolution_days": 16,
            "spatial_resolution_m": 10,
            "analysis_period": f"{start_year}-{end_year}",
        },
    )


@app.get("/api/v1/car", response_model=list[str])
async def search_car_by_municipio(
    municipio: str = Query(...),
    estado: str = Query(...),
) -> list[str]:
    """Busca números CAR por município."""
    await asyncio.sleep(random.uniform(0.3, 1.0))
    return [
        car for car, data in _CAR_DATABASE.items()
        if data["municipio"].lower() == municipio.lower()
        and data["estado"].upper() == estado.upper()
    ]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="info")
