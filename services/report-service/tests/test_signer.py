"""
Testes do assinador de PDF do report-service.

  - Geração do PKCS#12 dev e checagem de disponibilidade usam apenas `cryptography`
    (dependência do core) e rodam sempre.
  - A assinatura efetiva do PDF exige PyHanko + WeasyPrint (para produzir o PDF de
    entrada); esses testes usam importorskip e são pulados quando ausentes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_DIR))

import generator  # noqa: E402
import signer  # noqa: E402


def test_ensure_dev_pkcs12_creates_valid_p12(tmp_path: Path) -> None:
    from cryptography.hazmat.primitives.serialization import pkcs12

    p12_path = tmp_path / "dev_signer.p12"
    result = signer.ensure_dev_pkcs12(str(p12_path), "test-pass")
    assert Path(result).exists()

    blob = p12_path.read_bytes()
    key, cert, _ = pkcs12.load_key_and_certificates(blob, b"test-pass")
    assert key is not None
    assert cert is not None
    assert "AgroTrust" in cert.subject.rfc4514_string()


def test_ensure_dev_pkcs12_is_idempotent(tmp_path: Path) -> None:
    p12_path = tmp_path / "dev_signer.p12"
    signer.ensure_dev_pkcs12(str(p12_path), "pw")
    first = p12_path.read_bytes()
    signer.ensure_dev_pkcs12(str(p12_path), "pw")  # não regenera
    assert p12_path.read_bytes() == first


def test_is_signing_available_reflects_pyhanko_import() -> None:
    try:
        import pyhanko  # noqa: F401

        expected = True
    except ImportError:
        expected = False
    assert signer.is_signing_available() is expected


def test_sign_pdf_produces_signed_pdf_with_byterange(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("pyhanko")
    pytest.importorskip("weasyprint")

    # Usa um PKCS#12 dev isolado no tmp para não depender do estado global.
    p12_path = tmp_path / "signer.p12"
    monkeypatch.setattr(signer, "PKCS12_PATH", str(p12_path))
    monkeypatch.setattr(signer, "DEV_PKCS12_PASSWORD", "pw")

    pdf = generator.generate_compliance_pdf(
        {
            "dossie": {"id": "DOS-1", "tenant_id": "t", "status": "approved", "verdict": "approved",
                       "car_number": "C", "cpf_hash_masked": "ab***", "credit_amount_brl": 1.0,
                       "approved_amount_brl": 1.0, "credit_purpose": "custeio", "property_area_ha": 1.0,
                       "requested_by": "x", "created_at": None, "rejection_reasons": []},
            "scores": {"esg": 700, "financial": 700, "security": 700, "composite": 700},
            "agents": [], "audit": [], "legal_references": [],
            "meta": {"report_id": "RPT-1", "generated_at": "now", "generated_by": "x",
                     "chain_head_hash": "", "audit_entries": 0, "signed": False, "signer_subject": None},
        }
    )
    signed = signer.sign_pdf(pdf)
    assert signed[:5] == b"%PDF-"
    assert b"/ByteRange" in signed
    assert len(signed) > len(pdf)
