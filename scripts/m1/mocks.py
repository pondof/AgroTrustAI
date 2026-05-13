"""
AgroTrust AI – Setup de mocks HTTP (respx) para validação M1.

Cada cenário registra 4 rotas: SICAR (porta 8001), GEE (8002), Dataprev (8003)
e Open Finance (8004). As respostas são construídas a partir do M1Scenario para
manter coerência entre payload retornado e veredicto esperado.

Apenas HTTP é mockado — as ferramentas do SecurityGuardAgent (liveness, deepfake,
blockchain) são funções determinísticas in-process e respondem aos keywords em
session_id/media_url já embutidos pelos generators de cenário.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

import respx
from httpx import Response

from scripts.m1.scenarios import M1Scenario


def _sicar_payload(s: M1Scenario) -> dict[str, Any]:
    return {
        "car_number": s.car_number,
        "status": s.car_status,
        "owner_cpf_hash": s.cpf_hash,
        "municipio": s.location_municipio,
        "estado": s.location_estado,
        "area_total_ha": s.car_area_total_ha,
        "area_app_ha": round(s.car_area_total_ha * 0.10, 2),
        "area_reserva_legal_ha": round(s.car_area_total_ha * 0.20, 2),
        "area_desmatamento_ha": s.car_area_desmatamento_ha,
        "compliance_status": s.car_compliance,
        "pending_documents": [] if s.car_status == "ativo" else ["PRAD", "TAC"],
    }


def _gee_payload(s: M1Scenario) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    if s.gee_deforestation_detected:
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [s.location_lon, s.location_lat],
                            [s.location_lon + 0.01, s.location_lat],
                            [s.location_lon + 0.01, s.location_lat + 0.01],
                            [s.location_lon, s.location_lat + 0.01],
                            [s.location_lon, s.location_lat],
                        ]
                    ],
                },
                "properties": {"area_ha": s.gee_deforestation_area_ha},
            }
        )
    return {
        "car_number": s.car_number,
        "deforestation_detected": s.gee_deforestation_detected,
        "deforestation_area_ha": s.gee_deforestation_area_ha,
        "confidence_score": s.gee_confidence,
        "biome": s.gee_biome,
        "polygons": {"type": "FeatureCollection", "features": features},
    }


def _dataprev_payload(s: M1Scenario) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    cred_id = hashlib.sha3_256(s.holder_did.encode()).hexdigest()[:32]
    return {
        "credential_id": cred_id,
        "holder_did": s.holder_did,
        "verified": s.vc_verified,
        "verification_method": "Ed25519Signature2020",
        "verification_timestamp": now,
        "credential_type": s.vc_credential_type,
        "issuer": "did:gov:br:dataprev:mgi",
        "is_revoked": s.vc_is_revoked,
        "revocation_reason": "Suspeita de fraude" if s.vc_is_revoked else None,
        "claims": {
            "name_hash": hashlib.sha3_256(s.cpf_hash.encode()).hexdigest(),
            "cpf_hash": s.cpf_hash,
            "rural_producer_registry_id": cred_id,
        },
        "signature_valid": True,
        "chain_of_trust": [
            "did:gov:br:dataprev:mgi",
            "did:gov:br:iti",
            "did:gov:br:root",
        ],
    }


def _open_finance_payload(s: M1Scenario) -> dict[str, Any]:
    return {
        "consent_id": s.consent_id,
        "cpf_hash": s.cpf_hash,
        "months_of_history": s.of_months_history,
        "total_accounts": 3,
        "total_balance_brl": round(s.of_monthly_revenue_brl * 1.5, 2),
        "avg_monthly_revenue_brl": s.of_monthly_revenue_brl,
        "avg_monthly_expenses_brl": round(s.of_monthly_revenue_brl * 0.65, 2),
        "avg_monthly_agro_revenue_brl": round(s.of_monthly_revenue_brl * 0.85, 2),
        "debt_to_income_ratio": s.of_dti,
        "rural_credit_operations": [],
        "total_rural_credit_brl": s.of_total_rural_credit_brl,
        "defaulted_operations": s.of_defaulted_operations,
        "data_quality_score": s.of_data_quality,
    }


def register_mocks(router: respx.MockRouter, scenarios: list[M1Scenario]) -> None:
    """Registra rotas HTTP para todos os cenários no router fornecido."""
    for s in scenarios:
        router.get(f"http://localhost:8001/api/v1/car/{s.car_number}").mock(
            return_value=Response(200, json=_sicar_payload(s))
        )
        router.get(f"http://localhost:8002/api/v1/deforestation/{s.car_number}").mock(
            return_value=Response(200, json=_gee_payload(s))
        )
        router.get(f"http://localhost:8003/api/v1/credentials/{s.holder_did}/verify").mock(
            return_value=Response(200, json=_dataprev_payload(s))
        )
        router.get(f"http://localhost:8004/api/v1/consents/{s.consent_id}/summary").mock(
            return_value=Response(200, json=_open_finance_payload(s))
        )
