export type SectorClass =
  | "PUBLIC_MANUFACTURER"
  | "PRIVATE_MANUFACTURER"
  | "NON_MANUFACTURER"
  | "FINANCIAL";

export type AltmanModelName = "Z_1968" | "Z_PRIME" | "Z_DOUBLE_PRIME";
export type ZoneName = "SAFE" | "GREY" | "DISTRESS" | "NOT_APPLICABLE";
export type Confidence = "COMPLETE" | "PARTIAL" | "UNUSABLE";
export type StatementTypeName = "INCOME_STATEMENT" | "BALANCE_SHEET" | "CASH_FLOW";
export type ConsensusVerdict = "LOW_RISK" | "HIGH_RISK" | "MIXED_SIGNAL" | "INDETERMINATE";
export type FScoreBand = "STRONG" | "MIXED" | "WEAK";
export type TestStatus = "PASS" | "FAIL" | "NOT_EVALUATED";
export type MarketView = "CONFIRMS" | "CONTRADICTS" | "PARTIAL" | "UNAVAILABLE";

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

/** GET /companies/summary: a company plus the headline of every stage that has run. */
export interface CompanySummary extends Company {
  ticker: string | null;
  consensus_verdict: ConsensusVerdict | null;
  altman_model: AltmanModelName | null;
  altman_zone: ZoneName | null;
  health_score: number | null;
  market_view: MarketView | null;
  merton_probability_of_default: number | null;
}

export interface FinancialStatement {
  id: string;
  company_id: string;
  statement_type: StatementTypeName;
  fiscal_year: number;
  line_items: Record<string, number>;
  source_note: string | null;
  uploaded_at: string;
}

export interface OmittedRatio {
  ratio: string;
  reason: string;
}

export interface DupontTerm {
  value: number;
  definition: string;
  meaning: string;
}

export interface DupontForm {
  terms: Record<string, DupontTerm>;
  product_roe_pct: number;
  residual_pct: number;
  reconciles: boolean;
}

export interface Dupont {
  roe?: number;
  roe_basis?: string;
  three_step?: DupontForm;
  five_step?: DupontForm;
}

export interface CycleLeg {
  days: number;
  balance_used?: number;
  balance_basis?: string;
  definition: string;
  meaning?: string;
}

export type CashConversionCycle = Partial<Record<"dio" | "dso" | "dpo" | "ccc", CycleLeg>> & {
  basis?: string | string[];
};

export interface TrendEntry {
  by_year: Record<string, number>;
  first_year: number;
  last_year: number;
  change: number;
  change_pct?: number;
  cagr_pct?: number;
  cagr_omitted?: string;
  direction: "up" | "down" | "flat";
}

export interface Trend {
  years?: number[];
  span_years?: number;
  ratios?: Record<string, TrendEntry>;
}

