import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";

import { api } from "../api/client";
import type { AltmanModelName, Methodology as MethodologyPayload } from "../api/types";
import PageHeader from "../components/PageHeader";
import { ErrorState, LoadingBlock } from "../components/States";
import { num, pct } from "../components/format";

const MODEL_LABEL: Record<AltmanModelName, string> = {
  Z_1968: "Altman Z (1968), public manufacturers",
  Z_PRIME: "Altman Z′, private manufacturers",
  Z_DOUBLE_PRIME: "Altman Z″, non-manufacturers and emerging markets",
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

  const load = useCallback(() => {
    setError(null);
    api
      .methodology()
      .then(setData)
      .catch((err: Error) => setError(err.message));
  }, []);

  useEffect(load, [load]);

  return (
    <div className="space-y-10">
      <PageHeader
        eyebrow="Methodology"
        title={
          <>
            The values <em>in force</em>, read from the running service
          </>
        }
        summary="Coefficients, cutoffs, formulas and refusal rules, fetched live so an environment override shows up here rather than hiding behind a hardcoded page."
      />
      {error && <ErrorState title="Could not load the methodology" message={error} onRetry={load} />}
      {!error && !data && <LoadingBlock rows={10} label="Loading methodology" />}
      {data && <Sections data={data} />}
    </div>
  );
}

