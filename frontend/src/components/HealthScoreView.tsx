import type { HealthScore } from "../api/types";

const COMPONENT_ORDER = ["profitability", "liquidity", "leverage", "efficiency"] as const;

function barColour(score: number): string {
  if (score >= 66) return "bg-safe";
  if (score >= 40) return "bg-grey";
  return "bg-distress";
}

/**
 * The composite, its components, and the fact that it is not an established model.
 *
 * The "project-defined composite" line sits at the top rather than in a footnote.
 * The Altman score above it is a published model; this one is not, and presenting
 * them with equal authority would mislead.
 */
export default function HealthScoreView({ health }: { health: HealthScore }) {
  const basis = health.calculation_basis;
  const effective = basis.weights_effective ?? {};
  const declared = basis.weights_declared ?? {};

  return (
    <section className="panel p-5">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wider text-muted">
            Financial health score
          </h2>
          <p className="mt-1 text-xs text-grey">
            Project-defined composite, not an established model. 50 = exactly at benchmark.
          </p>
        </div>
        <div className="stat text-3xl font-semibold text-slate-100">
          {health.overall_score ?? "-"}
          <span className="text-base text-muted">/100</span>
        </div>
      </div>

      <ul className="space-y-3">
        {COMPONENT_ORDER.map((key) => {
          const score = health.component_scores[key];
          const weight = effective[key] ?? declared[key] ?? 0;
          return (
            <li key={key}>
              <div className="mb-1 flex items-baseline justify-between text-xs">
                <span className="capitalize text-slate-300">
                  {key}{" "}
                  <span className="text-muted">
                    (weight {(weight * 100).toFixed(0)}%)
                  </span>
                </span>
                <span className="stat text-slate-100">
                  {score === null ? <span className="text-muted">not scored</span> : score}
                </span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-ink">
                {score !== null && (
                  <div
                    className={`h-full ${barColour(score)}`}
                    style={{ width: `${Math.max(0, Math.min(100, score))}%` }}
                  />
                )}
              </div>
            </li>
          );
        })}
      </ul>

      {basis.renormalisation_note && (
        <p className="mt-4 rounded border border-grey/40 bg-grey/10 p-2 text-xs leading-relaxed text-grey">
          {basis.renormalisation_note}
        </p>
      )}

      <div className="mt-4 space-y-2 text-xs text-muted">
        <p>
          <span className="text-slate-400">Peer percentile:</span>{" "}
          {health.peer_percentile ?? "withheld, see methodology"}
        </p>
        <p className="leading-relaxed">
          <span className="text-slate-400">Benchmarks:</span> {basis.benchmark_provenance}
        </p>
      </div>

      <details className="mt-3 text-xs text-muted">
        <summary className="cursor-pointer hover:text-accent">Normalisation</summary>
        <p className="mt-2 font-mono text-[11px] leading-relaxed">{basis.normalisation}</p>
      </details>
    </section>
  );
}