export interface RatioAnalysis {
  id: string;
  company_id: string;
  fiscal_year: number | null;
  dupont: Dupont;
  cash_conversion_cycle: CashConversionCycle;
  trend: Trend;
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

export interface OhlsonTerm {
  value: number;
  coefficient: number;
  contribution: number;
}

export interface VariantScore {
  score: number | null;
  zone: ZoneName;
  confidence: Confidence;
  applicable: boolean;
  x4_equity_basis?: string;
  cutoffs?: { safe_above: number; distress_below: number };
  omitted_components: OmittedComponent[];
}

export interface BankruptcyRisk {
  id: string;
  company_id: string;
  fiscal_year: number | null;
  zscore_variant: AltmanModelName | null;
  variant_scores: Partial<Record<AltmanModelName, VariantScore>>;
  ohlson_o_score: number | null;
  ohlson_probability: number | null;
  ohlson_components: Record<string, OhlsonTerm>;
  ohlson_omitted: { term: string; reason: string }[];
  consensus_verdict: ConsensusVerdict | null;
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

export interface FScoreTest {
  status: TestStatus;
  group: string;
  question: string;
  definition: string;
  meaning?: string;
  points?: number;
  reason?: string;
  [key: string]: unknown;
}

export interface MScoreComponent {
  ratio: number;
  coefficient?: number;
  contribution?: number;
}

export interface EarningsQuality {
  id: string;
  company_id: string;
  fiscal_year: number;
  prior_fiscal_year: number | null;
  piotroski_f_score: number | null;
  f_score_band: FScoreBand | null;
  f_score_components: Record<string, FScoreTest>;
  beneish_m_score: number | null;
  m_score_components: Record<string, MScoreComponent>;
  manipulation_flag: boolean | null;
  confidence: Confidence;
  omitted: { model: string; test?: string; component?: string; reason: string }[];
  calculation_basis: Record<string, any>;
  calculated_at: string;
}

export interface FcffYear {
  year: number;
  revenue: number;
  ebit: number;
  nopat: number;
  depreciation_amortization: number;
  capital_expenditure: number;
  change_in_nwc: number;
  fcff: number;
  discount_factor: number;
  present_value: number;
}

export interface DcfAssumptions {
  revenue_growth: number;
  terminal_growth: number;
  tax_rate: number;
  projection_years: number;
  risk_free_rate: number;
  equity_risk_premium: number;
  beta: number;
  wacc_override: number | null;
  cost_of_debt_override: number | null;
  ebit_margin_override: number | null;
}

export interface DcfValuation {
  id: string;
  company_id: string;
  base_fiscal_year: number | null;
  assumptions: DcfAssumptions;
  fcff_projection: FcffYear[];
  wacc: number | null;
  terminal_value: number | null;
  enterprise_value: number | null;
  equity_value: number | null;
  implied_share_price: number | null;
  upside_downside_pct: number | null;
  confidence: Confidence;
  calculation_basis: Record<string, any>;
  calculated_at: string;
}

export interface Percentiles {
  p5: number;
  p50: number;
  p95: number;
  mean: number;
  min: number;
  max: number;
  n: number;
}

export interface ScenarioRun {
  id: string;
  company_id: string;
  n_trials: number;
  seed: number;
  input_distributions: Record<string, Record<string, unknown>>;
  result_summary: {
    health_score: Percentiles | null;
    z_score: Percentiles | null;
    ohlson_probability: Percentiles | null;
    dcf_equity_value: Percentiles | null;
    dcf_implied_share_price: Percentiles | null;
    zone_shares: Partial<Record<ZoneName, number>>;
    consensus_shares: Partial<Record<ConsensusVerdict, number>>;
    distress_probability: number;
    altman_model: AltmanModelName;
    dcf_trials_refused: number;
  };
  calculation_basis: Record<string, any>;
  run_at: string;
}

export interface PeerCompany {
  id: string;
  company_id: string;
  peer_name: string;
  industry: string | null;
  fiscal_year: number | null;
  source: string;
  ratios: Record<string, number>;
  added_at: string;
}

export interface RatioBenchmark {
  value: number;
  peer_count: number;
  status: "SCORED" | "TOO_FEW_PEERS" | "ZERO_VARIANCE";
  higher_is_better: boolean;
  peer_rank?: string;
  rank?: number;
  peer_mean?: number;
  peer_stdev?: number;
  z_score?: number;
  percentile?: number;
  extrapolated?: boolean;
  extrapolation_note?: string;
  reason?: string;
}

export interface PeerBenchmark {
  company_id: string;
  peer_count: number;
  peer_names: string[];
  ratios: Record<string, RatioBenchmark>;
  category_percentiles: Record<string, number | null>;
  industry_percentile: number | null;
  omitted: OmittedRatio[];
  calculation_basis: {
    method: string;
    interpretation_limit: string;
    why_a_z_score_rather_than_a_rank: string;
    [key: string]: unknown;
  };
}

export interface QaEntry {
  question: string;
  answer: string;
  grounded_in: string[];
  refused: boolean;
  answered_by: string | null;
  dropped_citations: number;
  asked_at: string;
  report_id: string;
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
  qa_thread: QaEntry[];
  generated_by: string;
  generated_at: string;
}

// --- V3: market data and Merton ---------------------------------------------

export interface Security {
  ticker: string;
  name: string;
  currency: string;
  exchange: string | null;
  sector: string | null;
  source: string;
  observations: number;
  first_date: string | null;
  last_date: string | null;
}

export interface PricePoint {
  date: string;
  close: number;
  adj_close: number;
}

export interface SecurityDetail extends Security {
  prices: PricePoint[];
}

export interface Listing {
  company_id: string;
  ticker: string;
  benchmark_ticker: string | null;
  fiscal_year_end_month: number;
}

export interface RiskMetrics {
  annualised_return?: number;
  annualised_volatility?: number;
  sharpe_ratio?: number;
  sortino_ratio?: number;
  max_drawdown?: number;
  historical_var?: number;
  parametric_var?: number;
  expected_shortfall?: number;
  best_month?: number;
  worst_month?: number;
  observations?: number;
}

export interface MertonBasis {
  citation: string;
  naive_citation: string;
  equations: string[];
  distance_to_default: string;
  drift: string;
  inputs: {
    equity_value: number;
    equity_volatility: number;
    default_point: number;
    risk_free_rate: number;
    horizon_years: number;
    prior_year_equity_return: number | null;
  };
  solver_message?: string;
  interpretation_limit: string;
  naive_formula: string;
  equity_value_basis: string;
  default_point_basis: string;
  volatility_window_months: number;
  reported_market_value_equity?: number;
  gap_vs_reported_pct?: number;
  refusal?: string;
}

export interface MarketRisk {
  id: string;
  company_id: string;
  fiscal_year: number | null;
  ticker: string;
  merton_distance_to_default: number | null;
  merton_probability_of_default: number | null;
  naive_distance_to_default: number | null;
  naive_probability_of_default: number | null;
  asset_value: number | null;
  asset_volatility: number | null;
  beta: number | null;
  adjusted_beta: number | null;
  market_view: MarketView;
  risk_metrics: RiskMetrics;
  confidence: Confidence;
  calculation_basis: {
    fiscal_year_end: string;
    no_look_ahead: string;
    currency: string;
    merton?: Partial<MertonBasis>;
    merton_confidence?: Confidence;
    beta?: {
      benchmark: string | null;
      window_months: number;
      observations: number;
      r_squared: number | null;
      std_error: number | null;
      alpha_annual: number | null;
      adjustment: string;
      reason: string | null;
    };
    risk_metrics?: {
      risk_free_rate: number;
      var_confidence: number;
      horizon: string;
      reason: string | null;
    };
    market_view?: {
      against_consensus: ConsensusVerdict | null;
      reason: string;
      bands: { low_pd_below: number; high_pd_above: number };
    };
  };
  calculated_at: string;
}

// --- V3: Portfolio Lab -------------------------------------------------------

export type PortfolioKey =
  | "min_volatility"
  | "max_sharpe"
  | "hrp"
  | "equal_weight"
  | "inverse_volatility"
  | "efficient_return";

export interface PortfolioResult {
  weights?: Record<string, number>;
  expected_return?: number;
  volatility?: number;
  sharpe_ratio?: number;
  effective_holdings?: number;
  refusal?: string;
  tree?: { order: number[]; linkage: number[][] };
}

export interface PortfolioAsset {
  ticker: string;
  expected_return: number;
  volatility: number;
  credit_view: {
    company: string;
    consensus: ConsensusVerdict | null;
    merton_pd: number | null;
  } | null;
}

export interface RiskPoint {
  expected_return: number;
  volatility: number;
}

export interface RiskComponent {
  ticker: string;
  weight: number;
  marginal_var: number;
  component_var: number;
  share_of_risk: number;
}

export interface PortfolioResults {
  universe: {
    tickers: string[];
    currency: string;
    start: string;
    end: string;
    observations: number;
  };
  assets: PortfolioAsset[];
  correlation: number[][];
  portfolios: Partial<Record<PortfolioKey, PortfolioResult>>;
  frontier: RiskPoint[];
  random_portfolios: RiskPoint[];
  risk_decomposition?: {
    portfolio: PortfolioKey;
    confidence: number;
    horizon: string;
    portfolio_var: number;
    components: RiskComponent[];
    identity: string;
  };
  allocation?: {
    budget: number;
    shares: Record<string, number>;
    leftover_cash: number;
    realised_weights: Record<string, number>;
    tracking_rmse: number;
  };
  credit_overlay: {
    mode: CreditOverlay;
    constrained: { ticker: string; cap: number; reason: string }[];
    linked: string[];
    unlinked: string[];
  };
}

export type CreditOverlay = "none" | "exclude_high_risk" | "cap_mixed";

export interface PortfolioConfig {
  name?: string | null;
  tickers: string[];
  start_date?: string | null;
  end_date?: string | null;
  expected_returns: "mean_historical" | "ema_historical" | "capm";
  risk_model: "sample" | "ledoit_wolf";
  risk_free_rate?: number | null;
  max_weight: number;
  target_return?: number | null;
  budget?: number | null;
  credit_overlay: CreditOverlay;
  benchmark_ticker?: string | null;
}

export interface PortfolioRun {
  id: string;
  name: string | null;
  tickers: string[];
  config: PortfolioConfig;
  results: PortfolioResults;
  calculation_basis: {
    estimation: {
      method: string;
      compounding?: string;
      risk_model: string;
      shrinkage?: number;
      psd_fixed: boolean;
    };
    risk_free_rate: number;
    constraints: string;
    headline_portfolio: PortfolioKey | null;
    citations: Record<string, string>;
    inspired_by: string[];
    hrp_note: string;
    interpretation_limit: string;
  };
  run_at: string;
}

export interface PortfolioRunSummary {
  id: string;
  name: string | null;
  tickers: string[];
  run_at: string;
  headline_portfolio: PortfolioKey | null;
  expected_return: number | null;
  volatility: number | null;
  sharpe_ratio: number | null;
}

// --- V3: multi-agent research memo ---------------------------------------------

export type TraceStatus = "ok" | "fallback" | "skipped" | "error";

export interface TraceNode {
  node: string;
  status: TraceStatus;
  source: string;
  duration_ms: number;
  detail: string;
}

/** A sentence the curator dropped, with the figures it could not ground. */
export interface RemovedSentence {
  sentence: string;
  ungrounded: string[];
}

export interface MemoSection {
  key: string;
  title: string;
  headline: string;
  text: string;
  removed: RemovedSentence[];
  numbers_checked: number;
  source: string;
}

export interface Disagreement {
  kind: string;
  title: string;
  detail: string;
}

export interface ResearchMemo {
  id: string;
  company_id: string;
  memo: {
    title: string;
    executive_summary: string;
    recommendation: string;
    disagreements: Disagreement[];
  };
  sections: MemoSection[];
  trace: TraceNode[];
  curator_report: {
    figures_checked: number;
    sentences_removed: number;
    tolerance: number;
    rule: string;
    removed: (RemovedSentence & { section: string })[];
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
    ohlson?: {
      citation: string;
      coefficients: Record<string, number>;
      term_definitions: Record<string, string>;
      term_meanings: Record<string, string>;
      size_substitution: string;
      distress_cutoff_probability: number;
    };
    consensus_verdict?: {
      rule: string;
      thresholds: { low_risk_below: number; high_risk_above: number };
      mixed_signal_is_an_output: string;
    };
    piotroski?: {
      citation: string;
      tests: Record<string, { group: string; question: string; definition: string }>;
      bands: Record<string, string>;
      roa_basis: string;
      partial_policy: string;
    };
    beneish?: {
      citation: string;
      coefficients: Record<string, number>;
      component_definitions: Record<string, string>;
      component_meanings: Record<string, string>;
      thresholds: Record<string, number>;
      partial_policy: string;
    };
    dcf?: {
      status: string;
      formulas: Record<string, string>;
      defaults: Record<string, number>;
      defaults_note: string;
      beta_policy: string;
      refusals: string[];
    };
    scenario_simulator?: {
      status: string;
      default_trials: number;
      perturbation_model: string;
      distress_probability: string;
    };
    peer_benchmarking?: {
      method: string;
      minimum_peers: number;
      interpretation_limit: string;
    };
    market_data?: {
      returns: string;
      market_capitalisation: string;
      no_look_ahead: string;
      beta: string;
      risk_free_rate_for_ratios: number;
      var_confidence: number;
      minimum_observations: number;
    };
    merton?: {
      citation: string;
      naive_cross_check: string;
      default_point: string;
      volatility_window_months: number;
      horizon_years: number;
      risk_free_rates: Record<string, number>;
      market_view_bands: { low_pd_below: number; high_pd_above: number };
      financial_sector_policy: string;
    };
    portfolio_lab?: {
      inspired_by: string[];
      expected_returns: string[];
      risk_models: string[];
      optimisers: string[];
      constraints: string;
      credit_overlay: string;
      risk_decomposition: string;
      minimum_observations: number;
      refusals: string[];
    };
    research_agents?: {
      inspired_by: string;
      pipeline: string[];
      departure_from_inspiration: string;
      number_tolerance: number;
      model: string;
      effort: string;
    };
    ratio_extensions?: {
      dupont_definitions: Record<string, string>;
      cycle_definitions: Record<string, string>;
      reconciliation: string;
      cagr_policy: string;
    };
  };
  line_item_vocabulary: string[];
  benchmark_provenance: string;
  llm_output_contract?: string;
  llm_role: string;
}
