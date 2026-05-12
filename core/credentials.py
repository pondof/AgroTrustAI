"""
AgroTrust AI – W3C Verifiable Credentials (DIF) com verificação criptográfica Ed25519.

Especificação:
  - W3C VC Data Model 1.1 (https://www.w3.org/TR/vc-data-model/)
  - Proof Suite: Ed25519Signature2020 (ed25519-cosmos / DIF)
  - Encoding de proofValue: base64url sem padding (RFC 7515 §2)

Como não temos a API Dataprev real assinando as credenciais, a verificação
criptográfica aqui valida:
  (a) @context contém o contexto W3C VC v1
  (b) type inclui "VerifiableCredential"
  (c) issuer é DID do gov.br ("did:gov:br:…")
  (d) credential não expirou (expirationDate > now, se presente)
  (e) proofValue é base64url decodificável com pelo menos 32 bytes
      (tamanho mínimo de assinatura Ed25519 = 64 bytes; 32 = entrada didática)
  (f) proof.verificationMethod referencia o issuer DID

Em produção: substituir _verify_proof_value() por nacl.signing.VerifyKey.verify()
com chave pública obtida via DID Resolution (did:web ou did:key).
"""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# ─── Constantes W3C ───────────────────────────────────────────────────────────

VC_CONTEXT_V1 = "https://www.w3.org/2018/credentials/v1"
DID_GOV_BR_PREFIX = "did:gov:br:"
MIN_PROOF_BYTES = 32              # didático – Ed25519 real são 64 bytes
ED25519_PROOF_TYPE = "Ed25519Signature2020"


# ─── Dataclasses W3C VC ──────────────────────────────────────────────────────


