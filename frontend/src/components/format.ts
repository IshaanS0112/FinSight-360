/** Display helpers shared by every schedule, so a quantity is formatted once. */

import type { ConsensusVerdict, MarketView, PortfolioKey, ZoneName } from "../api/types";

/** Ratios that are already percentages coming out of the engine. */
export const PERCENT_RATIOS = new Set(["roe", "roa", "net_margin", "gross_margin"]);

export const RATIO_LABELS: Record<string, string> = {
  current_ratio: "Current ratio",
  quick_ratio: "Quick ratio",
  roe: "Return on equity",
  roa: "Return on assets",
  net_margin: "Net margin",
  gross_margin: "Gross margin",
  debt_to_equity: "Debt-to-equity",
  interest_coverage: "Interest coverage",
  asset_turnover: "Asset turnover",
  inventory_turnover: "Inventory turnover",
};

export const CATEGORY_LABELS: Record<string, string> = {
  liquidity: "Liquidity",
  profitability: "Profitability",
  leverage: "Leverage",
  efficiency: "Efficiency",
};

export const PORTFOLIO_LABELS: Record<PortfolioKey, string> = {
  max_sharpe: "Max Sharpe",
  min_volatility: "Min volatility",
  efficient_return: "Target return",
  hrp: "HRP",
  inverse_volatility: "Inverse volatility",
  equal_weight: "Equal weight",
};

/** Display order for optimisers: the two mean-variance corners first, naive baselines last. */
export const PORTFOLIO_ORDER: PortfolioKey[] = [
  "max_sharpe",
  "min_volatility",
  "efficient_return",
  "hrp",
  "inverse_volatility",
  "equal_weight",
];

export const SECTOR_LABELS: Record<string, string> = {
  PUBLIC_MANUFACTURER: "Public manufacturer",
  PRIVATE_MANUFACTURER: "Private manufacturer",
  NON_MANUFACTURER: "Non-manufacturer",
  FINANCIAL: "Financial",
};

export const ALTMAN_LABELS: Record<string, string> = {
  Z_1968: "Z (1968)",
  Z_PRIME: "Z′",
  Z_DOUBLE_PRIME: "Z″",
};

export const VERDICT_LABELS: Record<ConsensusVerdict, string> = {
  LOW_RISK: "Low risk",
  HIGH_RISK: "High risk",
  MIXED_SIGNAL: "Mixed signal",
  INDETERMINATE: "No verdict",
};

export function ratioLabel(key: string): string {
  return RATIO_LABELS[key] ?? key.replace(/_/g, " ");
}

/** "LOW_RISK" -> "Low risk": enum values as sentence-case words. */
export function human(value: string | null | undefined): string {
  if (!value) return "—";
  const words = value.replace(/_/g, " ").toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function num(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function ratioValue(key: string, value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return PERCENT_RATIOS.has(key) ? `${num(value)}%` : num(value);
}

/** A fraction as a percentage: 0.1234 -> "12.3%". */
export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${num(value * 100, digits)}%`;
}

/** A probability that may be vanishingly small: anything under 0.01% reads "< 0.01%". */
export function probability(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value < 0.0001 ? "< 0.01%" : pct(value, 2);
}

export function signed(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return "—";
  return `${value >= 0 ? "+" : "−"}${num(Math.abs(value), digits)}`;
}

/** Large money figures, in the units the filing was reported in. */
export function money(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return Math.round(value).toLocaleString("en-US");
}

/** "2024-12-31" -> "Dec 2024". Parsed as UTC so the month never shifts with the time zone. */
export function monthYear(isoDate: string): string {
  const date = new Date(`${isoDate}T00:00:00Z`);
  return date.toLocaleDateString("en-US", { month: "short", year: "numeric", timeZone: "UTC" });
}

/** A timestamp from the API as "21 Oct 2026, 14:05" in the reader's time zone. */
export function stamp(isoDateTime: string): string {
  const date = new Date(isoDateTime.endsWith("Z") ? isoDateTime : `${isoDateTime}Z`);
  return date.toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Chip class for an Altman zone. Status colour is reserved for zones and verdicts. */
export function zoneChip(zone: ZoneName | string | null | undefined): string {
  if (zone === "SAFE") return "chip-safe";
  if (zone === "DISTRESS") return "chip-distress";
  if (zone === "GREY") return "chip-grey";
  return "chip-neutral";
}

/** Chip class for the Altman-Ohlson consensus verdict. */
export function verdictChip(verdict: ConsensusVerdict | null | undefined): string {
  if (verdict === "LOW_RISK") return "chip-safe";
  if (verdict === "HIGH_RISK") return "chip-distress";
  if (verdict === "MIXED_SIGNAL") return "chip-grey";
  return "chip-neutral";
}

/** Chip class for the market's view of the accounting verdict. Disagreement is the finding. */
export function marketViewChip(view: MarketView | null | undefined): string {
  return view === "CONTRADICTS" ? "chip-grey" : "chip-neutral";
}

/**
 * Inverse of the standard normal CDF (Acklam's rational approximation, |error| < 1.2e-9).
 * Used to place the Merton probability bands on the distance-to-default axis.
 */
export function inverseNormal(p: number): number {
  const a = [-39.6968302866538, 220.946098424521, -275.928510446969, 138.357751867269, -30.6647980661472, 2.50662827745924];
  const b = [-54.4760987982241, 161.585836858041, -155.698979859887, 66.8013118877197, -13.2806815528857];
  const c = [-0.00778489400243029, -0.322396458041136, -2.40075827716184, -2.54973253934373, 4.37466414146497, 2.93816398269878];
  const d = [0.00778469570904146, 0.32246712907004, 2.445134137143, 3.75440866190742];
  const tail = (q: number) =>
    (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
    ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  if (p < 0.02425) return tail(Math.sqrt(-2 * Math.log(p)));
  if (p > 1 - 0.02425) return -tail(Math.sqrt(-2 * Math.log(1 - p)));
  const q = p - 0.5;
  const r = q * q;
  return (
    ((((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q) /
    (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
  );
}
