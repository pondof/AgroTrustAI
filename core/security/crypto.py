"""
AgroTrust AI – Primitivas criptográficas.

Regras:
  - AES-256-GCM para dados em repouso e em trânsito entre serviços internos.
  - Chave mestra lida de SecretStr (nunca str pura).
  - Nonce/IV único por operação (nunca reutilizado).
  - SHA-3-256 para hashing determinístico (logs de auditoria, Merkle roots).
  - Zero dados sensíveis em logs.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from base64 import b64decode, b64encode
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


# ─── Tipos ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class EncryptedPayload:
    """Resultado de encrypt(). Serializa como Base64 para transporte."""
    ciphertext_b64: str   # nonce || ciphertext || tag (concatenados, depois b64)
    key_version: str      # referência à versão da chave (para rotação)

    def to_dict(self) -> dict[str, str]:
        return {"c": self.ciphertext_b64, "kv": self.key_version}

    @classmethod
    def from_dict(cls, d: dict[str, str]) -> "EncryptedPayload":
        return cls(ciphertext_b64=d["c"], key_version=d["kv"])


# ─── Gerenciamento de chaves ──────────────────────────────────────────────────

class KeyManager:
    """
    Gerencia chaves AES-256 derivadas da master key.
    Em produção, substituir por integração com HSM / KMS (ex: AWS KMS, Azure Key Vault).
    """

    NONCE_SIZE = 12   # 96 bits – recomendado pelo NIST para AES-GCM
    TAG_SIZE   = 16   # 128 bits

    def __init__(self, master_key_hex: str, version: str = "v1") -> None:
        if len(master_key_hex) != 64:
            raise ValueError("master_key_hex deve ter exatamente 64 caracteres (32 bytes AES-256)")
        self._key = bytes.fromhex(master_key_hex)
        self._version = version

    def encrypt(self, plaintext: bytes, associated_data: bytes | None = None) -> EncryptedPayload:
        """
        Cifra com AES-256-GCM.
        associated_data (AAD) é autenticado mas não cifrado – use para metadados de contexto.
        """
        nonce = os.urandom(self.NONCE_SIZE)
        aesgcm = AESGCM(self._key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, associated_data)
        blob = b64encode(nonce + ciphertext).decode()
        return EncryptedPayload(ciphertext_b64=blob, key_version=self._version)

    def decrypt(self, payload: EncryptedPayload, associated_data: bytes | None = None) -> bytes:
        """Decifra e verifica autenticidade. Lança InvalidTag se tampered."""
        raw = b64decode(payload.ciphertext_b64)
        nonce = raw[: self.NONCE_SIZE]
        ciphertext = raw[self.NONCE_SIZE :]
        aesgcm = AESGCM(self._key)
        return aesgcm.decrypt(nonce, ciphertext, associated_data)


# ─── Hashing ──────────────────────────────────────────────────────────────────

def sha3_256(data: bytes) -> str:
    """SHA-3-256 (Keccak). Retorna hex string lowercase."""
    return hashlib.sha3_256(data).hexdigest()


def compute_merkle_root(leaves: list[str]) -> str:
    """
    Calcula Merkle root de uma lista de hashes hex.
    Usado para verificação de integridade de lotes de dossiês.
    """
    if not leaves:
        return sha3_256(b"empty")
    nodes = list(leaves)
    while len(nodes) > 1:
        if len(nodes) % 2 != 0:
            nodes.append(nodes[-1])   # duplica último nó se ímpar
        nodes = [
            sha3_256((nodes[i] + nodes[i + 1]).encode())
            for i in range(0, len(nodes), 2)
        ]
    return nodes[0]


def generate_secure_token(nbytes: int = 32) -> str:
    """Token criptograficamente seguro para sessões, nonces de API etc."""
    return secrets.token_hex(nbytes)


# ─── Instância global (inicializada via settings) ─────────────────────────────

_key_manager: KeyManager | None = None


def init_key_manager(master_key_hex: str, version: str = "v1") -> None:
    global _key_manager
    _key_manager = KeyManager(master_key_hex, version)


def get_key_manager() -> KeyManager:
    if _key_manager is None:
        raise RuntimeError("KeyManager não inicializado. Chame init_key_manager() na startup.")
    return _key_manager
