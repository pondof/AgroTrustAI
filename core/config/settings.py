"""
AgroTrust AI – Configurações centralizadas com pydantic-settings.
Todas as variáveis sensíveis são lidas de env vars ou secrets; nunca hardcoded.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    DEV = "dev"
    STAGING = "staging"
    PRODUCTION = "production"


class KafkaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KAFKA_")

    bootstrap_servers: str = "localhost:9092"
    schema_registry_url: str = "http://localhost:8081"
    security_protocol: str = "PLAINTEXT"  # SASL_SSL em prod
    sasl_mechanism: str = "PLAIN"
    sasl_username: SecretStr = Field(default=SecretStr(""))
    sasl_password: SecretStr = Field(default=SecretStr(""))
    consumer_group_id: str = "agrotrust-core"
    auto_offset_reset: str = "earliest"
    enable_auto_commit: bool = False


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DB_")

    url: SecretStr = Field(default=SecretStr("postgresql+asyncpg://agrotrust:agrotrust@localhost:5432/agrotrust"))
    pool_size: int = 10
    max_overflow: int = 20
    pool_timeout: int = 30


class SecuritySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SEC_")

    jwt_secret: SecretStr = Field(default=SecretStr("CHANGE_ME_IN_PRODUCTION"))
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 30
    # Chave mestra AES-256 (32 bytes hex) – rotacionada via HSM em prod
    master_key_hex: SecretStr = Field(
        default=SecretStr("0" * 64),
        description="AES-256 master key (64 hex chars). Use HSM in production.",
    )
    tls_cert_path: str = "/run/secrets/tls.crt"
    tls_key_path: str = "/run/secrets/tls.key"
    mtls_enabled: bool = False  # True em staging/prod


class GovernmentAPISettings(BaseSettings):
    """URLs das APIs governamentais. Em dev apontam para os mocks."""

    model_config = SettingsConfigDict(env_prefix="GOV_")

    sicar_base_url: str = "http://localhost:8001"
    gee_base_url: str = "http://localhost:8002"
    dataprev_base_url: str = "http://localhost:8003"
    open_finance_base_url: str = "http://localhost:8004"
    # Timeouts em segundos (APIs gov podem ser lentas)
    request_timeout: int = 30
    max_retries: int = 3


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Environment = Environment.DEV
    service_name: str = "agrotrust-core"
    log_level: str = "INFO"
    debug: bool = False

    kafka: KafkaSettings = Field(default_factory=KafkaSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    gov_apis: GovernmentAPISettings = Field(default_factory=GovernmentAPISettings)

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in allowed:
            raise ValueError(f"log_level deve ser um de {allowed}")
        return v.upper()

    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton de configurações – use como dependência FastAPI."""
    return Settings()
