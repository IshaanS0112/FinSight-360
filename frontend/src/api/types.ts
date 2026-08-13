export type SectorClass =
  | "PUBLIC_MANUFACTURER"
  | "PRIVATE_MANUFACTURER"
  | "NON_MANUFACTURER"
  | "FINANCIAL";

export type AltmanModelName = "Z_1968" | "Z_PRIME" | "Z_DOUBLE_PRIME";
export type ZoneName = "SAFE" | "GREY" | "DISTRESS" | "NOT_APPLICABLE";
export type Confidence = "COMPLETE" | "PARTIAL" | "UNUSABLE";
export type StatementTypeName = "INCOME_STATEMENT" | "BALANCE_SHEET" | "CASH_FLOW";

export interface Company {
  id: string;
  name: string;
  industry: string | null;
  sector_class: SectorClass;
  fiscal_year: number | null;
  currency: string;
  units: string;
  data_source: string | null;
  created_at: string;
}

export interface FinancialStatement {
  id: string;
  company_id: string;
  statement_type: StatementTypeName;
  line_items: Record<string, number>;
  source_note: string | null;
  uploaded_at: string;
}

export interface OmittedRatio {
  ratio: string;
  reason: string;
}

export interface RatioAnalysis {
  id: string;
  company_id: string;
  liquidity_ratios: Record<string, number>;
  profitability_ratios: Record<string, number>;
  leverage_ratios: Record<string, number>;
  efficiency_ratios: Record<string, number>;
  omitted_ratios: OmittedRatio[];
  calculation_basis: {
    formulas?: Record<string, string>;
    percent_ratios?: string[];
    confidence?: Confidence;
    turnover_basis?: string;
    [key: string]: unknown;
  };
  calculated_at: string;
}

export interface ZComponent {
  ratio: number;
  coefficient: number;
  contribution: number;
}

export interface OmittedComponent {
  component: string;
  reason: string;
}

export interface BankruptcyRisk {
  id: string;
  company_id: string;
  model: AltmanModelName;
  altman_z_score: number | null;
  zone: ZoneName;
  confidence: Confidence;
  component_scores: Record<string, ZComponent>;
  omitted_components: OmittedComponent[];
  calculation_basis: {
    citation?: string;
    model_selection?: string;
    formula?: string;
    component_definitions?: Record<string, string>;
    component_meanings?: Record<string, string>;
    cutoffs?: { safe_above: number; distress_below: number };
    x4_equity_basis?: string;
    borderline?: boolean;
    partial_score_warning?: string | null;
    emerging_market_constant_applied?: number | null;
    [key: string]: unknown;
  };
  calculated_at: string;
}

export interface HealthScore {
  id: string;
  company_id: string;
  overall_score: number | null;
  component_scores: Record<string, number | null>;
  peer_percentile: number | null;
  confidence: Confidence;
  calculation_basis: {
    weights_declared?: Record<string, number>;
    weights_effective?: Record<string, number>;
    components_dropped?: string[];
    renormalisation_note?: string | null;
    benchmark_provenance?: string;
    benchmark_bases_used?: string[];
    normalisation?: string;
    definition?: string;
    component_detail?: Record<string, ComponentDetail>;
    [key: string]: unknown;
  };
  calculated_at: string;
}

export interface ComponentDetail {
  ratios: Record<
    string,
    {
      status: "SCORED" | "NOT_COMPUTED" | "NO_BENCHMARK";
      value?: number;
      benchmark?: number;
      benchmark_basis?: string;
      higher_is_better?: boolean;
      unit?: string;
      score?: number;
    }
  >;
  ratios_scored: number;
  minimum_required: number;
}

export interface KeyFinding {
  metric: string;
  observation: string;
  implication: string;
}

export interface InsightReport {
  id: string;
  company_id: string;
  structured_context: Record<string, unknown>;
  ai_narrative: {
    executive_summary?: string;
    bankruptcy_risk_assessment?: string;
    key_findings?: KeyFinding[];
    data_limitations?: string;
    recommendation?: string;
    generated_by?: string;
    fallback_reason?: string;
    dropped_citations?: number;
  };
  generated_by: string;
  generated_at: string;
}

export interface Methodology {
  models: {
    ratio_engine: { formulas: Record<string, string>; note: string; turnover_basis: string };
    altman: {
      variants: Record<
        AltmanModelName,
        {
          citation: string;
          components: string[];
          coefficients: Record<string, number>;
          cutoffs: { safe_above: number; distress_below: number };
          x4_equity_basis: string;
        }
      >;
      component_definitions: Record<string, string>;
      component_meanings: Record<string, string>;
      financial_sector_policy: string;
      borderline_margin: number;
    };
    health_score: {
      status: string;
      weights: Record<string, number>;
      normalisation: string;
      peer_percentile: string;
    };
  };
  line_item_vocabulary: string[];
  benchmark_provenance: string;
  llm_role: string;
}
