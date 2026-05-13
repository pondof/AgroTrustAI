"""
AgroTrust AI – Testes dos schemas de eventos Kafka.

Cobre:
  - LGPD Art. 20: SubscriptionVerdictEvent rejected exige rejection_reasons.
  - Validações de range (confidence_score 0..1, trust_score 0..1000, probabilidades 0..1).
  - Campos obrigatórios herdados (correlation_id, tenant_id).
  - TOPIC_SCHEMAS mapeando cada tópico para o schema correto.
  - Roundtrip de serialização/deserialização para cada tipo de evento.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from core.events.schemas import (
    TOPIC_SCHEMAS,
    BaseEvent,
    ESGAgentResultEvent,
    ESGComplianceStatus,
    FinancialAgentResultEvent,
    PropertyLocation,
    SecurityAgentResultEvent,
    SubscriptionInitiatedEvent,
    SubscriptionVerdictEvent,
)

# ─── Helpers de fábrica ──────────────────────────────────────────────────────


def _base_kwargs() -> dict[str, str]:
    return {"correlation_id": "00000000-0000-0000-0000-000000000001", "tenant_id": "coop-001"}


def _make_subscription_initiated(**overrides: object) -> SubscriptionInitiatedEvent:
    return SubscriptionInitiatedEvent(
        **_base_kwargs(),
        dossie_id="DOS-ABC123",
        producer_cpf_hash="a" * 64,
        car_number="MT-5100250-3A4B5C6D7E8F9A0B",
        property_area_ha=2450.5,
        location=PropertyLocation(latitude=-12.5450, longitude=-55.7117, municipio="Sorriso", estado="MT"),
        credit_amount_brl=500_000.0,
        credit_purpose="custeio",
        requested_by="user-001",
        **overrides,  # type: ignore[arg-type]
    )


def _make_esg_result(**overrides: object) -> ESGAgentResultEvent:
    defaults: dict[str, object] = {
        "dossie_id": "DOS-ABC123",
        "car_status": "ativo",
        "car_verified_at": "2026-05-01T00:00:00Z",
        "deforestation_detected": False,
        "vc_credential_valid": True,
        "compliance_status": ESGComplianceStatus.APPROVED,
        "xai_rationale": {"top_factor": "CAR ativo + sem desmatamento"},
        "confidence_score": 0.95,
    }
    defaults.update(overrides)
    return ESGAgentResultEvent(**_base_kwargs(), **defaults)  # type: ignore[arg-type]


def _make_financial_result(**overrides: object) -> FinancialAgentResultEvent:
    defaults: dict[str, object] = {
        "dossie_id": "DOS-ABC123",
        "trust_score": 720.0,
        "open_finance_data_months": 6,
        "avg_monthly_revenue_brl": 85_000.0,
        "debt_to_income_ratio": 0.28,
        "existing_rural_credit_brl": 450_000.0,
        "recommended_credit_limit_brl": 600_000.0,
        "risk_tier": "B",
        "xai_rationale": {"dti": 0.28, "history_months": 6},
        "open_finance_consent_id": "CONSENT_REGULAR_001",
    }
    defaults.update(overrides)
    return FinancialAgentResultEvent(**_base_kwargs(), **defaults)  # type: ignore[arg-type]


def _make_security_result(**overrides: object) -> SecurityAgentResultEvent:
    defaults: dict[str, object] = {
        "dossie_id": "DOS-ABC123",
        "liveness_passed": True,
        "deepfake_probability": 0.02,
        "voice_clone_probability": 0.01,
        "digital_mask_probability": 0.03,
        "title_verified_on_blockchain": True,
        "fraud_risk_level": "low",
        "kyc_passed": True,
    }
    defaults.update(overrides)
    return SecurityAgentResultEvent(**_base_kwargs(), **defaults)  # type: ignore[arg-type]


def _make_verdict(**overrides: object) -> SubscriptionVerdictEvent:
    defaults: dict[str, object] = {
        "dossie_id": "DOS-ABC123",
        "verdict": "approved",
        "approved_amount_brl": 500_000.0,
        "esg_score": 0.95,
        "financial_score": 0.82,
        "security_score": 0.99,
        "composite_score": 0.92,
        "xai_consolidated_rationale": {"summary": "ok"},
        "processing_time_ms": 12_345,
    }
    defaults.update(overrides)
    return SubscriptionVerdictEvent(**_base_kwargs(), **defaults)  # type: ignore[arg-type]


# ─── LGPD Art. 20 ────────────────────────────────────────────────────────────


class TestLGPDArt20:
    def test_rejected_without_reasons_raises(self) -> None:
        with pytest.raises(ValidationError) as exc:
            _make_verdict(verdict="rejected", rejection_reasons=[], approved_amount_brl=None)
        assert "rejection_reason" in str(exc.value).lower()

    def test_rejected_with_reasons_succeeds(self) -> None:
        verdict = _make_verdict(
            verdict="rejected",
            rejection_reasons=["DTI > 0.65", "CAR irregular"],
            approved_amount_brl=None,
        )
        assert verdict.verdict == "rejected"
        assert len(verdict.rejection_reasons) == 2

    def test_approved_does_not_require_reasons(self) -> None:
        verdict = _make_verdict()  # approved sem reasons (default)
        assert verdict.verdict == "approved"
        assert verdict.rejection_reasons == []


# ─── Validações de range ─────────────────────────────────────────────────────


class TestRangeValidations:
    def test_esg_confidence_above_one_raises(self) -> None:
        with pytest.raises(ValidationError):
            _make_esg_result(confidence_score=1.5)

    def test_esg_confidence_below_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            _make_esg_result(confidence_score=-0.01)

    def test_esg_confidence_at_bounds_ok(self) -> None:
        assert _make_esg_result(confidence_score=0.0).confidence_score == 0.0
        assert _make_esg_result(confidence_score=1.0).confidence_score == 1.0

    def test_trust_score_above_1000_raises(self) -> None:
        with pytest.raises(ValidationError):
            _make_financial_result(trust_score=1001.0)

    def test_trust_score_negative_raises(self) -> None:
        with pytest.raises(ValidationError):
            _make_financial_result(trust_score=-1.0)

    @pytest.mark.parametrize(
        "field",
        ["deepfake_probability", "voice_clone_probability", "digital_mask_probability"],
    )
    def test_security_probabilities_must_be_zero_to_one(self, field: str) -> None:
        with pytest.raises(ValidationError):
            _make_security_result(**{field: 1.5})
        with pytest.raises(ValidationError):
            _make_security_result(**{field: -0.1})


# ─── Campos obrigatórios herdados ───────────────────────────────────────────


class TestRequiredInheritedFields:
    def test_correlation_id_required_on_all_events(self) -> None:
        with pytest.raises(ValidationError):
            SubscriptionInitiatedEvent(
                tenant_id="coop-001",
                dossie_id="DOS-1",
                producer_cpf_hash="a" * 64,
                car_number="MT-X",
                property_area_ha=10.0,
                location=PropertyLocation(latitude=0, longitude=0, municipio="X", estado="MT"),
                credit_amount_brl=1000.0,
                credit_purpose="custeio",
                requested_by="u",
            )  # type: ignore[call-arg]

    def test_tenant_id_required_on_all_events(self) -> None:
        with pytest.raises(ValidationError):
            ESGAgentResultEvent(
                correlation_id="abc",
                dossie_id="DOS-1",
                car_status="ativo",
                car_verified_at="2026-05-01T00:00:00Z",
                deforestation_detected=False,
                vc_credential_valid=True,
                compliance_status=ESGComplianceStatus.APPROVED,
                xai_rationale={},
                confidence_score=0.9,
            )  # type: ignore[call-arg]

    def test_event_id_auto_generated(self) -> None:
        ev = _make_subscription_initiated()
        assert ev.event_id  # uuid v4 não vazio
        assert "-" in ev.event_id


# ─── TOPIC_SCHEMAS mapping ───────────────────────────────────────────────────


class TestTopicSchemasMapping:
    def test_all_expected_topics_present(self) -> None:
        expected = {
            "agrotrust.subscription.initiated": SubscriptionInitiatedEvent,
            "agrotrust.agent.esg.result": ESGAgentResultEvent,
            "agrotrust.agent.financial.result": FinancialAgentResultEvent,
            "agrotrust.agent.security.result": SecurityAgentResultEvent,
            "agrotrust.subscription.verdict": SubscriptionVerdictEvent,
        }
        for topic, schema in expected.items():
            assert topic in TOPIC_SCHEMAS
            assert TOPIC_SCHEMAS[topic] is schema

    def test_all_schemas_inherit_baseevent(self) -> None:
        for schema in TOPIC_SCHEMAS.values():
            assert issubclass(schema, BaseEvent)


# ─── Roundtrip JSON ──────────────────────────────────────────────────────────


class TestRoundtripSerialization:
    @pytest.mark.parametrize(
        "factory",
        [
            _make_subscription_initiated,
            _make_esg_result,
            _make_financial_result,
            _make_security_result,
            _make_verdict,
        ],
    )
    def test_roundtrip(self, factory) -> None:  # type: ignore[no-untyped-def]
        original = factory()
        # via model_dump → json.dumps → json.loads → model_validate
        as_dict = original.model_dump(mode="json")
        as_json = json.dumps(as_dict)
        reloaded_dict = json.loads(as_json)
        reloaded = type(original).model_validate(reloaded_dict)
        assert reloaded.event_id == original.event_id
        assert reloaded.correlation_id == original.correlation_id
        assert reloaded.tenant_id == original.tenant_id
        assert reloaded.model_dump(mode="json") == as_dict
