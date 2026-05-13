"""
Tests unitários – microsserviços HTTP dos 3 agentes.

Os diretórios services/agent-esg, services/agent-financial e services/agent-security
contêm hífen e não são pacotes Python — usamos importlib.util para carregá-los.

Cobre, para cada serviço:
  - create_app() retorna FastAPI válido
  - GET /health é público e responde 200
  - POST /run sem token → 401
  - POST /run com token sem o scope correto → 403
  - POST /run com token + scope correto + AgentExecutionError do agente → 500
  - POST /run com payload inválido (Pydantic) → 422

A execução real dos agentes é mockada (patch em app.state.agent.run) para isolar
o teste da camada HTTP/Auth.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from agents.base import AgentExecutionError
from agents.esg.schemas import ESGOutput
from agents.financial.schemas import FinancialOutput
from agents.security.schemas import SecurityOutput
from core.events.schemas import ESGComplianceStatus
from core.security.iam import Scope, TokenService

# ─── Loader importlib para diretórios com hífen ──────────────────────────────


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_service_module(service_dir: str, mod_name: str) -> types.ModuleType:
    """Carrega services/{service_dir}/app.py como módulo Python via importlib."""
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    path = _PROJECT_ROOT / "services" / service_dir / "app.py"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


# ─── Helpers de token ────────────────────────────────────────────────────────


def _issue_token(scopes: list[Scope], tenant_id: str = "tenant-test") -> str:
    return TokenService().issue_service_token(
        service_id="service-test",
        tenant_id=tenant_id,
        scopes=scopes,
        ttl_minutes=10,
    )


def _auth_header(scopes: list[Scope]) -> dict[str, str]:
    return {"Authorization": f"Bearer {_issue_token(scopes)}"}


# ─── Outputs sintéticos ──────────────────────────────────────────────────────


def _fake_esg_output() -> ESGOutput:
    return ESGOutput(
        dossie_id="dossie-x",
        car_status="ativo",
        car_verified_at="2026-05-12T00:00:00+00:00",
        deforestation_detected=False,
        deforestation_area_ha=0.0,
        gee_satellite_images_used=3,
        vc_credential_valid=True,
        compliance_status=ESGComplianceStatus.APPROVED,
        confidence_score=0.92,
        xai_rationale={
            "decision": "approved",
            "factors": [],
            "confidence": 0.92,
            "model_version": "x",
            "timestamp": "t",
        },
    )


def _fake_financial_output() -> FinancialOutput:
    return FinancialOutput(
        dossie_id="dossie-x",
        trust_score=820.0,
        open_finance_data_months=12,
        avg_monthly_revenue_brl=85_000.0,
        debt_to_income_ratio=0.25,
        existing_rural_credit_brl=20_000.0,
        recommended_credit_limit_brl=600_000.0,
        risk_tier="A",
        xai_rationale={"decision": "ok", "factors": [], "confidence": 0.9, "model_version": "x", "timestamp": "t"},
    )


def _fake_security_output() -> SecurityOutput:
    return SecurityOutput(
        dossie_id="dossie-x",
        liveness_passed=True,
        deepfake_probability=0.05,
        voice_clone_probability=0.02,
        digital_mask_probability=0.03,
        title_verified_on_blockchain=True,
        blockchain_tx_hash="0xabc",
        fraud_risk_level="low",
        kyc_passed=True,
        xai_rationale={"decision": "low", "factors": [], "confidence": 0.97, "model_version": "x", "timestamp": "t"},
    )


# ─── Payloads de input válidos ───────────────────────────────────────────────


_ESG_INPUT = {
    "dossie_id": "dossie-x",
    "correlation_id": "corr-x",
    "tenant_id": "tenant-test",
    "car_number": "MT-1234567-ABCD1234ABCD1234",
    "holder_did": "did:gov:br:abc",
    "property_area_ha": 250.0,
    "location_lat": -12.5,
    "location_lon": -55.3,
    "location_estado": "MT",
}

_FINANCIAL_INPUT = {
    "dossie_id": "dossie-x",
    "correlation_id": "corr-x",
    "tenant_id": "tenant-test",
    "open_finance_consent_id": "CONSENT_REGULAR_001",
    "requested_amount_brl": 200_000.0,
}

_SECURITY_INPUT = {
    "dossie_id": "dossie-x",
    "correlation_id": "corr-x",
    "tenant_id": "tenant-test",
    "session_id": "session-abc",
    "media_url": "https://biometria.agrotrust.ai/x.mp4.enc",
    "car_number": "MT-1234567-ABCD1234ABCD1234",
    "owner_cpf_hash": "a" * 64,
}


# ─── Spec de cada serviço ────────────────────────────────────────────────────


_SERVICE_SPECS = [
    {
        "name": "esg",
        "dir": "agent-esg",
        "mod": "agent_esg_app",
        "scope": Scope.AGENT_ESG_RUN,
        "wrong_scope": Scope.AGENT_FINANCIAL_RUN,
        "input": _ESG_INPUT,
        "fake_output": _fake_esg_output,
    },
    {
        "name": "financial",
        "dir": "agent-financial",
        "mod": "agent_financial_app",
        "scope": Scope.AGENT_FINANCIAL_RUN,
        "wrong_scope": Scope.AGENT_ESG_RUN,
        "input": _FINANCIAL_INPUT,
        "fake_output": _fake_financial_output,
    },
    {
        "name": "security",
        "dir": "agent-security",
        "mod": "agent_security_app",
        "scope": Scope.AGENT_SECURITY_RUN,
        "wrong_scope": Scope.AGENT_FINANCIAL_RUN,
        "input": _SECURITY_INPUT,
        "fake_output": _fake_security_output,
    },
]


@pytest.fixture(params=_SERVICE_SPECS, ids=lambda s: s["name"])
def service(request: pytest.FixtureRequest) -> dict[str, Any]:
    """Carrega o módulo do serviço e retorna spec + módulo + cliente com agent mockado."""
    spec: dict[str, Any] = request.param
    module = _load_service_module(spec["dir"], spec["mod"])

    # Substitui a função `lifespan` por um placeholder no-op para evitar
    # inicialização real do agent (XGBoost/LangGraph) no startup do TestClient.
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _noop_lifespan(app):  # type: ignore[no-untyped-def]
        # injetamos um agent mockado direto em app.state
        agent_mock = AsyncMock()
        agent_mock.run = AsyncMock(return_value=spec["fake_output"]())
        app.state.agent = agent_mock
        yield

    with patch.object(module, "lifespan", _noop_lifespan):
        app = module.create_app()
        client = TestClient(app)
        with client:
            yield {"spec": spec, "module": module, "client": client}


# ─── Testes parametrizados ───────────────────────────────────────────────────


class TestHealthEndpoint:
    def test_health_returns_ok_without_auth(self, service: dict[str, Any]) -> None:
        resp = service["client"].get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["service"] == f"agent-{service['spec']['name']}"


class TestRunEndpointAuthorization:
    def test_run_without_token_returns_401(self, service: dict[str, Any]) -> None:
        resp = service["client"].post("/run", json=service["spec"]["input"])
        assert resp.status_code == 401

    def test_run_with_wrong_scope_returns_403(self, service: dict[str, Any]) -> None:
        resp = service["client"].post(
            "/run",
            json=service["spec"]["input"],
            headers=_auth_header([service["spec"]["wrong_scope"]]),
        )
        assert resp.status_code == 403

    def test_run_with_correct_scope_returns_200(self, service: dict[str, Any]) -> None:
        resp = service["client"].post(
            "/run",
            json=service["spec"]["input"],
            headers=_auth_header([service["spec"]["scope"]]),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["dossie_id"] == "dossie-x"


class TestRunEndpointErrors:
    def test_invalid_payload_returns_422(self, service: dict[str, Any]) -> None:
        bad_input = {"dossie_id": "x"}  # falta campos obrigatórios
        resp = service["client"].post(
            "/run",
            json=bad_input,
            headers=_auth_header([service["spec"]["scope"]]),
        )
        assert resp.status_code == 422
        body = resp.json()
        assert "detail" in body
        assert "correlation_id" in body

    def test_agent_execution_error_returns_500(self, service: dict[str, Any]) -> None:
        # Substitui o mock por um que levanta AgentExecutionError
        service["client"].app.state.agent.run = AsyncMock(
            side_effect=AgentExecutionError(
                correlation_id="corr-x",
                agent_name=f"{service['spec']['name'].title()}Agent",
                original_exception=RuntimeError("boom"),
            )
        )
        resp = service["client"].post(
            "/run",
            json=service["spec"]["input"],
            headers=_auth_header([service["spec"]["scope"]]),
        )
        assert resp.status_code == 500
        body = resp.json()
        assert body["detail"]["error"] == "AgentExecutionError"
        assert body["detail"]["correlation_id"] == "corr-x"


# ─── Teste isolado: scope checker direto ─────────────────────────────────────


class TestScopeCheckerHelper:
    """Testa a função _require_*_scope() isoladamente (sem servir HTTP)."""

    def test_esg_scope_checker_raises_401_without_identity(self) -> None:
        from fastapi import HTTPException

        mod = _load_service_module("agent-esg", "agent_esg_app")

        fake_request = types.SimpleNamespace(state=types.SimpleNamespace(identity=None))

        with pytest.raises(HTTPException) as exc:
            mod._require_esg_scope(fake_request)
        assert exc.value.status_code == 401

    def test_financial_scope_checker_raises_403_with_wrong_scope(self) -> None:
        from fastapi import HTTPException

        from core.security.iam import ServiceIdentity

        mod = _load_service_module("agent-financial", "agent_financial_app")

        class _FakeRequest:
            state = types.SimpleNamespace(
                identity=ServiceIdentity(
                    subject="x",
                    tenant_id="t",
                    scopes=frozenset([Scope.AGENT_ESG_RUN]),  # scope errado
                )
            )

        with pytest.raises(HTTPException) as exc:
            mod._require_financial_scope(_FakeRequest())  # type: ignore[arg-type]
        assert exc.value.status_code == 403
