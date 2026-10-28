import type {
  BankruptcyRisk,
  Company,
  CompanySummary,
  DcfAssumptions,
  DcfValuation,
  EarningsQuality,
  FinancialStatement,
  HealthScore,
  InsightReport,
  Listing,
  MarketRisk,
  Methodology,
  PeerBenchmark,
  PeerCompany,
  PortfolioConfig,
  PortfolioRun,
  PortfolioRunSummary,
  QaEntry,
  RatioAnalysis,
  ResearchMemo,
  ScenarioRun,
  SectorClass,
  Security,
  SecurityDetail,
  StatementTypeName,
} from "./types";

// In dev, Vite proxies /api -> :8000. In the Docker image, nginx does the same.
// Either way the browser only ever talks to its own origin.
const BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });

  if (!response.ok) {
    let detail: unknown;
    try {
      detail = (await response.json()).detail;
    } catch {
      detail = await response.text();
    }
    // FastAPI's detail is a string for our explicit HTTPExceptions and an array
    // of error objects for request-validation failures.
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail
              .map((d: any) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg}`)
              .join("; ")
          : `Request failed (${response.status})`;
    throw new ApiError(message, response.status, detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** A 404 from a stage that has not been run yet is expected, not an error. */
export async function optional<T>(promise: Promise<T>): Promise<T | null> {
  try {
    return await promise;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export interface CompanyDraft {
  name: string;
  industry?: string | null;
  sector_class: SectorClass;
  fiscal_year?: number | null;
  currency: string;
  units: string;
  data_source: string;
}

export interface StatementDraft {
  statement_type: StatementTypeName;
  fiscal_year?: number | null;
  line_items: Record<string, number>;
  source_note?: string | null;
}

/** Every field optional: an omitted assumption falls back to a declared default,
 *  and the default that was used comes back in the stored assumptions. */
export type DcfDraft = Partial<Omit<DcfAssumptions, "projection_years">> & {
  projection_years?: number;
};

export interface ShockDraft {
  distribution: "TRIANGULAR" | "NORMAL";
  low?: number;
  mode?: number;
  high?: number;
  mu?: number;
  sigma?: number;
}

export interface ScenarioDraft {
  n_trials?: number;
  seed?: number;
  distributions?: Record<string, ShockDraft>;
  dcf?: DcfDraft;
  include_dcf?: boolean;
}

export interface ListingDraft {
  ticker: string;
  benchmark_ticker?: string | null;
  fiscal_year_end_month: number;
}

export interface PeerDraft {
  peer_name: string;
  industry?: string | null;
  fiscal_year?: number | null;
  source: string;
  ratios: Record<string, number>;
}

export const api = {
  methodology: () => request<Methodology>("/methodology"),

  listCompanies: () => request<Company[]>("/companies"),
  companySummaries: () => request<CompanySummary[]>("/companies/summary"),
  getCompany: (id: string) => request<Company>(`/companies/${id}`),
  createCompany: (body: CompanyDraft) =>
    request<Company>("/companies", { method: "POST", body: JSON.stringify(body) }),
  deleteCompany: (id: string) => request<void>(`/companies/${id}`, { method: "DELETE" }),

  listStatements: (id: string) =>
    request<FinancialStatement[]>(`/companies/${id}/financial-statements`),
  uploadStatement: (id: string, body: StatementDraft) =>
    request<FinancialStatement>(`/companies/${id}/financial-statements`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  lineItems: (id: string) =>
    request<{
      company_id: string;
      currency: string;
      units: string;
      fiscal_year: number | null;
      fiscal_years_on_file: number[];
      line_items: Record<string, number>;
      line_items_by_year: Record<string, Record<string, number>>;
    }>(`/companies/${id}/line-items`),

  runRatios: (id: string) =>
    request<RatioAnalysis>(`/companies/${id}/compute-ratios`, { method: "POST" }),
  getRatios: (id: string) => request<RatioAnalysis>(`/companies/${id}/ratio-analysis`),

  runRisk: (id: string, body: { model?: string | null; emerging_market_adjustment?: boolean } = {}) =>
    request<BankruptcyRisk>(`/companies/${id}/compute-bankruptcy-risk`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getRisk: (id: string) => request<BankruptcyRisk>(`/companies/${id}/bankruptcy-risk`),

  runHealth: (id: string) =>
    request<HealthScore>(`/companies/${id}/compute-health-score`, { method: "POST" }),
  getHealth: (id: string) => request<HealthScore>(`/companies/${id}/health-score`),

  runInsights: (id: string) =>
    request<InsightReport>(`/companies/${id}/generate-insights`, { method: "POST" }),
  getInsights: (id: string) => request<InsightReport>(`/companies/${id}/insights-report`),

  runFullAnalysis: (id: string) =>
    request<InsightReport>(`/companies/${id}/run-full-analysis`, { method: "POST" }),

  // --- V2 ---------------------------------------------------------------
  runEarningsQuality: (id: string) =>
    request<EarningsQuality>(`/companies/${id}/compute-earnings-quality`, { method: "POST" }),
  getEarningsQuality: (id: string) => request<EarningsQuality>(`/companies/${id}/earnings-quality`),

  runValuation: (id: string, body: DcfDraft = {}) =>
    request<DcfValuation>(`/companies/${id}/compute-valuation`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getValuation: (id: string) => request<DcfValuation>(`/companies/${id}/valuation`),

  runScenario: (id: string, body: ScenarioDraft = {}) =>
    request<ScenarioRun>(`/companies/${id}/run-scenario`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  listScenarios: (id: string) => request<ScenarioRun[]>(`/companies/${id}/scenario-results`),

  getPeerSet: (id: string) => request<PeerCompany[]>(`/companies/${id}/peer-set`),
  replacePeerSet: (id: string, peers: PeerDraft[]) =>
    request<PeerCompany[]>(`/companies/${id}/peer-set`, {
      method: "POST",
      body: JSON.stringify({ peers }),
    }),
  getPeerBenchmark: (id: string) => request<PeerBenchmark>(`/companies/${id}/peer-benchmark`),

  ask: (id: string, question: string) =>
    request<QaEntry>(`/companies/${id}/insights/ask`, {
      method: "POST",
      body: JSON.stringify({ question }),
    }),

  // --- V3 ---------------------------------------------------------------
  listSecurities: () => request<Security[]>("/market/securities"),
  getSecurity: (ticker: string) =>
    request<SecurityDetail>(`/market/securities/${encodeURIComponent(ticker)}`),

  getListing: (id: string) => request<Listing>(`/companies/${id}/listing`),
  setListing: (id: string, body: ListingDraft) =>
    request<Listing>(`/companies/${id}/listing`, { method: "PUT", body: JSON.stringify(body) }),
  runMarketRisk: (id: string) =>
    request<MarketRisk>(`/companies/${id}/compute-market-risk`, {
      method: "POST",
      body: JSON.stringify({}),
    }),
  getMarketRisk: (id: string) => request<MarketRisk>(`/companies/${id}/market-risk`),

  runResearchMemo: (id: string) =>
    request<ResearchMemo>(`/companies/${id}/research-memo`, { method: "POST" }),
  getResearchMemo: (id: string) => request<ResearchMemo>(`/companies/${id}/research-memo`),

  optimizePortfolio: (body: PortfolioConfig) =>
    request<PortfolioRun>("/portfolio/optimize", { method: "POST", body: JSON.stringify(body) }),
  portfolioRuns: (limit = 10) =>
    request<PortfolioRunSummary[]>(`/portfolio/runs/summary?limit=${limit}`),
  getPortfolioRun: (id: string) => request<PortfolioRun>(`/portfolio/runs/${id}`),
};
