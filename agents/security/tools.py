"""
AgroTrust AI – Ferramentas do Agente de Segurança.

Todas as funções são mocks determinísticos (seed = hash do parâmetro de entrada)
com interfaces async prontas para integração com sistemas reais:
  - run_liveness_check  → MediaPipe / biometria real
  - detect_deepfake     → FaceForensics++ / CLIP-ViT real
  - verify_title_blockchain → Ubitquity API real

O comportamento é determinístico para garantir reprodutibilidade nos testes.
"""

from __future__ import annotations

import hashlib
import random
import uuid

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

# ─── Modelos de retorno ───────────────────────────────────────────────────────


class LivenessResult(BaseModel):
    session_id: str
    passed: bool
    score: float = Field(ge=0.0, le=1.0)  # 1.0 = definitivamente humano


class DeepfakeResult(BaseModel):
    media_url_hash: str  # hash da URL (sem expor URL sensível)
    deepfake_probability: float = Field(ge=0.0, le=1.0)
    voice_clone_probability: float = Field(ge=0.0, le=1.0)
    digital_mask_probability: float = Field(ge=0.0, le=1.0)
    model_used: str = "mock-forensics-v0.1"


class BlockchainResult(BaseModel):
    car_number: str
    verified: bool
    tx_hash: str | None
    registry: str = "Ubitquity (mock)"


# ─── Funções utilitárias ─────────────────────────────────────────────────────


def _seeded_rng(seed_str: str) -> random.Random:
    """RNG determinístico por string: garante reprodutibilidade nos testes."""
    seed_int = int(hashlib.sha3_256(seed_str.encode()).hexdigest()[:16], 16)
    return random.Random(seed_int)


# ─── Ferramentas ──────────────────────────────────────────────────────────────


async def run_liveness_check(session_id: str) -> LivenessResult:
    """
    Mock de detecção de vivacidade (liveness) anti-replay.
    Determinístico: mesmo session_id → mesmo resultado (seed=hash(session_id)).
    Produz liveness_passed=False para IDs que contenham "fake" ou "bot".
    """
    is_forced_fail = any(kw in session_id.lower() for kw in ("fake", "bot", "replay"))
    if is_forced_fail:
        logger.info("liveness_forced_fail", session_id=session_id[:12] + "…")
        return LivenessResult(session_id=session_id, passed=False, score=0.05)

    rng = _seeded_rng(f"liveness:{session_id}")
    passed = rng.random() > 0.05  # 95% pass rate em condições normais
    score = rng.uniform(0.82, 0.99) if passed else rng.uniform(0.02, 0.35)
    logger.info("liveness_checked", session_id=session_id[:12] + "…", passed=passed, score=round(score, 3))
    return LivenessResult(session_id=session_id, passed=passed, score=round(score, 4))


async def detect_deepfake(media_url: str) -> DeepfakeResult:
    """
    Mock de detecção deepfake/voice-clone/digital-mask.
    Determinístico por seed=sha3(media_url).
    Produz probabilidade alta se a URL contiver "deepfake" ou "synthetic".
    """
    url_hash = hashlib.sha3_256(media_url.encode()).hexdigest()
    is_forced_fraud = any(kw in media_url.lower() for kw in ("deepfake", "synthetic", "fake"))

    if is_forced_fraud:
        rng = _seeded_rng(f"deepfake:forced:{url_hash}")
        dp = rng.uniform(0.82, 0.99)
        vc = rng.uniform(0.60, 0.95)
        dm = rng.uniform(0.70, 0.95)
    else:
        rng = _seeded_rng(f"deepfake:{url_hash}")
        dp = rng.uniform(0.00, 0.15)
        vc = rng.uniform(0.00, 0.10)
        dm = rng.uniform(0.00, 0.12)

    logger.info(
        "deepfake_checked",
        url_hash=url_hash[:12] + "…",
        deepfake_prob=round(dp, 3),
        voice_clone_prob=round(vc, 3),
    )
    return DeepfakeResult(
        media_url_hash=url_hash[:32],
        deepfake_probability=round(dp, 4),
        voice_clone_probability=round(vc, 4),
        digital_mask_probability=round(dm, 4),
    )


async def verify_title_blockchain(
    car_number: str,
    owner_cpf_hash: str,
) -> BlockchainResult:
    """
    Mock de verificação de título fundiário em blockchain (Ubitquity).
    tx_hash é determinístico: sha3_256(car_number + ":" + cpf_hash[:16]).
    """
    seed_str = f"{car_number}:{owner_cpf_hash[:16]}"
    tx_hash_hex = hashlib.sha3_256(seed_str.encode()).hexdigest()
    # Formata como UUID v4 para simular um tx hash de blockchain
    tx_uuid = str(uuid.UUID(tx_hash_hex[:32]))

    logger.info(
        "blockchain_title_verified",
        car_number=car_number,
        tx_hash=tx_uuid,
    )
    return BlockchainResult(
        car_number=car_number,
        verified=True,
        tx_hash=tx_uuid,
    )
