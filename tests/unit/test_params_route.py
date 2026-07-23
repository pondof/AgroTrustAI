"""
Testes de rota – GET/PUT /api/v1/params (parametrização de tolerância a risco).

Usa httpx.AsyncClient contra o app FastAPI completo, sem Kafka (ASGITransport não
dispara o lifespan). O get_session é sobrescrito para um SQLite async in-memory.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.db.engine import get_session
from core.db.repositories.params import RiskParamsCache
from core.security.iam import Scope, TokenService
from services.gateway.app import create_app

_TENANT = "tenant-alpha"


@pytest_asyncio.fixture
async def client(
    sqlite_sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    RiskParamsCache.clear()
    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with sqlite_sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = _override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
    RiskParamsCache.clear()


def _auth(scopes: list[Scope]) -> dict[str, str]:
    token = TokenService().issue_user_token("gestor-1", _TENANT, scopes)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_get_params_without_auth_is_401(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/params")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_put_params_weights_not_summing_one_is_422(client: AsyncClient) -> None:
    body = {
        "w_esg": 0.5,
        "w_financial": 0.5,
        "w_security": 0.5,  # soma 1.5 → inválido
        "approve_threshold": 600.0,
        "manual_threshold": 450.0,
        "max_dti": 0.65,
        "max_credit_multiplier": 12.0,
    }
    resp = await client.put("/api/v1/params", json=body, headers=_auth([Scope.ADMIN_PARAMS]))
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_defaults_then_put_then_get_cycle(client: AsyncClient) -> None:
    headers = _auth([Scope.ADMIN_PARAMS])

    # 1. GET inicial → defaults (não há registro ainda).
    resp = await client.get("/api/v1/params", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["tenant_id"] == _TENANT
    assert data["w_esg"] == pytest.approx(0.35)
    assert data["w_financial"] == pytest.approx(0.45)

    # 2. PUT novos pesos válidos (somam 1.0).
    body = {
        "w_esg": 0.40,
        "w_financial": 0.40,
        "w_security": 0.20,
        "approve_threshold": 650.0,
        "manual_threshold": 500.0,
        "max_dti": 0.60,
        "max_credit_multiplier": 10.0,
    }
    put = await client.put("/api/v1/params", json=body, headers=headers)
    assert put.status_code == 200
    assert put.json()["updated_by"] == "gestor-1"

    # PUT deve repovoar o cache consultado pelo VerdictEngine.
    cached = RiskParamsCache.get(_TENANT)
    assert cached is not None
    assert cached.w_esg == pytest.approx(0.40)
    assert cached.approve_threshold == pytest.approx(650.0)

    # 3. GET reflete os valores persistidos.
    resp2 = await client.get("/api/v1/params", headers=headers)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["w_esg"] == pytest.approx(0.40)
    assert data2["approve_threshold"] == pytest.approx(650.0)
    assert data2["max_credit_multiplier"] == pytest.approx(10.0)


@pytest.mark.asyncio
async def test_put_params_requires_admin_scope(client: AsyncClient) -> None:
    body = {
        "w_esg": 0.35,
        "w_financial": 0.45,
        "w_security": 0.20,
        "approve_threshold": 600.0,
        "manual_threshold": 450.0,
        "max_dti": 0.65,
        "max_credit_multiplier": 12.0,
    }
    # Token sem admin:params → 403.
    resp = await client.put("/api/v1/params", json=body, headers=_auth([Scope.SUBSCRIPTION_READ]))
    assert resp.status_code == 403
