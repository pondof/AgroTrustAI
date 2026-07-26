"""
Testes do gerador de PDF do report-service.

Estratégia:
  - A renderização Jinja2 (render_html) e o bloqueio de rede não dependem do
    WeasyPrint e rodam sempre.
  - A conversão HTML→PDF exige WeasyPrint (dependência de sistema pesada); esses
    testes usam pytest.importorskip e são pulados quando ela não está instalada.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

# Diretório do serviço (com hífen) na frente do path para importar os módulos irmãos.
_SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_DIR))

import generator  # noqa: E402


def _mock_context() -> dict[str, Any]:
    return {
        "dossie": {
            "id": "DOS-ABC123",
            "tenant_id": "coop-demo",
            "status": "approved",
            "verdict": "approved",
            "car_number": "MT-5107602-XYZ",
            "cpf_hash_masked": "a3f5b8c2***",
            "credit_amount_brl": 120000.0,
            "approved_amount_brl": 100000.0,
            "credit_purpose": "custeio",
            "property_area_ha": 300.0,
            "requested_by": "analista@agrotrust.ai",
            "created_at": "2026-07-23T10:00:00+00:00",
            "rejection_reasons": [],
        },
        "scores": {"esg": 720, "financial": 810, "security": 655, "composite": 762},
        "agents": [
            {
                "key": "esg",
                "title": "ESG / Socioambiental",
                "score": 720,
                "decision": "approved",
                "confidence": 0.92,
                "factors": [
                    {"name": "CAR regular", "weight": 0.4, "value": "regular", "impact": "positive"},
                    {"name": "Desmatamento", "weight": 0.35, "value": "0 ha", "impact": 0.8},
                ],
            },
            {
                "key": "financial",
                "title": "Financeiro",
                "score": 810,
                "decision": "approved",
                "confidence": None,
                "factors": [{"name": "DTI", "weight": 0.5, "value": "0.42", "impact": -0.2}],
            },
            {
                "key": "security",
                "title": "Segurança / Identidade",
                "score": 655,
                "decision": "approved",
                "confidence": 0.88,
                "factors": [],
            },
        ],
        "audit": [
            {
                "event_type": "subscription.initiated",
                "timestamp": "2026-07-23T10:00:00+00:00",
                "subject": "analista@agrotrust.ai",
                "outcome": "success",
                "entry_hash": "abcdef0123456789" * 4,
                "entry_hash_short": "abcdef012345…",
                "details": {"car_number": "MT-5107602-XYZ"},
            }
        ],
        "legal_references": [("LGPD – Art. 20", "Revisão de decisões automatizadas.")],
        "meta": {
            "report_id": "RPT-DEADBEEF",
            "generated_at": "23/07/2026 10:05:00 UTC",
            "generated_by": "analista@agrotrust.ai",
            "chain_head_hash": "abcdef0123456789" * 4,
            "audit_entries": 1,
            "signed": False,
            "signer_subject": None,
        },
    }


def test_render_compliance_html_contains_key_sections() -> None:
    html = generator.render_html(generator.COMPLIANCE_TEMPLATE, _mock_context())
    assert "AgroTrust" in html
    assert "DOS-ABC123" in html
    assert "Fundamento Legal" in html
    assert "LGPD" in html
    # Nunca vaza CPF em claro — apenas o hash mascarado.
    assert "a3f5b8c2***" in html


def test_render_audit_html_lists_entries() -> None:
    html = generator.render_html(generator.AUDIT_TEMPLATE, _mock_context())
    assert "subscription.initiated" in html
    assert "Trilha de Auditoria" in html


def test_no_network_fetcher_blocks_external_resources() -> None:
    with pytest.raises(ValueError, match="bloqueado"):
        generator._no_network_url_fetcher("https://example.com/logo.png")
    with pytest.raises(ValueError, match="bloqueado"):
        generator._no_network_url_fetcher("file:///etc/passwd")


def test_generate_compliance_pdf_is_valid_pdf() -> None:
    pytest.importorskip("weasyprint")
    pdf = generator.generate_compliance_pdf(_mock_context())
    assert isinstance(pdf, bytes)
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 1000


def test_generate_audit_pdf_is_valid_pdf() -> None:
    pytest.importorskip("weasyprint")
    pdf = generator.generate_audit_pdf(_mock_context())
    assert isinstance(pdf, bytes)
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 1000
