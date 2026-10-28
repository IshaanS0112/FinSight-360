import ScheduleCard from "../components/ScheduleCard";
import { EmptyState } from "../components/States";
import TrendSparkline from "../components/TrendSparkline";
import { CATEGORY_LABELS, num, ratioLabel, ratioValue, signed } from "../components/format";
import type { HealthScore, RatioAnalysis } from "../api/types";

const SCHEDULES = [
  { key: "liquidity", bucket: "liquidity_ratios" },
  { key: "profitability", bucket: "profitability_ratios" },
  { key: "leverage", bucket: "leverage_ratios" },
  { key: "efficiency", bucket: "efficiency_ratios" },
] as const;

export default function RatioSchedules({
  ratios,
  health,
}: {
  ratios: RatioAnalysis | null;
  health: HealthScore | null;
}) {
  if (!ratios) {
    return (
      <EmptyState title="No ratio schedules yet">
        Run the analysis to compute the ten ratios, the DuPont identity and the cash conversion cycle.
      </EmptyState>
    );
  }

  const formulas = ratios.calculation_basis.formulas ?? {};
  const trend = ratios.trend?.ratios ?? {};
  const detail = health?.calculation_basis?.component_detail ?? {};

  return (
    <div className="space-y-6">
      {SCHEDULES.map((schedule, index) => {
        const bucket = ratios[schedule.bucket] as Record<string, number>;
        const scored = detail[schedule.key]?.ratios ?? {};
        return (
          <ScheduleCard
            key={schedule.key}
            reference={`Schedule ${index + 1}`}
            title={CATEGORY_LABELS[schedule.key]}
            aside={
              <span className="chip-neutral">
                {Object.keys(bucket).length} computed
              </span>
            }
          >
            <div className="overflow-x-auto">
              <table className="ledger">
                <thead>
                  <tr>
                    <th>Ratio</th>
                    <th>Formula</th>
                    <th className="text-right">FY{ratios.fiscal_year}</th>
                    <th className="text-right">Benchmark</th>
                    <th className="text-right">Δ</th>
                    <th className="text-right">Trend</th>
                    <th className="text-right">CAGR</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(bucket).map(([key, value]) => {
                    const scoredEntry = scored[key];
                    const entry = trend[key];
                    return (
                      <tr key={key}>
                        <td className="text-foreground">{ratioLabel(key)}</td>
                        <td className="font-mono text-2xs text-muted-foreground">{formulas[key] ?? "—"}</td>
                        <td className="num">{ratioValue(key, value)}</td>
                        <td className="num-dim">
                          {scoredEntry?.status === "SCORED" ? num(scoredEntry.benchmark ?? 0) : "—"}
                        </td>
                        <td className="num-dim">
                          {scoredEntry?.status === "SCORED"
                            ? signed(value - (scoredEntry.benchmark ?? 0))
                            : "—"}
                        </td>
                        <td className="px-3 py-2 text-right">
                          {entry ? (
                            <TrendSparkline points={Object.values(entry.by_year)} direction={entry.direction} />
                          ) : (
                            <span className="font-mono text-2xs text-muted-foreground">—</span>
                          )}
                        </td>
                        <td className="num-dim" title={entry?.cagr_omitted}>
                          {entry?.cagr_pct !== undefined
                            ? `${signed(entry.cagr_pct, 1)}%`
                            : entry?.cagr_omitted
                              ? "n/a"
                              : "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </ScheduleCard>
        );
      })}

      <DupontSchedule ratios={ratios} />
      <CycleSchedule ratios={ratios} />

      {ratios.omitted_ratios.length > 0 && (
        <ScheduleCard
          reference="Schedule 7"
          title="Not computed, and why"
          note="A ratio absent from the schedules above was not computed. It is not zero, and it is not weak."
        >
          <div className="overflow-x-auto">
            <table className="ledger">
              <thead>
                <tr>
                  <th>Metric</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {ratios.omitted_ratios.map((entry) => (
                  <tr key={entry.ratio}>
                    <td className="font-mono text-2xs text-foreground">{entry.ratio}</td>
                    <td className="text-xs leading-relaxed">{entry.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </ScheduleCard>
      )}
    </div>
  );
}

function DupontSchedule({ ratios }: { ratios: RatioAnalysis }) {
  const dupont = ratios.dupont ?? {};
  const forms = [
    { key: "three_step" as const, label: "Three-step" },
    { key: "five_step" as const, label: "Five-step" },
  ];
  const available = forms.filter((form) => dupont[form.key]);

  return (
    <ScheduleCard
      reference="Schedule 5"
      title="DuPont decomposition of return on equity"
      aside={dupont.roe !== undefined && <span className="chip-brand">ROE {num(dupont.roe)}%</span>}
      note={
        available.length === 0
          ? "Withheld. ROE is undefined at non-positive equity, so there is nothing to decompose: every term would still multiply out to a plausible number."
          : "DuPont is an algebraic identity, so the product of the terms is reconciled against ROE computed directly. A non-zero residual means a term came from a different period than the rest."
      }
    >
      {available.length > 0 && (
        <div className="divide-y divide-border">
          {available.map((form) => {
            const body = dupont[form.key]!;
            const terms = Object.entries(body.terms);
            return (
              <div key={form.key} className="px-4 py-4">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h3 className="text-xs font-medium text-muted-foreground">
                    {form.label}
                  </h3>
                  <span className={body.reconciles ? "chip-safe" : "chip-distress"}>
                    {body.reconciles ? "reconciles" : `residual ${signed(body.residual_pct)}%`}
                  </span>
                </div>
                <div className="mt-3 flex flex-wrap items-stretch gap-1">
                  {terms.map(([key, term], index) => (
                    <div key={key} className="flex items-stretch gap-1">
                      {index > 0 && (
                        <span className="self-center font-mono text-sm text-muted-foreground">×</span>
                      )}
                      <div
                        className="min-w-28 flex-1 border border-border bg-surface-2 px-2.5 py-2"
                        title={term.meaning}
                      >
                        <p className="text-2xs text-muted-foreground">
                          {ratioLabel(key)}
                        </p>
                        <p className="font-mono text-base text-foreground">{num(term.value, 4)}</p>
                        <p className="mt-0.5 font-mono text-2xs leading-tight text-muted-foreground">
                          {term.definition}
                        </p>
                      </div>
                    </div>
                  ))}
                  <div className="flex items-stretch gap-1">
                    <span className="self-center font-mono text-sm text-muted-foreground">=</span>
                    <div className="min-w-28 border border-primary/40 bg-brand-tint px-2.5 py-2">
                      <p className="text-2xs font-medium text-primary">ROE</p>
                      <p className="font-mono text-base text-primary">{num(body.product_roe_pct)}%</p>
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </ScheduleCard>
  );
}

function CycleSchedule({ ratios }: { ratios: RatioAnalysis }) {
  const cycle = ratios.cash_conversion_cycle ?? {};
  const legs = [
    { key: "dio" as const, label: "Days inventory outstanding", sign: "+" },
    { key: "dso" as const, label: "Days sales outstanding", sign: "+" },
    { key: "dpo" as const, label: "Days payables outstanding", sign: "−" },
  ];
  const basis = Array.isArray(cycle.basis) ? cycle.basis.join(", ") : cycle.basis;

  return (
    <ScheduleCard
      reference="Schedule 6"
      title="Cash conversion cycle"
      aside={basis && <span className="chip-neutral">{basis.replace(/_/g, " ").toLowerCase()}</span>}
      note={
        cycle.ccc
          ? cycle.ccc.meaning
          : "The cycle is the sum of all three day counts; at least one could not be computed."
      }
    >
      <div className="flex flex-wrap items-stretch gap-1 px-4 py-4">
        {legs.map((leg, index) => {
          const entry = cycle[leg.key];
          return (
            <div key={leg.key} className="flex items-stretch gap-1">
              {index > 0 && (
                <span className="self-center font-mono text-sm text-muted-foreground">{leg.sign}</span>
              )}
              <div className="min-w-36 border border-border bg-surface-2 px-3 py-2">
                <p className="text-2xs text-muted-foreground">{leg.label}</p>
                <p className="font-mono text-lg text-foreground">
                  {entry ? `${num(entry.days, 1)}d` : "—"}
                </p>
                <p className="mt-0.5 font-mono text-2xs text-muted-foreground">
                  {entry?.balance_basis?.replace(/_/g, " ").toLowerCase() ?? "not computed"}
                </p>
              </div>
            </div>
          );
        })}
        <div className="flex items-stretch gap-1">
          <span className="self-center font-mono text-sm text-muted-foreground">=</span>
          <div className="min-w-36 border border-primary/40 bg-brand-tint px-3 py-2">
            <p className="text-2xs font-medium text-primary">Cash conversion cycle</p>
            <p className="font-mono text-lg text-primary">
              {cycle.ccc ? `${num(cycle.ccc.days, 1)}d` : "—"}
            </p>
          </div>
        </div>
      </div>
    </ScheduleCard>
  );
}
