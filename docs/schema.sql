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

-- ============================================================================
-- V2 delta
-- ============================================================================
--
-- create_all still builds this from the models on a fresh database. The
-- statements below are what an EXISTING V1 deployment needs, and they are the
-- reason the V1 note about Alembic is now overdue rather than theoretical: one
-- of these changes a column's nullability, which create_all will not do to a
-- table that already exists.

-- Multi-year ingestion. The default is a migration device only: the application
-- rejects an undated statement, so no new row can carry 0.
ALTER TABLE financial_statements ADD COLUMN fiscal_year INT NOT NULL DEFAULT 0;
UPDATE financial_statements fs
   SET fiscal_year = COALESCE(c.fiscal_year, 0)
  FROM companies c
 WHERE c.id = fs.company_id;
CREATE INDEX idx_financial_statements_company_year
    ON financial_statements (company_id, fiscal_year, statement_type);

-- Ratio analyses gain the year they describe and the three V2 blocks. None of
-- the three is a ratio: DuPont is an identity that decomposes one, the cycle is
-- a day count, the trend block compares years.
ALTER TABLE ratio_analyses ADD COLUMN fiscal_year INT;
ALTER TABLE ratio_analyses ADD COLUMN dupont JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE ratio_analyses ADD COLUMN cash_conversion_cycle JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE ratio_analyses ADD COLUMN trend JSONB NOT NULL DEFAULT '{}'::jsonb;

-- bankruptcy_risk holds a suite now, not a score. The V1 columns keep their
-- meaning exactly: `model` and `altman_z_score` are still the applicable variant
-- and its score. consensus_verdict stays NULL for an Altman-only run rather than
-- claiming agreement with a model that was never evaluated.
ALTER TABLE bankruptcy_risk ADD COLUMN fiscal_year INT;
ALTER TABLE bankruptcy_risk ADD COLUMN zscore_variant VARCHAR(20);
ALTER TABLE bankruptcy_risk ADD COLUMN variant_scores JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE bankruptcy_risk ADD COLUMN ohlson_o_score DOUBLE PRECISION;
ALTER TABLE bankruptcy_risk ADD COLUMN ohlson_probability DOUBLE PRECISION;  -- e^O / (1+e^O)
ALTER TABLE bankruptcy_risk ADD COLUMN ohlson_components JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE bankruptcy_risk ADD COLUMN ohlson_omitted JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE bankruptcy_risk ADD COLUMN consensus_verdict VARCHAR(20);

-- A Q&A thread beside the narrative. Appended to, never rewritten: a refusal
-- that a later, richer context could have answered is part of the record.
ALTER TABLE insight_reports ADD COLUMN qa_thread JSONB NOT NULL DEFAULT '[]'::jsonb;

CREATE TABLE earnings_quality (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id           UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    fiscal_year          INT NOT NULL,
    prior_fiscal_year    INT,
    -- 0-9, or NULL when too few of the nine tests could be evaluated. A partial
    -- F-Score is not a low F-Score.
    piotroski_f_score    INT,
    f_score_band         VARCHAR(20),          -- STRONG | MIXED | WEAK
    f_score_components   JSONB NOT NULL DEFAULT '{}'::jsonb,
    beneish_m_score      DOUBLE PRECISION,
    m_score_components   JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- Beneish's own -1.78 cutoff. The stricter -2.22 verdict lives in
    -- calculation_basis: promoting one threshold to a column would quietly pick
    -- a side in a disagreement the literature has not settled.
    manipulation_flag    BOOLEAN,
    confidence           VARCHAR(20) NOT NULL,
    omitted              JSONB NOT NULL DEFAULT '[]'::jsonb,
    calculation_basis    JSONB NOT NULL DEFAULT '{}'::jsonb,
    calculated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_earnings_quality_company_id ON earnings_quality (company_id);

CREATE TABLE dcf_valuation (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id           UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    base_fiscal_year     INT,
    -- A DCF is a function of its assumptions and almost nothing else. Storing
    -- the output without them would be storing an opinion with the reasoning
    -- deleted.
    assumptions          JSONB NOT NULL DEFAULT '{}'::jsonb,
    fcff_projection      JSONB NOT NULL DEFAULT '[]'::jsonb,
    wacc                 DOUBLE PRECISION,
    terminal_value       DOUBLE PRECISION,
    enterprise_value     DOUBLE PRECISION,
    equity_value         DOUBLE PRECISION,
    implied_share_price  DOUBLE PRECISION,
    upside_downside_pct  DOUBLE PRECISION,
    confidence           VARCHAR(20) NOT NULL,
    calculation_basis    JSONB NOT NULL DEFAULT '{}'::jsonb,
    calculated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_dcf_valuation_company_id ON dcf_valuation (company_id);

CREATE TABLE scenario_runs (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id           UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    n_trials             INT NOT NULL,
    -- Stored, not logged. A simulation whose distribution cannot be regenerated
    -- exactly is an anecdote.
    seed                 INT NOT NULL,
    input_distributions  JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_summary       JSONB NOT NULL DEFAULT '{}'::jsonb,
    calculation_basis    JSONB NOT NULL DEFAULT '{}'::jsonb,
    run_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_scenario_runs_company_id ON scenario_runs (company_id);

CREATE TABLE peer_companies (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id   UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    peer_name    VARCHAR(200) NOT NULL,
    industry     VARCHAR(100),
    fiscal_year  INT,
    -- Required for the same reason companies.data_source is: a peer with no
    -- citation is not a comparison point, it is a number someone typed.
    source       VARCHAR(500) NOT NULL,
    ratios       JSONB NOT NULL DEFAULT '{}'::jsonb,
    added_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_peer_companies_company_id ON peer_companies (company_id);

-- Note on naming: the V2 specification calls the health-score percentile column
-- `industry_percentile`. V1 shipped it as `financial_health_scores.peer_percentile`
-- and that name is kept, because renaming a live column to match a document is
-- churn. It is the same field, and V2 finally populates it - see
-- services/peer_benchmarking.py.
