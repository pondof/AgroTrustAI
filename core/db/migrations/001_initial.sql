-- ═══════════════════════════════════════════════════════════════════════════
-- AgroTrust AI – Migração 001 (inicial) – Fase 2 (Persistência real)
--
-- SQL puro, sem Alembic. Idempotente (IF NOT EXISTS) para permitir replay.
-- Autoridade do schema de aplicação da Fase 2 (substitui docker/init-db.sql).
--
-- Tabelas: dossies (projeção de leitura), audit_log (append-only hash chain),
--          risk_params (parametrização de tolerância por tenant).
-- ═══════════════════════════════════════════════════════════════════════════

-- gen_random_uuid() vem de pgcrypto no PG < 13; no PG >= 13 é nativo.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ─── Projeção de leitura: dossiês de subscrição ──────────────────────────────
CREATE TABLE IF NOT EXISTS dossies (
    id                          UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
    dossie_id                   VARCHAR(20)    UNIQUE NOT NULL,        -- "DOS-XXXXXXXXXXXX"
    correlation_id              UUID           NOT NULL,
    tenant_id                   VARCHAR(100)   NOT NULL,
    producer_cpf_hash           CHAR(64)       NOT NULL,               -- SHA-3-256, nunca CPF em claro
    car_number                  VARCHAR(100)   NOT NULL,
    property_area_ha            NUMERIC(12,4)  NOT NULL,
    credit_amount_brl           NUMERIC(15,2)  NOT NULL,
    credit_purpose              VARCHAR(50)    NOT NULL,
    requested_by                VARCHAR(200)   NOT NULL,
    status                      VARCHAR(30)    NOT NULL DEFAULT 'initiated',
    verdict                     VARCHAR(20),                           -- approved|rejected|manual_review|NULL
    composite_score             NUMERIC(7,4),
    esg_score                   NUMERIC(7,4),
    financial_score             NUMERIC(7,4),
    security_score              NUMERIC(7,4),
    approved_amount_brl         NUMERIC(15,2),
    rejection_reasons           TEXT[],
    xai_consolidated_rationale  JSONB,
    processing_time_ms          INTEGER,
    created_at                  TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

-- Listagem por tenant ordenada por data (projeção de dossiê status/history).
-- Sem CONCURRENTLY: tabela recém-criada (vazia) e a migração roda em transação.
CREATE INDEX IF NOT EXISTS dossies_tenant_id_idx ON dossies (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS dossies_status_idx    ON dossies (tenant_id, status);


-- ─── Auditoria imutável (append-only hash chain) ─────────────────────────────
CREATE TABLE IF NOT EXISTS audit_log (
    id             BIGSERIAL     PRIMARY KEY,
    event_id       UUID          NOT NULL UNIQUE,
    timestamp      TIMESTAMPTZ   NOT NULL,
    event_type     VARCHAR(60)   NOT NULL,
    subject        VARCHAR(200)  NOT NULL,
    tenant_id      VARCHAR(100)  NOT NULL,
    resource_id    VARCHAR(100)  NOT NULL,
    outcome        VARCHAR(20)   NOT NULL,
    details        JSONB         NOT NULL,
    previous_hash  CHAR(64)      NOT NULL,
    entry_hash     CHAR(64)      NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS audit_log_resource_idx ON audit_log (resource_id);
CREATE INDEX IF NOT EXISTS audit_log_tenant_idx   ON audit_log (tenant_id, id);

-- RLS: o role de aplicação (agrotrust_app) jamais pode UPDATE/DELETE a trilha.
-- INSERT e SELECT continuam permitidos; a imutabilidade é garantida no banco,
-- não apenas na aplicação (defense-in-depth, LGPD Art. 37 + Bacen).
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS audit_select ON audit_log;
DROP POLICY IF EXISTS audit_insert ON audit_log;
DROP POLICY IF EXISTS no_update   ON audit_log;
DROP POLICY IF EXISTS no_delete   ON audit_log;

CREATE POLICY audit_select ON audit_log FOR SELECT USING (true);
CREATE POLICY audit_insert ON audit_log FOR INSERT WITH CHECK (true);
CREATE POLICY no_update    ON audit_log FOR UPDATE USING (false);
CREATE POLICY no_delete    ON audit_log FOR DELETE USING (false);


-- ─── Parametrização de tolerância a risco (por tenant) ───────────────────────
CREATE TABLE IF NOT EXISTS risk_params (
    id                     UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id              VARCHAR(100)  NOT NULL UNIQUE,
    w_esg                  NUMERIC(5,4)  NOT NULL DEFAULT 0.35,        -- peso ESG no composite
    w_financial            NUMERIC(5,4)  NOT NULL DEFAULT 0.45,
    w_security             NUMERIC(5,4)  NOT NULL DEFAULT 0.20,
    approve_threshold      NUMERIC(7,4)  NOT NULL DEFAULT 600.0,
    manual_threshold       NUMERIC(7,4)  NOT NULL DEFAULT 450.0,
    max_dti                NUMERIC(5,4)  NOT NULL DEFAULT 0.65,        -- DTI máximo para aprovação
    max_credit_multiplier  NUMERIC(5,2)  NOT NULL DEFAULT 12.0,
    updated_by             VARCHAR(200)  NOT NULL DEFAULT 'system',
    updated_at             TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT w_sum CHECK (w_esg + w_financial + w_security = 1.0)
);


-- ─── Roles de aplicação (least privilege) ────────────────────────────────────
-- Criado condicionalmente; a senha real é injetada via secret em produção.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agrotrust_app') THEN
        CREATE ROLE agrotrust_app LOGIN PASSWORD 'CHANGE_ME_IN_PRODUCTION';
    END IF;
END
$$;

GRANT SELECT, INSERT, UPDATE ON dossies      TO agrotrust_app;
GRANT SELECT, INSERT         ON audit_log     TO agrotrust_app;  -- sem UPDATE/DELETE (append-only)
GRANT USAGE                  ON SEQUENCE audit_log_id_seq TO agrotrust_app;
GRANT SELECT, INSERT, UPDATE ON risk_params   TO agrotrust_app;


-- ─── Documentação ────────────────────────────────────────────────────────────
COMMENT ON TABLE dossies     IS 'Projeção de leitura dos dossiês (status/history). Fonte de verdade é o Kafka.';
COMMENT ON TABLE audit_log   IS 'Trilha de auditoria imutável (hash chain). Apenas INSERT/SELECT via RLS.';
COMMENT ON TABLE risk_params IS 'Tolerância a risco configurável por tenant. Pesos somam 1.0 (CHECK w_sum).';
