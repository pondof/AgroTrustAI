"""
Tests unitários – core/credentials.py (W3C Verifiable Credentials).

Cobre:
  - VCVerifier.verify(): 6 checks (context, type, issuer, expiração, proofValue,
    verificationMethod) — verifica que cada falha é capturada em checks_failed.
  - _build_chain_of_trust por DID (dataprev, gov.br genérico, desconhecido).
  - build_vc_from_dataprev_payload: payload completo e mínimo.
  - Helpers internos: _b64url_decode (padding variável), _parse_iso (com Z UTC).
  - to_dict da VerifiableCredential (serialização JSON-LD).
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

import pytest

from core.credentials import (
    DID_GOV_BR_PREFIX,
    ED25519_PROOF_TYPE,
    MIN_PROOF_BYTES,
    VC_CONTEXT_V1,
    VCProof,
    VCVerifier,
    VerifiableCredential,
    _b64url_decode,
    _parse_iso,
    build_vc_from_dataprev_payload,
)

# ─── Builders auxiliares ─────────────────────────────────────────────────────


def _valid_proof(issuer: str = "did:gov:br:dataprev") -> VCProof:
    raw = b"X" * 64
    proof_value = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    return VCProof(
        type=ED25519_PROOF_TYPE,
        created="2026-05-12T00:00:00+00:00",
        verificationMethod=f"{issuer}#keys-1",
        proofValue=proof_value,
    )


def _valid_vc(
    *,
    issuer: str = "did:gov:br:dataprev",
    expiration: str | None = None,
    proof: VCProof | None = None,
) -> VerifiableCredential:
    return VerifiableCredential(
        context=[VC_CONTEXT_V1, "https://agrotrust.ai/credentials/v1"],
        type=["VerifiableCredential", "AgriculturalProducerCredential"],
        issuer=issuer,
        issuanceDate="2026-01-01T00:00:00+00:00",
        credentialSubject={"id": "did:gov:br:abc"},
        proof=proof or _valid_proof(issuer),
        expirationDate=expiration,
    )


# ─── _b64url_decode ──────────────────────────────────────────────────────────


class TestB64UrlDecode:
    def test_decodes_padded_input(self) -> None:
        raw = b"hello world!"
        encoded = base64.urlsafe_b64encode(raw).decode()
        assert _b64url_decode(encoded) == raw

    def test_decodes_unpadded_input(self) -> None:
        raw = b"hello"
        encoded = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
        assert _b64url_decode(encoded) == raw

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="proofValue vazio"):
            _b64url_decode("")


# ─── _parse_iso ──────────────────────────────────────────────────────────────


class TestParseIso:
    def test_handles_zulu_suffix(self) -> None:
        dt = _parse_iso("2026-05-12T10:30:00Z")
        assert dt.year == 2026 and dt.month == 5 and dt.day == 12

    def test_handles_explicit_offset(self) -> None:
        dt = _parse_iso("2026-05-12T10:30:00+00:00")
        assert dt.year == 2026


# ─── VCVerifier ──────────────────────────────────────────────────────────────


class TestVCVerifierHappyPath:
    def test_valid_vc_passes_all_checks(self) -> None:
        vc = _valid_vc()
        result = VCVerifier().verify(vc)
        assert result.valid is True
        assert not result.checks_failed
        assert "context_w3c_vc_v1" in result.checks_passed
        assert "type_includes_verifiable_credential" in result.checks_passed
        assert "issuer_gov_br_did" in result.checks_passed
        assert "proof_value_valid_base64url" in result.checks_passed
        assert "verification_method_matches_issuer" in result.checks_passed

    def test_valid_vc_with_future_expiration_passes(self) -> None:
        future = (datetime.now(UTC) + timedelta(days=365)).isoformat()
        vc = _valid_vc(expiration=future)
        result = VCVerifier().verify(vc)
        assert result.valid is True
        assert "not_expired" in result.checks_passed

    def test_chain_of_trust_resolved_for_dataprev_issuer(self) -> None:
        vc = _valid_vc(issuer="did:gov:br:dataprev:mgi")
        result = VCVerifier().verify(vc)
        assert result.chain_of_trust == ["Dataprev", "Gov.br", "ITI"]

    def test_chain_of_trust_for_generic_gov_br_issuer(self) -> None:
        vc = _valid_vc(issuer="did:gov:br:outro:org")
        result = VCVerifier().verify(vc)
        assert result.chain_of_trust == ["Gov.br", "ITI"]


class TestVCVerifierFailures:
    def test_missing_w3c_context_fails(self) -> None:
        vc = _valid_vc()
        vc.context.remove(VC_CONTEXT_V1)
        result = VCVerifier().verify(vc)
        assert result.valid is False
        assert "context_missing_w3c_vc_v1" in result.checks_failed

    def test_missing_verifiable_credential_type_fails(self) -> None:
        vc = _valid_vc()
        vc.type.remove("VerifiableCredential")
        result = VCVerifier().verify(vc)
        assert result.valid is False
        assert "type_missing_verifiable_credential" in result.checks_failed

    def test_non_gov_br_issuer_fails(self) -> None:
        vc = _valid_vc(issuer="did:web:example.com")
        # Recriamos o proof apontando para o novo issuer para isolar a falha de issuer
        vc = VerifiableCredential(
            context=vc.context,
            type=vc.type,
            issuer="did:web:example.com",
            issuanceDate=vc.issuanceDate,
            credentialSubject=vc.credentialSubject,
            proof=_valid_proof(issuer="did:web:example.com"),
        )
        result = VCVerifier().verify(vc)
        assert result.valid is False
        assert "issuer_not_gov_br_did" in result.checks_failed

    def test_expired_credential_fails(self) -> None:
        past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        vc = _valid_vc(expiration=past)
        result = VCVerifier().verify(vc)
        assert result.valid is False
        assert "credential_expired" in result.checks_failed

    def test_unparseable_expiration_fails(self) -> None:
        vc = _valid_vc(expiration="not-a-date")
        result = VCVerifier().verify(vc)
        assert result.valid is False
        assert "expirationDate_unparseable" in result.checks_failed

    def test_too_short_proof_fails(self) -> None:
        # 16 bytes < 32 mínimo
        short_raw = b"x" * 16
        proof = VCProof(
            type=ED25519_PROOF_TYPE,
            created="2026-01-01T00:00:00+00:00",
            verificationMethod="did:gov:br:dataprev#keys-1",
            proofValue=base64.urlsafe_b64encode(short_raw).rstrip(b"=").decode(),
        )
        vc = _valid_vc(proof=proof)
        result = VCVerifier().verify(vc)
        assert result.valid is False
        assert any("proof_value_too_short" in f for f in result.checks_failed)

    def test_bad_proof_decode_fails(self) -> None:
        proof = VCProof(
            type=ED25519_PROOF_TYPE,
            created="2026-01-01T00:00:00+00:00",
            verificationMethod="did:gov:br:dataprev#keys-1",
            proofValue="",  # vazio → ValueError em _b64url_decode
        )
        vc = _valid_vc(proof=proof)
        result = VCVerifier().verify(vc)
        assert result.valid is False
        assert any("proof_value_decode_failed" in f for f in result.checks_failed)

    def test_verification_method_not_matching_issuer_fails(self) -> None:
        proof = VCProof(
            type=ED25519_PROOF_TYPE,
            created="2026-01-01T00:00:00+00:00",
            verificationMethod="did:web:outro.com#keys-1",
            proofValue=base64.urlsafe_b64encode(b"X" * 64).rstrip(b"=").decode(),
        )
        vc = _valid_vc(proof=proof)
        result = VCVerifier().verify(vc)
        assert result.valid is False
        assert "verification_method_does_not_match_issuer" in result.checks_failed


# ─── VerifiableCredential.to_dict ────────────────────────────────────────────


class TestSerialization:
    def test_to_dict_includes_required_keys(self) -> None:
        vc = _valid_vc()
        d = vc.to_dict()
        for key in ("@context", "type", "issuer", "issuanceDate", "credentialSubject", "proof"):
            assert key in d, f"Chave obrigatória ausente: {key}"
        assert "expirationDate" not in d  # expiration None → omitida

    def test_to_dict_includes_expiration_when_present(self) -> None:
        vc = _valid_vc(expiration="2030-01-01T00:00:00+00:00")
        d = vc.to_dict()
        assert d["expirationDate"] == "2030-01-01T00:00:00+00:00"

    def test_proof_extras_merged(self) -> None:
        proof = _valid_proof()
        proof.extra["proofPurpose"] = "assertionMethod"
        vc = _valid_vc(proof=proof)
        d = vc.to_dict()
        assert d["proof"]["proofPurpose"] == "assertionMethod"


# ─── build_vc_from_dataprev_payload ──────────────────────────────────────────


_FULL_PAYLOAD = {
    "credential_id": "cred-123",
    "holder_did": "did:gov:br:holder-abc",
    "verified": True,
    "verification_method": "Ed25519Signature2020",
    "verification_timestamp": "2026-05-12T10:00:00+00:00",
    "credential_type": "AgriculturalProducerCredential",
    "issuer": "did:gov:br:dataprev:mgi",
    "is_revoked": False,
    "revocation_reason": None,
    "claims": {
        "name_hash": "abc123",
        "cpf_hash": "def456",
        "rural_producer_registry_id": "RPR-789",
    },
    "signature_valid": True,
    "chain_of_trust": ["did:gov:br:dataprev:mgi", "did:gov:br:iti"],
}


class TestBuildVCFromDataprev:
    def test_full_payload_yields_verifiable_vc(self) -> None:
        vc = build_vc_from_dataprev_payload(_FULL_PAYLOAD, holder_did="did:gov:br:holder-abc")
        assert vc.issuer == "did:gov:br:dataprev:mgi"
        assert "VerifiableCredential" in vc.type
        assert "AgriculturalProducerCredential" in vc.type
        assert vc.credentialSubject["id"] == "did:gov:br:holder-abc"
        assert vc.credentialSubject["cpf_hash"] == "def456"
        # Proof determinístico — pelo menos MIN_PROOF_BYTES
        decoded = _b64url_decode(vc.proof.proofValue)
        assert len(decoded) >= MIN_PROOF_BYTES

    def test_built_vc_passes_verifier(self) -> None:
        vc = build_vc_from_dataprev_payload(_FULL_PAYLOAD, holder_did="did:gov:br:holder-abc")
        result = VCVerifier().verify(vc)
        assert result.valid is True, f"checks_failed={result.checks_failed}"

    def test_minimal_payload_uses_defaults(self) -> None:
        minimal = {"verified": True}
        vc = build_vc_from_dataprev_payload(minimal, holder_did="did:gov:br:novo")
        # Defaults: issuer=did:gov:br:dataprev, credential_type=AgriculturalProducerCredential
        assert vc.issuer.startswith(DID_GOV_BR_PREFIX)
        assert "AgriculturalProducerCredential" in vc.type

    def test_minimal_payload_still_passes_verifier(self) -> None:
        minimal = {"verified": True}
        vc = build_vc_from_dataprev_payload(minimal, holder_did="did:gov:br:novo")
        result = VCVerifier().verify(vc)
        assert result.valid is True

    def test_proof_value_is_deterministic_per_credential_id(self) -> None:
        vc1 = build_vc_from_dataprev_payload(_FULL_PAYLOAD, holder_did="did:gov:br:x")
        vc2 = build_vc_from_dataprev_payload(_FULL_PAYLOAD, holder_did="did:gov:br:x")
        assert vc1.proof.proofValue == vc2.proof.proofValue
