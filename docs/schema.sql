-- FinSight 360 schema, as deployed on PostgreSQL 16.
--
-- The application creates this itself at startup via SQLAlchemy's create_all,
-- which is adequate while the schema is append-only. This file is the readable
-- reference, and it is what to diff against once Alembic is introduced.
--
-- Two things are load-bearing and easy to miss:
--
-- 1. Analysis tables are APPEND-ONLY. Re-running a stage after correcting a
--    statement inserts a new row; the earlier result stays. "The number changed
--    when we fixed the filing" is the audit trail this kind of tool needs.
--
-- 2. Nothing that can legitimately be negative is constrained to be positive.
--    retained_earnings, shareholder_equity, altman_z_score and net_income all
--    go negative for exactly the companies this system exists to score.

CREATE TABLE companies (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          VARCHAR(200) NOT NULL,
    industry      VARCHAR(100),
    -- Decides which Altman variant is valid. FINANCIAL means no score at all.
    sector_class  VARCHAR(30)  NOT NULL,
    fiscal_year   INT,
    currency      VARCHAR(3)   NOT NULL DEFAULT 'USD',
    units         VARCHAR(20)  NOT NULL DEFAULT 'MILLIONS',
    -- Required at the API layer: a company with no filing provenance is a guess.
    data_source   VARCHAR(500),
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE financial_statements (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    statement_type  VARCHAR(30) NOT NULL,  -- INCOME_STATEMENT | BALANCE_SHEET | CASH_FLOW
    -- Free-shaped because filings disclose different lines. Keys are validated
    -- against the closed vocabulary in app/services/line_items.py at the API layer.
    line_items      JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_note     VARCHAR(500),
    uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_financial_statements_company_id ON financial_statements (company_id);

CREATE TABLE ratio_analyses (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id            UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    liquidity_ratios      JSONB NOT NULL DEFAULT '{}'::jsonb,
    profitability_ratios  JSONB NOT NULL DEFAULT '{}'::jsonb,
    leverage_ratios       JSONB NOT NULL DEFAULT '{}'::jsonb,
    efficiency_ratios     JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- [{ratio, reason}] - an analytical finding, not a debug detail.
    omitted_ratios        JSONB NOT NULL DEFAULT '[]'::jsonb,
    calculation_basis     JSONB NOT NULL DEFAULT '{}'::jsonb,
    calculated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_ratio_analyses_company_id ON ratio_analyses (company_id);

CREATE TABLE bankruptcy_risk (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id          UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    model               VARCHAR(30) NOT NULL,   -- Z_1968 | Z_PRIME | Z_DOUBLE_PRIME
    -- NULL for a financial-sector issuer, or when no component was computable.
    altman_z_score      DOUBLE PRECISION,
    zone                VARCHAR(20) NOT NULL,   -- SAFE | GREY | DISTRESS | NOT_APPLICABLE
    confidence          VARCHAR(20) NOT NULL,   -- COMPLETE | PARTIAL | UNUSABLE
    -- {x1..x5: {ratio, coefficient, contribution}}
    component_scores    JSONB NOT NULL DEFAULT '{}'::jsonb,
    omitted_components  JSONB NOT NULL DEFAULT '[]'::jsonb,
    calculation_basis   JSONB NOT NULL DEFAULT '{}'::jsonb,
    calculated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_bankruptcy_risk_company_id ON bankruptcy_risk (company_id);

CREATE TABLE financial_health_scores (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id         UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    overall_score      DOUBLE PRECISION,
    component_scores   JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- Always NULL in V1. A percentile over a handful of peers presented as an
    -- industry position would be a claim this dataset cannot support.
    peer_percentile    DOUBLE PRECISION,
    confidence         VARCHAR(20) NOT NULL,
    calculation_basis  JSONB NOT NULL DEFAULT '{}'::jsonb,
    calculated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_financial_health_scores_company_id ON financial_health_scores (company_id);

CREATE TABLE insight_reports (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id          UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    -- Stored beside the narrative on purpose: every figure the narrative may
    -- mention exists here first, so "the LLM did not invent this" is checkable
    -- by diffing the two rather than taken on trust.
    structured_context  JSONB NOT NULL DEFAULT '{}'::jsonb,
    ai_narrative        JSONB NOT NULL DEFAULT '{}'::jsonb,
    generated_by        VARCHAR(30) NOT NULL,   -- llm | template_fallback
    generated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_insight_reports_company_id ON insight_reports (company_id);
