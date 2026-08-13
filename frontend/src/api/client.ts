import type {
  BankruptcyRisk,
  Company,
  FinancialStatement,
  HealthScore,
  InsightReport,
  Methodology,
  RatioAnalysis,
  SectorClass,
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
  line_items: Record<string, number>;
  source_note?: string | null;
}

export const api = {
  methodology: () => request<Methodology>("/methodology"),

  listCompanies: () => request<Company[]>("/companies"),
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
    request<{ company_id: string; currency: string; units: string; line_items: Record<string, number> }>(
      `/companies/${id}/line-items`,
    ),

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
};
