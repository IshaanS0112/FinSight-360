import { useEffect, useState } from "react";

import type { PortfolioKey, PortfolioRun } from "../api/types";
import ScheduleCard from "../components/ScheduleCard";
import CorrelationHeatmap from "../components/charts/CorrelationHeatmap";
import Dendrogram from "../components/charts/Dendrogram";
import EfficientFrontier from "../components/charts/EfficientFrontier";
import RiskShareBars, { mostOverweightInRisk } from "../components/charts/RiskShareBars";
import { PORTFOLIO_LABELS, PORTFOLIO_ORDER, VERDICT_LABELS, money, num, pct, verdictChip } from "../components/format";

/** Every section of one stored Portfolio Lab run, numbered in reading order. */
export default function PortfolioResults({ run, sectors }: { run: PortfolioRun; sectors: Record<string, string | null> }) {
  const headline = run.calculation_basis.headline_portfolio ?? firstAvailable(run);
  const [selected, setSelected] = useState<PortfolioKey>(headline);
  useEffect(() => setSelected(headline), [run.id, headline]);
  const chosen = run.results.portfolios[selected];

  return (
    <div className="space-y-6">
      <ScheduleCard
        reference="01"
        title={
          chosen?.expected_return !== undefined && chosen.volatility !== undefined
            ? `${PORTFOLIO_LABELS[selected]}: ${pct(chosen.expected_return)} expected return at ${pct(chosen.volatility)} volatility`
            : `${PORTFOLIO_LABELS[selected]} was refused`
        }
        note="Every point is in-sample: the optimiser is scored on the history it was fitted to. Click an optimiser's mark to select it."
      >
        <div className="px-4 py-5">
          <EfficientFrontier results={run.results} selected={selected} onSelect={setSelected} />
        </div>
      </ScheduleCard>

      <MethodsTable run={run} selected={selected} onSelect={setSelected} />
      <WeightsTable run={run} selected={selected} />
      <RiskSection run={run} />
      <ClusterSection run={run} sectors={sectors} />
      <AllocationSection run={run} />
      <BasisSection run={run} />
    </div>
  );
}

function firstAvailable(run: PortfolioRun): PortfolioKey {
  return PORTFOLIO_ORDER.find((key) => run.results.portfolios[key]?.weights) ?? "hrp";
}

