"""
Teste de integração – API Gateway end-to-end (httpx.AsyncClient contra o app completo).

Sem Kafka real: o producer é substituído por um fake em app.state e o get_session
aponta para um SQLite async in-memory. Valida o ciclo POST → GET → audit-trail.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.db.engine import get_session
from core.events.schemas import BaseEvent
from core.security.audit import reset_audit_repo
from core.security.iam import Scope, TokenService
from services.gateway.app import create_app

_TENANT = "tenant-alpha"
_CPF_HASH = "a3f5b8c2d1e4f7a0b3c6d9e2f5a8b1c4d7e0f3a6b9c2d5e8f1a4b7c0d3e6f9ab"


class _FakeProducer:
    """Producer Kafka fake: registra o que foi publicado, sem rede."""

    def __init__(self) -> None:
        self.published: list[tuple[str, BaseEvent]] = []

    async def publish(self, topic: str, event: BaseEvent, partition_key: str | None = None) -> None:
        self.published.append((topic, event))

    async def stop(self) -> None:  # pragma: no cover
        pass


@pytest_asyncio.fixture
async def client(
    sqlite_sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    reset_audit_repo()
    app = create_app()
    app.state.kafka_producer = _FakeProducer()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with sqlite_sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = _override_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
    reset_audit_repo()


def _auth(scopes: list[Scope]) -> dict[str, str]:
    token = TokenService().issue_user_token("analista-1", _TENANT, scopes)
    return {"Authorization": f"Bearer {token}"}


def _subscription_body() -> dict[str, Any]:
    return {
        "producer_cpf_hash": _CPF_HASH,
        "car_number": "MT-5107602-ABC",
        "property_area_ha": 300.0,
        "location": {
            "latitude": -12.5,
            "longitude": -55.3,
            "municipio": "Sorriso",
            "estado": "MT",
            "biome": "Cerrado",
        },
        "credit_amount_brl": 120000.0,
        "credit_purpose": "custeio",
        "requested_by": "analista-1",
    }


@pytest.mark.asyncio
async def test_post_subscription_returns_202_with_correlation_id(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/subscriptions",
        json=_subscription_body(),
        headers=_auth([Scope.SUBSCRIPTION_WRITE]),
    )
    assert resp.status_code == 202
    assert "X-Correlation-ID" in resp.headers
    data = resp.json()
    assert data["dossie_id"].startswith("DOS-")
    assert data["status"] == "initiated"
    assert data["correlation_id"] == resp.headers["X-Correlation-ID"]


@pytest.mark.asyncio
async def test_get_missing_subscription_returns_404(client: AsyncClient) -> None:
    resp = await client.get(
        "/api/v1/subscriptions/DOS-DOESNOTEXIST",
        headers=_auth([Scope.SUBSCRIPTION_READ]),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_audit_trail_lists_entries_after_post(client: AsyncClient) -> None:
    post = await client.post(
        "/api/v1/subscriptions",
        json=_subscription_body(),
        headers=_auth([Scope.SUBSCRIPTION_WRITE]),
    )
    dossie_id = post.json()["dossie_id"]

    trail = await client.get(
        f"/api/v1/subscriptions/{dossie_id}/audit-trail",
        headers=_auth([Scope.AUDIT_READ]),
    )
    assert trail.status_code == 200
    body = trail.json()
    assert body["dossie_id"] == dossie_id
    assert body["total"] >= 1
    assert body["entries"][0]["event_type"] == "subscription.initiated"
    # Nunca vaza CPF em claro na trilha (apenas hash em details).
    assert _CPF_HASH not in trail.text or "producer_cpf_hash" not in trail.text


@pytest.mark.asyncio
async def test_missing_bearer_token_is_401(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/subscriptions", json=_subscription_body())
    assert resp.status_code == 401
