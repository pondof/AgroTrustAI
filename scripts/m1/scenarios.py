"""
AgroTrust AI – Geração dos 50 cenários para validação do Marco M1.

Distribuição obrigatória do critério M1:
  15 approved + 15 manual_review + 10 rejected_esg + 10 rejected_fraud = 50

Cada cenário é determinístico (seed = índice) e usa valores plausíveis para
crédito rural brasileiro (área 80-4500 ha, crédito R$50k-R$2M, biomas reais).

Sub-variantes (campo `variant`) controlam o caminho que produz o veredicto esperado:
  approved           → "default"
  manual_review      → "car_pendente" | "vc_revogada"
  rejected_esg       → "desmatamento" | "car_cancelado"
  rejected_fraud     → "liveness_fail" | "deepfake"
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from typing import Literal

ScenarioCategory = Literal["approved", "manual_review", "rejected_esg", "rejected_fraud"]
ExpectedVerdict = Literal["approved", "manual_review", "rejected"]

# Coordenadas plausíveis por bioma brasileiro (lat, lon, UF, município, bioma)
_LOCATIONS: list[tuple[float, float, str, str, str]] = [
    (-12.5, -55.3, "MT", "Sorriso", "Cerrado"),
    (-28.6, -53.6, "RS", "Cruz Alta", "Pampa"),
    (-3.2, -52.2, "PA", "Altamira", "Amazônia"),
    (-17.8, -50.9, "GO", "Rio Verde", "Cerrado"),
    (-22.2, -54.8, "MS", "Dourados", "Mata Atlântica"),
    (-15.8, -47.9, "DF", "Brasília", "Cerrado"),
    (-9.5, -67.8, "AC", "Rio Branco", "Amazônia"),
    (-7.1, -41.7, "PI", "Floriano", "Caatinga"),
    (-19.0, -57.0, "MS", "Corumbá", "Pantanal"),
]

_TENANTS = ["sicredi-rs", "sicoob-mt", "fiagro-x", "banco-do-povo", "coop-cerrado"]
_PURPOSES = ["custeio", "investimento", "comercialização"]


@dataclass(slots=True, frozen=True)
class M1Scenario:
    """Cenário sintético — encapsula tudo que é necessário para um dossiê M1.

    Carrega:
      (a) Identificadores e dados do produtor/propriedade para o DossieState
      (b) Dados que os mocks HTTP devem retornar (SICAR/GEE/Dataprev/Open Finance)
      (c) Categoria + variante + veredicto esperado para validação
    """

    # ─── Categorização ────────────────────────────────────────────────────────
    index: int
    category: ScenarioCategory
    variant: str
    expected_verdict: ExpectedVerdict

    # ─── Identidade ───────────────────────────────────────────────────────────
    dossie_id: str
    correlation_id: str
    tenant_id: str
    cpf_hash: str
    holder_did: str
    consent_id: str
    session_id: str
    media_url: str

    # ─── Propriedade ──────────────────────────────────────────────────────────
    car_number: str
    property_area_ha: float
    location_lat: float
    location_lon: float
    location_estado: str
    location_municipio: str
    location_biome: str
    credit_amount_brl: float
    credit_purpose: str
    requested_by: str

    # ─── Mock SICAR ───────────────────────────────────────────────────────────
    car_status: str
    car_compliance: str
    car_area_desmatamento_ha: float
    car_area_total_ha: float

    # ─── Mock GEE ─────────────────────────────────────────────────────────────
    gee_deforestation_detected: bool
    gee_deforestation_area_ha: float
    gee_biome: str
    gee_confidence: float

    # ─── Mock Dataprev (VC) ───────────────────────────────────────────────────
    vc_verified: bool
    vc_is_revoked: bool
    vc_credential_type: str

    # ─── Mock Open Finance ────────────────────────────────────────────────────
    of_monthly_revenue_brl: float
    of_dti: float
    of_months_history: int
    of_defaulted_operations: int
    of_total_rural_credit_brl: float
    of_data_quality: float


# ─── Templates de dados financeiros por perfil ───────────────────────────────

_FIN_PROFILE_GOOD = {
    "monthly_revenue": (85_000.0, 250_000.0),
    "dti": (0.18, 0.32),
    "months": (12, 24),
    "defaulted": (0, 0),
    "rural_credit": (0.0, 80_000.0),
    "quality": (0.90, 0.98),
}

_FIN_PROFILE_BAD = {
    "monthly_revenue": (18_000.0, 35_000.0),
    "dti": (0.60, 0.75),
    "months": (3, 8),
    "defaulted": (1, 3),
    "rural_credit": (150_000.0, 400_000.0),
    "quality": (0.65, 0.82),
}


# ─── Builders auxiliares ─────────────────────────────────────────────────────


def _hash_seed(seed: str) -> str:
    return hashlib.sha3_256(seed.encode()).hexdigest()


def _build_car_number(
    rng: random.Random,
    category: ScenarioCategory,
    variant: str,
) -> str:
    """CAR plausível BR: UF-IBGE-HEX16. Embute keyword em variantes específicas."""
    state = rng.choice(["MT", "RS", "PA", "GO", "MS", "MA", "PI", "TO"])
    ibge = rng.randint(1000000, 9999999)
    suffix = "".join(rng.choices("0123456789ABCDEF", k=16))

    if category == "rejected_esg" and variant == "desmatamento":
        suffix = "DEFOREST" + suffix[8:]
    elif category == "rejected_esg" and variant == "car_cancelado":
        suffix = "CANCELAD" + suffix[8:]
    return f"{state}-{ibge}-{suffix}"


def _build_session_media(
    rng: random.Random,
    category: ScenarioCategory,
    variant: str,
    idx: int,
) -> tuple[str, str]:
    """session_id/media_url disparam fraud quando contêm palavras-chave (mocks)."""
    base = _hash_seed(f"sess-{idx}")[:24]
    if category == "rejected_fraud" and variant == "liveness_fail":
        return f"session-fake-{base}", f"https://biometria.agrotrust.ai/{base}.mp4.enc"
    if category == "rejected_fraud" and variant == "deepfake":
        return f"session-{base}", f"https://biometria.agrotrust.ai/deepfake-{base}.mp4.enc"
    return f"session-{base}", f"https://biometria.agrotrust.ai/{base}.mp4.enc"


def _sample(rng: random.Random, lo: float, hi: float, *, integer: bool = False) -> float:
    v = rng.uniform(lo, hi)
    if integer:
        return float(int(round(v)))
    return round(v, 2)


def _build_one(idx: int, category: ScenarioCategory, variant: str) -> M1Scenario:
    rng = random.Random(idx * 31 + 17)

    base_lat, base_lon, estado, municipio, biome = rng.choice(_LOCATIONS)
    lat = round(base_lat + rng.uniform(-0.45, 0.45), 6)
    lon = round(base_lon + rng.uniform(-0.45, 0.45), 6)

    car_number = _build_car_number(rng, category, variant)
    cpf_hash = _hash_seed(f"cpf-{idx}-{category}-{variant}")
    holder_did = f"did:gov:br:{cpf_hash[:32]}"
    session_id, media_url = _build_session_media(rng, category, variant, idx)
    consent_id = f"CONSENT_M1_{idx:03d}"

    property_area_ha = round(rng.uniform(80.0, 4500.0), 1)
    credit_amount = round(rng.uniform(50_000.0, 2_000_000.0), 2)
    credit_purpose = rng.choice(_PURPOSES)

    # Padrões por categoria/variant
    car_status = "ativo"
    car_compliance = "regular"
    car_desmat = 0.0
    gee_det = False
    gee_area = 0.0
    vc_verified = True
    vc_revoked = False
    fin_profile = _FIN_PROFILE_GOOD
    expected: ExpectedVerdict = "approved"

    if category == "approved":
        pass  # defaults

    elif category == "manual_review":
        expected = "manual_review"
        if variant == "car_pendente":
            car_status = "pendente"
            car_compliance = "com_pendencia"
        elif variant == "vc_revogada":
            vc_revoked = True  # → ESG PENDING_DOCS → has_warning → manual_review

    elif category == "rejected_esg":
        expected = "rejected"
        # Para garantir verdict=rejected (não manual_review), precisamos:
        #   composite < 450 E sem has_warning
        # ESG REJECTED produz esg_score=0; usamos perfil financeiro ruim para fin_score baixo.
        fin_profile = _FIN_PROFILE_BAD
        if variant == "desmatamento":
            car_compliance = "irregular"
            car_desmat = round(rng.uniform(15.0, 250.0), 1)
            gee_det = True
            gee_area = car_desmat
        elif variant == "car_cancelado":
            car_status = rng.choice(["cancelado", "suspenso"])
            car_compliance = "irregular"

    elif category == "rejected_fraud":
        expected = "rejected"
        # short-circuit no SecurityGuardAgent — outros agentes não rodam
        # SICAR/GEE/Dataprev devem retornar dados válidos mesmo assim para evitar 404

    return M1Scenario(
        index=idx,
        category=category,
        variant=variant,
        expected_verdict=expected,
        dossie_id=f"dossie-m1-{idx:03d}",
        correlation_id=f"corr-m1-{idx:03d}",
        tenant_id=rng.choice(_TENANTS),
        cpf_hash=cpf_hash,
        holder_did=holder_did,
        consent_id=consent_id,
        session_id=session_id,
        media_url=media_url,
        car_number=car_number,
        property_area_ha=property_area_ha,
        location_lat=lat,
        location_lon=lon,
        location_estado=estado,
        location_municipio=municipio,
        location_biome=biome,
        credit_amount_brl=credit_amount,
        credit_purpose=credit_purpose,
        requested_by=f"analista-{rng.randint(100, 999)}",
        car_status=car_status,
        car_compliance=car_compliance,
        car_area_desmatamento_ha=car_desmat,
        car_area_total_ha=property_area_ha,
        gee_deforestation_detected=gee_det,
        gee_deforestation_area_ha=gee_area,
        gee_biome=biome,
        gee_confidence=round(rng.uniform(0.90, 0.99), 3),
        vc_verified=vc_verified,
        vc_is_revoked=vc_revoked,
        vc_credential_type="AgriculturalProducerCredential",
        of_monthly_revenue_brl=_sample(rng, *fin_profile["monthly_revenue"]),
        of_dti=round(_sample(rng, *fin_profile["dti"]), 4),
        of_months_history=int(_sample(rng, *fin_profile["months"], integer=True)),
        of_defaulted_operations=int(_sample(rng, *fin_profile["defaulted"], integer=True)),
        of_total_rural_credit_brl=_sample(rng, *fin_profile["rural_credit"]),
        of_data_quality=round(_sample(rng, *fin_profile["quality"]), 4),
    )


# ─── API pública ─────────────────────────────────────────────────────────────


def generate_scenarios() -> list[M1Scenario]:
    """Gera os 50 cenários M1 com distribuição 15/15/10/10."""
    plan: list[tuple[ScenarioCategory, str]] = []

    # 15 approved
    plan.extend([("approved", "default")] * 15)

    # 15 manual_review: 8 CAR pendente + 7 VC revogada
    plan.extend([("manual_review", "car_pendente")] * 8)
    plan.extend([("manual_review", "vc_revogada")] * 7)

    # 10 rejected_esg: 6 desmatamento + 4 CAR cancelado/suspenso
    plan.extend([("rejected_esg", "desmatamento")] * 6)
    plan.extend([("rejected_esg", "car_cancelado")] * 4)

    # 10 rejected_fraud: 5 liveness fail + 5 deepfake
    plan.extend([("rejected_fraud", "liveness_fail")] * 5)
    plan.extend([("rejected_fraud", "deepfake")] * 5)

    if len(plan) != 50:
        raise AssertionError(f"Distribuição M1 inválida: {len(plan)} cenários")

    return [_build_one(idx, cat, var) for idx, (cat, var) in enumerate(plan)]
