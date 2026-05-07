-- AgroTrust AI – Schema PostgreSQL inicial
-- Políticas RLS garantem que app roles não possam UPDATE/DELETE a tabela de auditoria.

CREATE SCHEMA IF NOT EXISTS agrotrust;
SET search_path = agrotrust;

-- ─── Tabela de auditoria imutável ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_log (
    id             BIGSERIAL PRIMARY KEY,
    event_id       UUID         NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    timestamp      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    event_type     TEXT         NOT NULL,
    subject        TEXT         NOT NULL,
    tenant_id      TEXT         NOT NULL,
    resource_id    TEXT         NOT NULL,
    outcome        TEXT         NOT NULL CHECK (outcome IN ('success', 'failure', 'warning')),
    details        JSONB        NOT NULL DEFAULT '{}',
    previous_hash  CHAR(64)     NOT NULL,
    entry_hash     CHAR(64)     NOT NULL UNIQUE
);

-- Nenhum UPDATE ou DELETE permitido (append-only via RLS)
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY audit_insert_only ON audit_log FOR INSERT WITH CHECK (true);
-- Revoga UPDATE/DELETE de todos os roles de aplicação
REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC;

-- ─── Dossiês de subscrição ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dossies (
    id                    UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id             TEXT         NOT NULL,
    car_number            TEXT         NOT NULL,
    producer_cpf_hash     CHAR(64)     NOT NULL,
    credit_amount_brl     NUMERIC(15,2) NOT NULL,
    credit_purpose        TEXT         NOT NULL,
    status                TEXT         NOT NULL DEFAULT 'initiated'
                          CHECK (status IN ('initiated','processing','approved','rejected','manual_review')),
    esg_score             NUMERIC(5,3),
    financial_score       NUMERIC(5,3),
    security_score        NUMERIC(5,3),
    composite_score       NUMERIC(5,3),
    verdict               TEXT,
    xai_rationale         JSONB,
    processing_time_ms    INTEGER,
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_dossies_tenant ON dossies(tenant_id);
CREATE INDEX idx_dossies_car    ON dossies(car_number);
CREATE INDEX idx_dossies_status ON dossies(status);

-- ─── Parâmetros de tolerância a risco (por tenant) ───────────────────────────
CREATE TABLE IF NOT EXISTS risk_parameters (
    id                    UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id             TEXT         NOT NULL UNIQUE,
    min_esg_score         NUMERIC(5,3) NOT NULL DEFAULT 0.6,
    min_financial_score   NUMERIC(5,3) NOT NULL DEFAULT 0.5,
    min_security_score    NUMERIC(5,3) NOT NULL DEFAULT 0.7,
    max_dti               NUMERIC(5,3) NOT NULL DEFAULT 0.65,
    max_credit_brl        NUMERIC(15,2) NOT NULL DEFAULT 5000000.00,
    auto_approve_threshold NUMERIC(5,3) NOT NULL DEFAULT 0.85,
    manual_review_threshold NUMERIC(5,3) NOT NULL DEFAULT 0.60,
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Inserir parâmetros padrão para tenant de desenvolvimento
INSERT INTO risk_parameters (tenant_id) VALUES ('dev-tenant') ON CONFLICT DO NOTHING;
INSERT INTO risk_parameters (tenant_id) VALUES ('sicredi-pilot') ON CONFLICT DO NOTHING;

-- ─── Comentários de documentação ─────────────────────────────────────────────
COMMENT ON TABLE audit_log IS 'Log de auditoria imutável – LGPD Art. 37 + Bacen. Apenas INSERT permitido.';
COMMENT ON TABLE dossies IS 'Dossiês de subscrição de crédito rural processados pelo motor multiagente.';
COMMENT ON TABLE risk_parameters IS 'Parâmetros de tolerância a risco configuráveis por tenant (Módulo C).';
