"""Testes unitários – core/security/crypto.py"""

from __future__ import annotations

import pytest

from core.security.crypto import (
    KeyManager,
    compute_merkle_root,
    generate_secure_token,
    sha3_256,
)

VALID_KEY = "a" * 64  # 32 bytes hex válido para AES-256


class TestKeyManager:
    def setup_method(self) -> None:
        self.km = KeyManager(VALID_KEY)

    def test_encrypt_decrypt_roundtrip(self) -> None:
        plaintext = b"dado super sensivel do produtor rural"
        payload = self.km.encrypt(plaintext)
        recovered = self.km.decrypt(payload)
        assert recovered == plaintext

    def test_encrypt_with_aad(self) -> None:
        plaintext = b"cpf-hash-ou-dado-identificador"
        aad = b"dossie-id-12345"
        payload = self.km.encrypt(plaintext, associated_data=aad)
        recovered = self.km.decrypt(payload, associated_data=aad)
        assert recovered == plaintext

    def test_decrypt_fails_with_wrong_aad(self) -> None:
        plaintext = b"dado confidencial"
        aad = b"contexto-correto"
        payload = self.km.encrypt(plaintext, associated_data=aad)
        from cryptography.exceptions import InvalidTag

        with pytest.raises((InvalidTag, Exception)):
            self.km.decrypt(payload, associated_data=b"contexto-errado")

    def test_nonces_are_unique(self) -> None:
        plaintext = b"texto repetido"
        p1 = self.km.encrypt(plaintext)
        p2 = self.km.encrypt(plaintext)
        # Nonce diferente => ciphertext diferente mesmo com mesmo plaintext
        assert p1.ciphertext_b64 != p2.ciphertext_b64

    def test_invalid_key_length_raises(self) -> None:
        with pytest.raises(ValueError, match="64 caracteres"):
            KeyManager("short-key")

    def test_key_version_stored(self) -> None:
        km = KeyManager(VALID_KEY, version="v2")
        payload = km.encrypt(b"test")
        assert payload.key_version == "v2"

    def test_payload_serialization(self) -> None:
        payload = self.km.encrypt(b"dados")
        d = payload.to_dict()
        from core.security.crypto import EncryptedPayload

        restored = EncryptedPayload.from_dict(d)
        assert self.km.decrypt(restored) == b"dados"


class TestHashing:
    def test_sha3_256_deterministic(self) -> None:
        h1 = sha3_256(b"agrotrust")
        h2 = sha3_256(b"agrotrust")
        assert h1 == h2
        assert len(h1) == 64  # 32 bytes hex

    def test_sha3_256_different_inputs(self) -> None:
        assert sha3_256(b"a") != sha3_256(b"b")

    def test_merkle_root_empty(self) -> None:
        root = compute_merkle_root([])
        assert len(root) == 64

    def test_merkle_root_single(self) -> None:
        root = compute_merkle_root(["abc123"])
        assert len(root) == 64

    def test_merkle_root_deterministic(self) -> None:
        leaves = [sha3_256(f"leaf-{i}".encode()) for i in range(8)]
        r1 = compute_merkle_root(leaves)
        r2 = compute_merkle_root(leaves)
        assert r1 == r2

    def test_merkle_root_order_matters(self) -> None:
        leaves = [sha3_256(f"leaf-{i}".encode()) for i in range(4)]
        r1 = compute_merkle_root(leaves)
        r2 = compute_merkle_root(list(reversed(leaves)))
        assert r1 != r2


class TestSecureToken:
    def test_token_length(self) -> None:
        token = generate_secure_token(32)
        assert len(token) == 64  # 32 bytes => 64 hex chars

    def test_tokens_are_unique(self) -> None:
        tokens = {generate_secure_token() for _ in range(100)}
        assert len(tokens) == 100
