"""
AgroTrust AI – report-service: assinatura digital de PDF (PAdES via PyHanko).

Fluxo:
  - DEV:  gera um par chave/certificado self-signed e o persiste como PKCS#12
          (uma vez) em PKCS12_PATH; assina os relatórios com ele.
  - PROD: PKCS12_PATH aponta para um certificado real (idealmente respaldado por
          HSM/KMS). O código de assinatura é o mesmo; muda apenas a origem da chave.

A assinatura embute um dicionário /ByteRange no PDF (CMS/PKCS#7), tornando qualquer
alteração posterior detectável. cryptography (geração do PKCS#12) já é dependência
do core; PyHanko é importado de forma preguiçosa.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

DEV_PKCS12_PASSWORD = os.environ.get("PKCS12_PASSWORD", "agrotrust-dev")
DEFAULT_PKCS12_PATH = str(Path(tempfile.gettempdir()) / "agrotrust_dev_signer.p12")
PKCS12_PATH = os.environ.get("PKCS12_PATH", DEFAULT_PKCS12_PATH)
SIGNER_COMMON_NAME = os.environ.get("SIGNER_CN", "AgroTrust AI – Assinatura de Compliance (DEV)")


def is_signing_available() -> bool:
    """True se o PyHanko estiver instalado (assinatura possível)."""
    try:
        import pyhanko  # noqa: F401
    except ImportError:
        return False
    return True


def ensure_dev_pkcs12(path: str = PKCS12_PATH, password: str = DEV_PKCS12_PASSWORD) -> str:
    """
    Garante a existência de um PKCS#12 self-signed em `path` (gera se ausente).
    Retorna o caminho. Usado apenas em DEV — em PROD o arquivo já existe.
    """
    target = Path(path)
    if target.exists():
        return str(target)

    from datetime import UTC, datetime, timedelta

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "BR"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AgroTrust AI"),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Compliance"),
            x509.NameAttribute(NameOID.COMMON_NAME, SIGNER_COMMON_NAME),
        ]
    )
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=True,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    blob = pkcs12.serialize_key_and_certificates(
        name=b"agrotrust-dev-signer",
        key=key,
        cert=cert,
        cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(password.encode()),
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(blob)
    target.chmod(0o600)
    return str(target)


def load_signer():  # type: ignore[no-untyped-def]  # -> pyhanko SimpleSigner
    """Carrega o SimpleSigner do PKCS#12 (gerando o dev p12 se necessário)."""
    from pyhanko.sign.signers import SimpleSigner

    path = ensure_dev_pkcs12()
    signer = SimpleSigner.load_pkcs12(pfx_file=path, passphrase=DEV_PKCS12_PASSWORD.encode())
    if signer is None:  # pragma: no cover - senha/arquivo inválidos
        raise RuntimeError(f"Falha ao carregar o PKCS#12 do signatário em {path}")
    return signer


def sign_pdf(
    pdf_bytes: bytes,
    reason: str = "Relatório de compliance AgroTrust AI",
    location: str = "Brasil",
    field_name: str = "AgroTrustSignature",
) -> bytes:
    """
    Assina o PDF (PAdES/CMS) e devolve os bytes assinados. Requer PyHanko instalado;
    lança RuntimeError caso contrário (o app decide se cai para PDF não-assinado).
    """
    if not is_signing_available():
        raise RuntimeError("PyHanko não está instalado — assinatura indisponível")

    from io import BytesIO

    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign.signers import PdfSignatureMetadata
    from pyhanko.sign.signers.pdf_signer import PdfSigner

    signer = load_signer()
    writer = IncrementalPdfFileWriter(BytesIO(pdf_bytes))
    meta = PdfSignatureMetadata(
        field_name=field_name,
        reason=reason,
        location=location,
        name="AgroTrust AI Report Service",
    )
    pdf_signer = PdfSigner(meta, signer=signer)
    signed = pdf_signer.sign_pdf(writer)
    return signed.getvalue()


def signer_subject_cn() -> str:
    """Common Name do signatário (para os metadados do relatório)."""
    return SIGNER_COMMON_NAME
