"""Testes unitários – core/security/iam.py"""
from __future__ import annotations

import pytest

from core.security.iam import (
    ROLE_SCOPES,
    Scope,
    ServiceIdentity,
    TokenService,
    hash_password,
    verify_password,
)


@pytest.fixture
def token_service() -> TokenService:
    return TokenService()


class TestTokenService:
    def test_issue_and_verify_user_token(self, token_service: TokenService) -> None:
        scopes = [Scope.SUBSCRIPTION_READ, Scope.AUDIT_READ]
        token = token_service.issue_user_token("user-123", "sicredi-pilot", scopes)
        identity = token_service.verify(token)
        assert identity.subject == "user-123"
        assert identity.tenant_id == "sicredi-pilot"
        assert Scope.SUBSCRIPTION_READ in identity.scopes
        assert not identity.is_service

    def test_issue_and_verify_service_token(self, token_service: TokenService) -> None:
        scopes = [Scope.AGENT_ORCHESTRATE]
        token = token_service.issue_service_token("orchestrator-svc", "tenant-a", scopes, ttl_minutes=5)
        identity = token_service.verify(token)
        assert identity.is_service
        assert Scope.AGENT_ORCHESTRATE in identity.scopes

    def test_invalid_token_raises(self, token_service: TokenService) -> None:
        with pytest.raises(PermissionError):
            token_service.verify("not.a.valid.jwt")

    def test_tampered_token_raises(self, token_service: TokenService) -> None:
        token = token_service.issue_user_token("u1", "t1", [Scope.SUBSCRIPTION_READ])
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(PermissionError):
            token_service.verify(tampered)


class TestServiceIdentity:
    def test_has_scope_true(self) -> None:
        identity = ServiceIdentity(
            subject="svc-esg",
            tenant_id="tenant-1",
            scopes=frozenset([Scope.AGENT_ESG_RUN]),
        )
        assert identity.has_scope(Scope.AGENT_ESG_RUN)

    def test_has_scope_false(self) -> None:
        identity = ServiceIdentity(
            subject="svc-esg",
            tenant_id="tenant-1",
            scopes=frozenset([Scope.AGENT_ESG_RUN]),
        )
        assert not identity.has_scope(Scope.ADMIN_USERS)

    def test_require_scope_passes(self) -> None:
        identity = ServiceIdentity(
            subject="gestor",
            tenant_id="fiagro",
            scopes=frozenset([Scope.SUBSCRIPTION_APPROVE]),
        )
        identity.require_scope(Scope.SUBSCRIPTION_APPROVE)  # não deve lançar

    def test_require_scope_raises(self) -> None:
        identity = ServiceIdentity(
            subject="analista",
            tenant_id="sicredi",
            scopes=frozenset([Scope.SUBSCRIPTION_READ]),
        )
        with pytest.raises(PermissionError, match="subscription:approve"):
            identity.require_scope(Scope.SUBSCRIPTION_APPROVE)


class TestRoleScopes:
    def test_gestor_fiagro_can_approve(self) -> None:
        scopes = ROLE_SCOPES["gestor_fiagro"]
        assert Scope.SUBSCRIPTION_APPROVE in scopes

    def test_orchestrator_has_all_agent_scopes(self) -> None:
        scopes = ROLE_SCOPES["orchestrator_service"]
        assert Scope.AGENT_ESG_RUN in scopes
        assert Scope.AGENT_FINANCIAL_RUN in scopes
        assert Scope.AGENT_SECURITY_RUN in scopes

    def test_analista_cannot_approve(self) -> None:
        scopes = ROLE_SCOPES["analista_cooperativa"]
        assert Scope.SUBSCRIPTION_APPROVE not in scopes


class TestPasswordHashing:
    def test_hash_and_verify(self) -> None:
        plain = "senha-segura-cooperativa-2026"
        hashed = hash_password(plain)
        assert hashed != plain
        assert verify_password(plain, hashed)

    def test_wrong_password_fails(self) -> None:
        hashed = hash_password("senha-correta")
        assert not verify_password("senha-errada", hashed)

    def test_hashes_are_salted(self) -> None:
        plain = "mesma-senha"
        assert hash_password(plain) != hash_password(plain)