function MethodsTable({ run, selected, onSelect }: { run: PortfolioRun; selected: PortfolioKey; onSelect: (key: PortfolioKey) => void }) {
  const rows = PORTFOLIO_ORDER.filter((key) => run.results.portfolios[key]);
  return (
    <ScheduleCard reference="02" title="Six methods on the same estimates" note={run.calculation_basis.hrp_note}>
      <div className="overflow-x-auto">
        <table className="ledger">
          <thead>
            <tr>
              <th>Method</th>
              <th className="text-right">Return</th>
              <th className="text-right">Volatility</th>
              <th className="text-right">Sharpe</th>
              <th className="hidden text-right sm:table-cell">Effective holdings</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((key) => {
              const p = run.results.portfolios[key]!;
              const active = key === selected;
              return (
                <tr key={key} className={active ? "bg-brand-tint" : undefined}>
                  <td>
                    <button
                      type="button"
                      className="link text-left text-foreground"
                      aria-pressed={active}
                      onClick={() => p.weights && onSelect(key)}
                      disabled={!p.weights}
                    >
                      {PORTFOLIO_LABELS[key]}
                    </button>
                    {p.refusal && <p className="mt-0.5 max-w-md text-xs text-muted-foreground">{p.refusal}</p>}
                  </td>
                  <td className="num">{pct(p.expected_return)}</td>
                  <td className="num">{pct(p.volatility)}</td>
                  <td className="num">{num(p.sharpe_ratio)}</td>
                  <td className="num-dim hidden sm:table-cell">{num(p.effective_holdings, 1)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </ScheduleCard>
  );
}

function WeightsTable({ run, selected }: { run: PortfolioRun; selected: PortfolioKey }) {
  const methods = PORTFOLIO_ORDER.filter((key) => run.results.portfolios[key]?.weights);
  const assets = run.results.assets;
  return (
    <ScheduleCard
      reference="03"
      title="Weights by method"
      note="A credit verdict appears for securities linked to a FinSight company; the overlay caps or excludes on it."
    >
      <div className="overflow-x-auto">
        <table className="ledger">
          <thead>
            <tr>
              <th>Security</th>
              <th>Credit view</th>
              {methods.map((key) => (
                <th key={key} className={`text-right ${key === selected ? "text-foreground" : ""}`}>
                  {PORTFOLIO_LABELS[key]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {assets.map((asset) => (
              <tr key={asset.ticker}>
                <td className="font-mono text-xs">{asset.ticker}</td>
                <td>
                  {asset.credit_view?.consensus ? (
                    <span className={verdictChip(asset.credit_view.consensus)} title={asset.credit_view.company}>
                      {VERDICT_LABELS[asset.credit_view.consensus]}
                    </span>
                  ) : (
                    <span className="text-xs text-muted-foreground">not linked</span>
                  )}
                </td>
                {methods.map((key) => {
                  const weight = run.results.portfolios[key]!.weights![asset.ticker] ?? 0;
                  return (
                    <td key={key} className={key === selected ? "num bg-brand-tint" : "num-dim"}>
                      {weight < 0.0005 ? "—" : pct(weight)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </ScheduleCard>
  );
}

function RiskSection({ run }: { run: PortfolioRun }) {
  const risk = run.results.risk_decomposition;
  if (!risk) return null;
  const standout = mostOverweightInRisk(risk.components);
  const title = standout
    ? `${standout.ticker} is ${pct(standout.weight)} of the weight and ${pct(standout.share_of_risk)} of the risk`
    : "Where the risk sits";
  return (
    <ScheduleCard
      reference="04"
      title={title}
      aside={<span className="chip-neutral">{PORTFOLIO_LABELS[risk.portfolio]}</span>}
      note={`Parametric VaR at ${pct(risk.confidence, 0)} over ${risk.horizon}: ${pct(risk.portfolio_var)} of the portfolio. The component VaRs ${risk.identity.replace("component VaRs ", "")}.`}
    >
      <div className="px-4 py-5">
        <RiskShareBars components={risk.components} />
      </div>
    </ScheduleCard>
  );
}

function ClusterSection({ run, sectors }: { run: PortfolioRun; sectors: Record<string, string | null> }) {
  const hrp = run.results.portfolios.hrp;
  if (!hrp?.tree || !hrp.weights) return null;
  const tickers = run.results.universe.tickers;
  return (
    <ScheduleCard
      reference="05"
      title={firstSplit(tickers, hrp.tree.linkage, sectors)}
      note="HRP orders assets by a single-linkage tree on correlation distance, then splits the budget top-down by inverse variance. It never inverts the covariance matrix, which is why it survives estimates the mean-variance optimisers do not."
    >
      <div className="grid gap-6 px-4 py-5 2xl:grid-cols-2">
        <div className="min-w-0">
          <p className="mb-2 text-xs text-muted-foreground">Cluster tree, HRP weight under each leaf</p>
          <Dendrogram tickers={tickers} order={hrp.tree.order} linkage={hrp.tree.linkage} weights={hrp.weights} />
        </div>
        <div className="min-w-0">
          <p className="mb-2 text-xs text-muted-foreground">Correlation of monthly returns, in tree order</p>
          <CorrelationHeatmap tickers={tickers} matrix={run.results.correlation} order={hrp.tree.order} />
        </div>
      </div>
    </ScheduleCard>
  );
}

/**
 * The title for the HRP section: the tree's top merge, named by sector when each
 * side is a single sector, otherwise by its tickers.
 */
function firstSplit(tickers: string[], linkage: number[][], sectors: Record<string, string | null>): string {
  if (linkage.length === 0) return "How HRP clusters the universe";
  const leaves = (node: number): number[] =>
    node < tickers.length ? [node] : linkage[node - tickers.length].slice(0, 2).flatMap((child) => leaves(child));
  const [left, right] = linkage[linkage.length - 1].slice(0, 2).map((node) => leaves(node).map((i) => tickers[i]));
  const name = (side: string[]) => {
    const found = new Set(side.map((t) => sectors[t] ?? t));
    return found.size === 1 && side.length > 1 ? [...found][0] : side.join(", ");
  };
  return `HRP's first split: ${name(left)} against ${name(right)}`;
}

function AllocationSection({ run }: { run: PortfolioRun }) {
  const allocation = run.results.allocation;
  const headline = run.calculation_basis.headline_portfolio;
  if (!allocation || !headline) return null;
  const currency = run.results.universe.currency;
  const held = Object.entries(allocation.shares).filter(([, shares]) => shares > 0);
  return (
    <ScheduleCard
      reference="06"
      title={`${money(allocation.budget)} ${currency} in whole shares, ${money(allocation.leftover_cash)} left over`}
      aside={<span className="chip-neutral">{PORTFOLIO_LABELS[headline]}</span>}
      note={`Greedy rounding to whole shares at the last month-end price. Tracking error against the target weights: ${pct(allocation.tracking_rmse, 2)} RMSE.`}
    >
      <div className="overflow-x-auto">
        <table className="ledger">
          <thead>
            <tr>
              <th>Security</th>
              <th className="text-right">Shares</th>
              <th className="text-right">Target</th>
              <th className="text-right">Realised</th>
            </tr>
          </thead>
          <tbody>
            {held.map(([ticker, shares]) => (
              <tr key={ticker}>
                <td className="font-mono text-xs">{ticker}</td>
                <td className="num">{shares.toLocaleString("en-US")}</td>
                <td className="num-dim">{pct(run.results.portfolios[headline]?.weights?.[ticker])}</td>
                <td className="num">{pct(allocation.realised_weights[ticker])}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </ScheduleCard>
  );
}

function BasisSection({ run }: { run: PortfolioRun }) {
  const basis = run.calculation_basis;
  const overlay = run.results.credit_overlay;
  const facts: [string, string][] = [
    ["Expected returns", `${basis.estimation.method.replace(/_/g, " ")}${basis.estimation.compounding ? `, ${basis.estimation.compounding}` : ""}`],
    ["Risk model", `${basis.estimation.risk_model.replace(/_/g, "-")}${basis.estimation.shrinkage !== undefined ? `, shrinkage ${num(basis.estimation.shrinkage, 3)}` : ""}`],
    ["Risk-free rate", pct(basis.risk_free_rate)],
    ["Constraints", basis.constraints],
    ["Credit overlay", `${overlay.mode.replace(/_/g, " ")}; ${overlay.constrained.length ? overlay.constrained.map((c) => `${c.ticker} capped at ${pct(c.cap, 0)} (${c.reason})`).join("; ") : "no security constrained"}`],
    ["Linked to a company", overlay.linked.length ? overlay.linked.join(", ") : "none"],
  ];
  return (
    <ScheduleCard reference="07" title="Basis, sources and limits">
      <dl className="divide-y divide-border">
        {facts.map(([label, value]) => (
          <div key={label} className="grid gap-1 px-4 py-2 sm:grid-cols-[11rem_minmax(0,1fr)] sm:gap-4">
            <dt className="text-xs text-muted-foreground">{label}</dt>
            <dd className="text-xs text-foreground">{value}</dd>
          </div>
        ))}
      </dl>
      <div className="space-y-3 border-t border-border px-4 py-4">
        <p className="callout-warning text-xs">{basis.interpretation_limit}</p>
        <ul className="space-y-1 text-2xs leading-relaxed text-muted-foreground">
          {Object.values(basis.citations).map((citation) => (
            <li key={citation}>{citation}</li>
          ))}
        </ul>
        <p className="text-2xs text-muted-foreground">
          Adapted from{" "}
          {basis.inspired_by.map((repo, i) => (
            <span key={repo}>
              {i > 0 && " and "}
              <a className="link" href={`https://github.com/${repo}`} target="_blank" rel="noreferrer">
                {repo}
              </a>
            </span>
          ))}
          .
        </p>
      </div>
    </ScheduleCard>
  );
}
