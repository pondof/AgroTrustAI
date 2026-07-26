"""
Testes das rotas novas do Gateway (Fase 3):

  - POST /token                        (login dev, OAuth2 password flow)
  - GET  /api/v1/subscriptions         (listagem paginada + filtros + isolamento)
  - POST /api/v1/reports/{dossie_id}   (proxy do PDF para o report-service)
  - GET  /api/v1/subscriptions/{id}/audit-trail  (agora expõe previous_hash)

Sem Kafka nem PostgreSQL reais: SQLite async in-memory (conftest) + respx para o
report-service. O report-service em si é mockado (o gateway apenas faz proxy).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
import respx
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.db.engine import get_session
from core.db.repositories.dossie import DossieCreateDTO, DossieRepository
from core.security.audit import reset_audit_repo
from core.security.iam import Scope, TokenService
from services.gateway import routes_params
from services.gateway.app import create_app

_TENANT = "coop-demo"
_OTHER_TENANT = "coop-outra"
_CPF_HASH = "a3f5b8c2d1e4f7a0b3c6d9e2f5a8b1c4d7e0f3a6b9c2d5e8f1a4b7c0d3e6f9ab"


@pytest_asyncio.fixture
async def maker(
    sqlite_sessionmaker: async_sessionmaker[AsyncSession],
) -> async_sessionmaker[AsyncSession]:
    return sqlite_sessionmaker


@pytest_asyncio.fixture
async def client(maker: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncClient]:
    reset_audit_repo()
    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = _override_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
    reset_audit_repo()


def _auth(scopes: list[Scope], tenant: str = _TENANT) -> dict[str, str]:
    token = TokenService().issue_user_token("user-1", tenant, scopes)
    return {"Authorization": f"Bearer {token}"}


async def _seed(maker: async_sessionmaker[AsyncSession], n: int, tenant: str = _TENANT) -> list[str]:
    ids: list[str] = []
    async with maker() as session:
        repo = DossieRepository(session)
        prefix = tenant.replace("-", "").upper()[:6]
        for i in range(n):
            dossie_id = f"DOS-{prefix}{i:04d}"
            await repo.create(
                DossieCreateDTO(
                    dossie_id=dossie_id,
                    correlation_id=f"corr-{i}",
                    tenant_id=tenant,
                    producer_cpf_hash=_CPF_HASH,
                    car_number=f"MT-510760{i}-ABC",
                    property_area_ha=300.0 + i,
                    credit_amount_brl=100000.0 + i,
                    credit_purpose="custeio",
                    requested_by="analista-1",
                )
            )
            ids.append(dossie_id)
    return ids


# ─── POST /token ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_token_valid_credentials_returns_jwt(client: AsyncClient) -> None:
    resp = await client.post("/token", data={"username": "analista@agrotrust.ai", "password": "analista123"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["tenant_id"] == _TENANT
    assert "subscription:read" in body["scopes"]


@pytest.mark.asyncio
async def test_token_gestor_has_admin_params_scope(client: AsyncClient) -> None:
    resp = await client.post("/token", data={"username": "gestor@agrotrust.ai", "password": "gestor123"})
    assert resp.status_code == 200
    assert "admin:params" in resp.json()["scopes"]


@pytest.mark.asyncio
async def test_token_invalid_password_is_401(client: AsyncClient) -> None:
    resp = await client.post("/token", data={"username": "analista@agrotrust.ai", "password": "wrong"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_token_unknown_user_is_401(client: AsyncClient) -> None:
    resp = await client.post("/token", data={"username": "ninguem@x.ai", "password": "x"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_token_then_use_it_on_protected_route(client: AsyncClient) -> None:
    login = await client.post("/token", data={"username": "analista@agrotrust.ai", "password": "analista123"})
    token = login.json()["access_token"]
    resp = await client.get("/api/v1/subscriptions", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


# ─── GET /api/v1/subscriptions ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/subscriptions")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_empty_returns_zero(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/subscriptions", headers=_auth([Scope.SUBSCRIPTION_READ]))
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"items": [], "total": 0, "page": 1, "pages": 0}


@pytest.mark.asyncio
async def test_list_paginates(client: AsyncClient, maker: async_sessionmaker[AsyncSession]) -> None:
    await _seed(maker, 25)
    page1 = await client.get(
        "/api/v1/subscriptions", params={"page": 1, "limit": 10}, headers=_auth([Scope.SUBSCRIPTION_READ])
    )
    body = page1.json()
    assert body["total"] == 25
    assert body["pages"] == 3
    assert len(body["items"]) == 10

    page3 = await client.get(
        "/api/v1/subscriptions", params={"page": 3, "limit": 10}, headers=_auth([Scope.SUBSCRIPTION_READ])
    )
    assert len(page3.json()["items"]) == 5


@pytest.mark.asyncio
async def test_list_isolated_by_tenant(client: AsyncClient, maker: async_sessionmaker[AsyncSession]) -> None:
    await _seed(maker, 3, tenant=_TENANT)
    await _seed(maker, 7, tenant=_OTHER_TENANT)
    resp = await client.get("/api/v1/subscriptions", headers=_auth([Scope.SUBSCRIPTION_READ], tenant=_TENANT))
    assert resp.json()["total"] == 3


@pytest.mark.asyncio
async def test_list_filter_by_status(client: AsyncClient, maker: async_sessionmaker[AsyncSession]) -> None:
    await _seed(maker, 4)  # todos 'initiated'
    resp = await client.get(
        "/api/v1/subscriptions", params={"status": "approved"}, headers=_auth([Scope.SUBSCRIPTION_READ])
    )
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_list_item_shape_has_cpf_hash_not_plain_cpf(
    client: AsyncClient, maker: async_sessionmaker[AsyncSession]
) -> None:
    await _seed(maker, 1)
    resp = await client.get("/api/v1/subscriptions", headers=_auth([Scope.SUBSCRIPTION_READ]))
    item = resp.json()["items"][0]
    assert item["producer_cpf_hash"] == _CPF_HASH
    assert item["status"] == "initiated"
    assert item["credit_amount_brl"] == 100000.0


# ─── audit-trail expõe previous_hash ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_trail_exposes_previous_hash(client: AsyncClient) -> None:
    login = await client.post("/token", data={"username": "analista@agrotrust.ai", "password": "analista123"})
    # O login já gerou uma entrada de auditoria (auth.success) — mas para um dossiê
    # precisamos de um evento com resource_id = dossie_id. Usamos o audit repo direto.
    from core.security.audit import AuditEventType, get_audit_repo

    audit = get_audit_repo()
    await audit.append(
        event_type=AuditEventType.SUBSCRIPTION_INITIATED,
        subject="analista@agrotrust.ai",
        tenant_id=_TENANT,
        resource_id="DOS-XYZ",
        outcome="success",
        details={"car_number": "MT-1"},
    )
    token = login.json()["access_token"]
    resp = await client.get(
        "/api/v1/subscriptions/DOS-XYZ/audit-trail", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    entry = resp.json()["entries"][0]
    assert "previous_hash" in entry
    assert "entry_hash" in entry
    assert entry["tenant_id"] == _TENANT
    # A canônica enviada ao cliente deve, de fato, produzir o entry_hash (SHA-3-256).
    from core.security.crypto import sha3_256

    assert sha3_256(entry["canonical"].encode()) == entry["entry_hash"]


# ─── POST /api/v1/reports/{dossie_id} (proxy) ────────────────────────────────


@pytest.mark.asyncio
async def test_report_missing_dossie_is_404(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/reports/DOS-NOPE", headers=_auth([Scope.SUBSCRIPTION_READ]))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_report_proxies_pdf(client: AsyncClient, maker: async_sessionmaker[AsyncSession]) -> None:
    ids = await _seed(maker, 1)
    dossie_id = ids[0]
    fake_pdf = b"%PDF-1.7\n%mock signed pdf\n%%EOF"
    with respx.mock:
        route = respx.post(f"{routes_params.REPORT_SERVICE_URL}/reports/{dossie_id}").mock(
            return_value=httpx.Response(200, content=fake_pdf, headers={"Content-Type": "application/pdf"})
        )
        resp = await client.post(f"/api/v1/reports/{dossie_id}", headers=_auth([Scope.SUBSCRIPTION_READ]))
    assert route.called
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.headers["content-disposition"] == f'attachment; filename="agrotrust_{dossie_id}.pdf"'
    assert resp.content == fake_pdf


@pytest.mark.asyncio
async def test_report_upstream_error_is_502(client: AsyncClient, maker: async_sessionmaker[AsyncSession]) -> None:
    ids = await _seed(maker, 1)
    dossie_id = ids[0]
    with respx.mock:
        respx.post(f"{routes_params.REPORT_SERVICE_URL}/reports/{dossie_id}").mock(
            return_value=httpx.Response(500, text="boom")
        )
        resp = await client.post(f"/api/v1/reports/{dossie_id}", headers=_auth([Scope.SUBSCRIPTION_READ]))
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_report_isolated_by_tenant(client: AsyncClient, maker: async_sessionmaker[AsyncSession]) -> None:
    ids = await _seed(maker, 1, tenant=_OTHER_TENANT)
    # Usuário do _TENANT não pode gerar relatório de dossiê de outro tenant → 404.
    resp = await client.post(f"/api/v1/reports/{ids[0]}", headers=_auth([Scope.SUBSCRIPTION_READ], tenant=_TENANT))
    assert resp.status_code == 404
