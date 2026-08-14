import type { HealthScore, RatioAnalysis } from "../api/types";

const CATEGORIES = [
  { key: "liquidity_ratios", label: "Liquidity" },
  { key: "profitability_ratios", label: "Profitability" },
  { key: "leverage_ratios", label: "Leverage" },
  { key: "efficiency_ratios", label: "Efficiency" },
] as const;

const RATIO_LABEL: Record<string, string> = {
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

/**
 * Ratios by category, each with the benchmark it was compared against.
 *
 * The omitted-ratios block at the bottom carries as much weight as the table
 * above it. A ratio missing without explanation reads as a bug; a ratio missing
 * with a reason is a finding about the filing.
 */
export default function RatioDashboard({
  ratios,
  health,
}: {
  ratios: RatioAnalysis;
  health: HealthScore | null;
}) {
  const percentRatios = new Set(ratios.calculation_basis.percent_ratios ?? []);
  const detail = health?.calculation_basis.component_detail ?? {};

  const benchmarkFor = (ratioKey: string) => {
    for (const component of Object.values(detail)) {
      const entry = component.ratios?.[ratioKey];
      if (entry?.status === "SCORED") return entry;
    }
    return null;
  };

  return (
    <section className="panel p-5">
      <h2 className="mb-1 text-sm font-semibold uppercase tracking-wider text-muted">
        Ratio analysis
      </h2>
      <p className="mb-4 text-xs text-muted">
        Arithmetic over reported line items. Turnover uses{" "}
        {(ratios.calculation_basis.turnover_basis ?? "").toLowerCase().replace("_", " ")}.
      </p>

      <div className="grid gap-5 sm:grid-cols-2">
        {CATEGORIES.map(({ key, label }) => {
          const values = ratios[key];
          return (
            <div key={key}>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-accent">
                {label}
              </h3>
              {Object.keys(values).length === 0 ? (
                <p className="text-xs text-muted">Nothing computable in this category.</p>
              ) : (
                <ul className="space-y-2">
                  {Object.entries(values).map(([ratioKey, value]) => {
                    const suffix = percentRatios.has(ratioKey) ? "%" : "×";
                    const scored = benchmarkFor(ratioKey);
                    return (
                      <li key={ratioKey} className="text-xs">
                        <div className="flex items-baseline justify-between gap-2">
                          <span className="text-slate-300">
                            {RATIO_LABEL[ratioKey] ?? ratioKey}
                          </span>
                          <span className="stat text-slate-100">
                            {value.toFixed(2)}
                            <span className="text-muted">{suffix}</span>
                          </span>
                        </div>
                        {scored && (
                          <div className="mt-0.5 flex items-baseline justify-between gap-2 text-[11px] text-muted">
                            <span>
                              vs {scored.benchmark?.toFixed(2)} ({scored.benchmark_basis})
                            </span>
                            <span
                              className={
                                (scored.score ?? 50) >= 50 ? "text-safe" : "text-distress"
                              }
                            >
                              {scored.score?.toFixed(0)}/100
                            </span>
                          </div>
                        )}
                        <div className="mt-0.5 font-mono text-[10px] text-edge">
                          {ratios.calculation_basis.formulas?.[ratioKey]}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          );
        })}
      </div>

      {ratios.omitted_ratios.length > 0 && (
        <div className="mt-5 rounded border border-edge bg-ink p-3 text-xs">
          <p className="mb-2 font-medium text-grey">
            {ratios.omitted_ratios.length} ratio
            {ratios.omitted_ratios.length === 1 ? "" : "s"} not computed
          </p>
          <ul className="space-y-1.5 text-muted">
            {ratios.omitted_ratios.map((entry) => (
              <li key={entry.ratio} className="leading-relaxed">
                <span className="text-slate-400">{RATIO_LABEL[entry.ratio] ?? entry.ratio}</span>{" "}
               , {entry.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