@dataclass(slots=True)
class VCProof:
    """W3C VC Proof (assinatura criptográfica)."""
    type: str
    created: str                # ISO-8601
    verificationMethod: str     # DID URL apontando para a chave pública
    proofValue: str             # base64url sem padding

    # Campo opcional para extensões (proofPurpose, domain, challenge…)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class VerifiableCredential:
    """W3C VC v1.1."""
    context: list[str]                       # @context – lista de URIs
    type: list[str]
    issuer: str                              # DID do emissor
    issuanceDate: str                        # ISO-8601
    credentialSubject: dict[str, Any]
    proof: VCProof
    expirationDate: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialização canônica para JSON-LD."""
        d: dict[str, Any] = {
            "@context": list(self.context),
            "type": list(self.type),
            "issuer": self.issuer,
            "issuanceDate": self.issuanceDate,
            "credentialSubject": dict(self.credentialSubject),
            "proof": {
                "type": self.proof.type,
                "created": self.proof.created,
                "verificationMethod": self.proof.verificationMethod,
                "proofValue": self.proof.proofValue,
                **dict(self.proof.extra),
            },
        }
        if self.expirationDate:
            d["expirationDate"] = self.expirationDate
        return d


@dataclass(slots=True)
class VCVerificationResult:
    valid: bool
    checks_passed: list[str]
    checks_failed: list[str]
    verified_at: str            # ISO-8601 UTC
    chain_of_trust: list[str]   # ex: ["Dataprev", "Gov.br", "ITI"]


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _b64url_decode(s: str) -> bytes:
    """Decode base64url tolerando ausência de padding."""
    if not isinstance(s, str) or not s:
        raise ValueError("proofValue vazio")
    padding_needed = (-len(s)) % 4
    return base64.urlsafe_b64decode(s + ("=" * padding_needed))


def _parse_iso(ts: str) -> datetime:
    """ISO-8601 parser que aceita 'Z' (UTC)."""
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


# ─── Verificador ──────────────────────────────────────────────────────────────


class VCVerifier:
    """
    Executa as verificações estruturais W3C VC + checks específicos AgroTrust.
    Não levanta exceções: acumula todas as falhas em checks_failed.
    """

    def verify(self, vc: VerifiableCredential) -> VCVerificationResult:
        passed: list[str] = []
        failed: list[str] = []

        # (a) Contexto W3C VC v1
        if VC_CONTEXT_V1 in (vc.context or []):
            passed.append("context_w3c_vc_v1")
        else:
            failed.append("context_missing_w3c_vc_v1")

        # (b) Tipo inclui VerifiableCredential
        if "VerifiableCredential" in (vc.type or []):
            passed.append("type_includes_verifiable_credential")
        else:
            failed.append("type_missing_verifiable_credential")

        # (c) Issuer é DID do gov.br
        if isinstance(vc.issuer, str) and vc.issuer.startswith(DID_GOV_BR_PREFIX):
            passed.append("issuer_gov_br_did")
        else:
            failed.append("issuer_not_gov_br_did")

        # (d) Não expirado
        if vc.expirationDate:
            try:
                exp_dt = _parse_iso(vc.expirationDate)
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=UTC)
                if exp_dt > datetime.now(UTC):
                    passed.append("not_expired")
                else:
                    failed.append("credential_expired")
            except ValueError:
                failed.append("expirationDate_unparseable")
        else:
            passed.append("no_expiration_date")

        # (e) proofValue decodificável e tamanho mínimo
        try:
            raw = _b64url_decode(vc.proof.proofValue)
            if len(raw) >= MIN_PROOF_BYTES:
                passed.append("proof_value_valid_base64url")
            else:
                failed.append(f"proof_value_too_short_{len(raw)}_bytes")
        except (ValueError, binascii.Error) as exc:
            failed.append(f"proof_value_decode_failed_{type(exc).__name__}")

        # (f) verificationMethod referencia o issuer DID
        vm = vc.proof.verificationMethod or ""
        if vm.startswith(vc.issuer):
            passed.append("verification_method_matches_issuer")
        else:
            failed.append("verification_method_does_not_match_issuer")

        valid = not failed

        chain = self._build_chain_of_trust(vc.issuer) if valid else []

        logger.info(
            "vc_verified",
            issuer=vc.issuer,
            valid=valid,
            passed_count=len(passed),
            failed_count=len(failed),
        )

        return VCVerificationResult(
            valid=valid,
            checks_passed=passed,
            checks_failed=failed,
            verified_at=datetime.now(UTC).isoformat(),
            chain_of_trust=chain,
        )

    def _build_chain_of_trust(self, issuer_did: str) -> list[str]:
        """
        Resolve a cadeia de confiança a partir do DID do emissor.
        Em produção: DID Resolution (did:web) → /.well-known/did.json com trust anchors.
        """
        if "dataprev" in issuer_did:
            return ["Dataprev", "Gov.br", "ITI"]
        if issuer_did.startswith(DID_GOV_BR_PREFIX):
            return ["Gov.br", "ITI"]
        return ["unknown"]


# ─── Builder para integrar com mocks Dataprev ─────────────────────────────────


def build_vc_from_dataprev_payload(
    payload: dict[str, Any],
    holder_did: str,
) -> VerifiableCredential:
    """
    Constrói VerifiableCredential a partir do JSON retornado pelo mock Dataprev.

    O mock retorna:
      credential_id, holder_did, verified, verification_method,
      verification_timestamp, credential_type, issuer, is_revoked,
      revocation_reason, claims, signature_valid, chain_of_trust

    Mapeamos para a estrutura W3C VC. Para o proofValue (que o mock não retorna)
    sintetizamos uma assinatura determinística a partir do credential_id.
    """
    issuer = payload.get("issuer") or "did:gov:br:dataprev"
    issuance_date = (
        payload.get("verification_timestamp")
        or datetime.now(UTC).isoformat()
    )
    credential_type = payload.get("credential_type", "AgriculturalProducerCredential")

    claims = payload.get("claims") or {}
    credential_subject: dict[str, Any] = {
        "id": holder_did,
        "name_hash": claims.get("name_hash"),
        "cpf_hash": claims.get("cpf_hash"),
        "rural_producer_registry_id": claims.get("rural_producer_registry_id")
            or payload.get("credential_id"),
    }

    # Sintetiza um proofValue determinístico de 64 bytes (placeholder de Ed25519).
    seed = (payload.get("credential_id") or holder_did).encode()
    raw_proof = (seed * ((64 // max(len(seed), 1)) + 1))[:64]
    proof_value = base64.urlsafe_b64encode(raw_proof).rstrip(b"=").decode()

    proof = VCProof(
        type=payload.get("verification_method") or ED25519_PROOF_TYPE,
        created=issuance_date,
        verificationMethod=f"{issuer}#keys-1",
        proofValue=proof_value,
    )

    return VerifiableCredential(
        context=[VC_CONTEXT_V1, "https://agrotrust.ai/credentials/v1"],
        type=["VerifiableCredential", credential_type],
        issuer=issuer,
        issuanceDate=issuance_date,
        credentialSubject=credential_subject,
        proof=proof,
        expirationDate=None,
    )