function Sections({ data }: { data: MethodologyPayload }) {
  const { altman, ratio_engine, health_score, market_data, merton, portfolio_lab, research_agents } = data.models;
  return (
    <div className="divide-y divide-border border-t border-border">
      <Section no="01" title="Bankruptcy models">
        <div className="grid gap-3 lg:grid-cols-3">
          {(Object.keys(altman.variants) as AltmanModelName[]).map((model) => {
            const variant = altman.variants[model];
            return (
              <div key={model} className="sheet p-4">
                <p className="text-sm font-medium text-foreground">{MODEL_LABEL[model]}</p>
                <p className="mt-2 font-mono text-xs leading-relaxed text-foreground">
                  {variant.components.map((c) => `${variant.coefficients[c]}·${c.toUpperCase()}`).join(" + ")}
                </p>
                <p className="mt-2 text-xs text-muted-foreground">
                  Safe above {variant.cutoffs.safe_above}, distress below {variant.cutoffs.distress_below}. X4 uses the{" "}
                  {variant.x4_equity_basis.toLowerCase().replace("_", " ")} of equity.
                </p>
                <p className="mt-2 text-2xs leading-relaxed text-muted-foreground">{variant.citation}</p>
              </div>
            );
          })}
        </div>
        <dl className="mt-5 grid gap-x-8 gap-y-3 sm:grid-cols-2">
          {Object.entries(altman.component_definitions).map(([key, definition]) => (
            <div key={key}>
              <dt className="font-mono text-xs text-foreground">
                {key.toUpperCase()} = {definition}
              </dt>
              <dd className="text-xs text-muted-foreground">{altman.component_meanings[key]}</dd>
            </div>
          ))}
        </dl>
        <p className="callout-warning mt-5 text-xs">{altman.financial_sector_policy}</p>
      </Section>

      <Section no="02" title="Ratio definitions" lead={ratio_engine.note}>
        <ul className="grid gap-x-8 gap-y-1.5 font-mono text-xs sm:grid-cols-2">
          {Object.entries(ratio_engine.formulas).map(([key, formula]) => (
            <li key={key}>
              <span className="text-foreground">{key}</span> <span className="text-muted-foreground">= {formula}</span>
            </li>
          ))}
        </ul>
      </Section>

      <Section no="03" title="Health score" lead={health_score.status}>
        <table className="ledger max-w-md">
          <tbody>
            {Object.entries(health_score.weights).map(([key, weight]) => (
              <tr key={key}>
                <td className="capitalize">{key}</td>
                <td className="num">{(weight * 100).toFixed(0)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-4 font-mono text-xs leading-relaxed text-muted-foreground">{health_score.normalisation}</p>
        <p className="mt-2 text-xs leading-relaxed text-muted-foreground">Peer percentile: {health_score.peer_percentile}</p>
      </Section>

      {market_data && merton && (
        <Section no="04" title="Market data and the Merton model" lead={market_data.no_look_ahead}>
          <Facts
            rows={[
              ["Returns", market_data.returns],
              ["Market capitalisation", market_data.market_capitalisation],
              ["Beta", market_data.beta],
              ["VaR confidence", pct(market_data.var_confidence, 0)],
              ["Minimum observations", `${market_data.minimum_observations} months`],
              ["Default point", merton.default_point],
              ["Volatility window", `${merton.volatility_window_months} months`],
              ["Horizon", `${num(merton.horizon_years, 0)} year`],
              ["Risk-free rates", Object.entries(merton.risk_free_rates).map(([ccy, r]) => `${ccy} ${pct(r)}`).join(", ")],
              ["Market view bands", `low below ${pct(merton.market_view_bands.low_pd_below)}, high above ${pct(merton.market_view_bands.high_pd_above)}`],
              ["Financial firms", merton.financial_sector_policy],
            ]}
          />
          <p className="mt-4 text-2xs leading-relaxed text-muted-foreground">
            {merton.citation} {merton.naive_cross_check}
          </p>
        </Section>
      )}

      {portfolio_lab && (
        <Section no="05" title="Portfolio Lab" lead={`Adapted from ${portfolio_lab.inspired_by.join(" and ")}.`}>
          <Facts
            rows={[
              ["Expected returns", portfolio_lab.expected_returns.join(", ")],
              ["Risk models", portfolio_lab.risk_models.join(", ")],
              ["Optimisers", portfolio_lab.optimisers.join(", ")],
              ["Constraints", portfolio_lab.constraints],
              ["Credit overlay", portfolio_lab.credit_overlay],
              ["Risk decomposition", portfolio_lab.risk_decomposition],
              ["Minimum observations", `${portfolio_lab.minimum_observations} months`],
            ]}
          />
          <p className="mt-4 text-xs font-medium text-foreground">Refused, with the reason stated</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs text-muted-foreground">
            {portfolio_lab.refusals.map((refusal) => (
              <li key={refusal}>{refusal}</li>
            ))}
          </ul>
        </Section>
      )}

      {research_agents && (
        <Section no="06" title="Research agents" lead={`Adapted from ${research_agents.inspired_by}. ${research_agents.departure_from_inspiration}`}>
          <ol className="space-y-1.5 text-xs">
            {research_agents.pipeline.map((step, index) => (
              <li key={step} className="flex gap-3">
                <span className="font-mono text-muted-foreground">{String(index + 1).padStart(2, "0")}</span>
                <span className="text-foreground">{step}</span>
              </li>
            ))}
          </ol>
          <p className="mt-4 font-mono text-xs text-muted-foreground">
            model {research_agents.model} · effort {research_agents.effort} · number tolerance{" "}
            {pct(research_agents.number_tolerance, 0)}
          </p>
        </Section>
      )}

      <Section no="07" title="Benchmarks and the language model">
        <p className="callout-warning text-xs">{data.benchmark_provenance}</p>
        <p className="prose-measure mt-4 text-sm leading-relaxed text-muted-foreground">{data.llm_role}</p>
        {data.llm_output_contract && (
          <p className="prose-measure mt-2 text-sm leading-relaxed text-muted-foreground">{data.llm_output_contract}</p>
        )}
      </Section>

      <Section no="08" title="Accepted line items">
        <p className="font-mono text-xs leading-relaxed text-muted-foreground">{data.line_item_vocabulary.join(" · ")}</p>
      </Section>
    </div>
  );
}

function Section({ no, title, lead, children }: { no: string; title: string; lead?: string; children: ReactNode }) {
  return (
    <section className="grid gap-4 py-8 lg:grid-cols-[14rem_minmax(0,1fr)]">
      <div>
        <p className="section-no">{no}</p>
        <h2 className="sheet-title mt-0.5">{title}</h2>
      </div>
      <div className="min-w-0">
        {lead && <p className="prose-measure mb-4 text-sm leading-relaxed text-muted-foreground">{lead}</p>}
        {children}
      </div>
    </section>
  );
}

function Facts({ rows }: { rows: [string, string][] }) {
  return (
    <dl className="divide-y divide-border border-y border-border">
      {rows.map(([label, value]) => (
        <div key={label} className="grid gap-1 py-2 sm:grid-cols-[12rem_minmax(0,1fr)] sm:gap-4">
          <dt className="text-xs text-muted-foreground">{label}</dt>
          <dd className="text-xs text-foreground">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
