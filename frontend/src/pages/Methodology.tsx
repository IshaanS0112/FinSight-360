import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { AltmanModelName, Methodology as MethodologyPayload } from "../api/types";

const MODEL_LABEL: Record<AltmanModelName, string> = {
  Z_1968: "Altman Z (1968), public manufacturers",
  Z_PRIME: "Altman Z′, private manufacturers",
  Z_DOUBLE_PRIME: "Altman Z″, non-manufacturers & emerging markets",
};

/**
 * Everything the numbers depend on, read live from GET /methodology.
 *
 * Hardcoding these values into the UI would defeat the purpose: the page exists so
 * a reader can confirm which coefficients the running service is actually using,
 * including any overridden by environment variables.
 */
export default function Methodology() {
  const [data, setData] = useState<MethodologyPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .methodology()
      .then(setData)
      .catch((err: Error) => setError(err.message));
  }, []);

  if (error) return <p className="panel p-6 text-sm text-distress">{error}</p>;
  if (!data) return <p className="panel p-6 text-sm text-muted">Loading…</p>;

  const { altman, ratio_engine, health_score } = data.models;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-slate-100">Methodology</h1>
        <p className="mt-1 text-xs text-muted">
          Read live from the running service, so these are the values actually in force.
        </p>
      </div>

      <section className="panel p-5">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-accent">
          Bankruptcy models
        </h2>
        <div className="space-y-4">
          {(Object.keys(altman.variants) as AltmanModelName[]).map((model) => {
            const variant = altman.variants[model];
            return (
              <div key={model} className="rounded border border-edge bg-ink p-3">
                <p className="text-xs font-medium text-slate-200">{MODEL_LABEL[model]}</p>
                <p className="mt-1 font-mono text-[11px] text-slate-400">
                  {variant.components
                    .map((c) => `${variant.coefficients[c]}·${c.toUpperCase()}`)
                    .join(" + ")}
                </p>
                <p className="mt-1 text-[11px] text-muted">
                  safe &gt; {variant.cutoffs.safe_above} · distress &lt;{" "}
                  {variant.cutoffs.distress_below} · X4 uses{" "}
                  {variant.x4_equity_basis.toLowerCase().replace("_", " ")} of equity
                </p>
                <p className="mt-2 text-[11px] leading-relaxed text-muted">{variant.citation}</p>
              </div>
            );
          })}
        </div>

        <div className="mt-4">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">
            Components
          </h3>
          <ul className="space-y-1.5 text-xs">
            {Object.entries(altman.component_definitions).map(([key, definition]) => (
              <li key={key}>
                <span className="font-mono uppercase text-slate-300">{key}</span>{" "}
                <span className="font-mono text-[11px] text-muted">= {definition}</span>
                <div className="text-[11px] text-muted">{altman.component_meanings[key]}</div>
              </li>
            ))}
          </ul>
        </div>

        <p className="mt-4 rounded border border-grey/40 bg-grey/10 p-3 text-xs leading-relaxed text-grey">
          {altman.financial_sector_policy}
        </p>
      </section>

      <section className="panel p-5">
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider text-accent">
          Ratio definitions
        </h2>
        <p className="mb-3 text-xs leading-relaxed text-muted">{ratio_engine.note}</p>
        <ul className="space-y-1 font-mono text-[11px]">
          {Object.entries(ratio_engine.formulas).map(([key, formula]) => (
            <li key={key} className="flex flex-wrap gap-2">
              <span className="text-slate-300">{key}</span>
              <span className="text-muted">= {formula}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="panel p-5">
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider text-accent">
          Health score
        </h2>
        <p className="mb-3 rounded border border-grey/40 bg-grey/10 p-2 text-xs text-grey">
          {health_score.status}
        </p>
        <ul className="space-y-1 text-xs">
          {Object.entries(health_score.weights).map(([key, weight]) => (
            <li key={key} className="flex justify-between">
              <span className="capitalize text-slate-300">{key}</span>
              <span className="stat text-muted">{(weight * 100).toFixed(0)}%</span>
            </li>
          ))}
        </ul>
        <p className="mt-3 font-mono text-[11px] leading-relaxed text-muted">
          {health_score.normalisation}
        </p>
        <p className="mt-3 text-xs leading-relaxed text-muted">
          <span className="text-slate-400">Peer percentile:</span>{" "}
          {health_score.peer_percentile}
        </p>
      </section>

      <section className="panel p-5">
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider text-accent">
          Benchmarks and the LLM
        </h2>
        <p className="text-xs leading-relaxed text-grey">{data.benchmark_provenance}</p>
        <p className="mt-3 text-xs leading-relaxed text-muted">{data.llm_role}</p>
      </section>

      <section className="panel p-5">
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider text-accent">
          Accepted line items
        </h2>
        <p className="font-mono text-[11px] leading-relaxed text-muted">
          {data.line_item_vocabulary.join(" · ")}
        </p>
      </section>
    </div>
  );
}
