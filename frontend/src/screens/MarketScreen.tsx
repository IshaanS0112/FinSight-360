import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { ListingDraft } from "../api/client";
import type { MarketRisk, Security, SecurityDetail } from "../api/types";
import ActionButton from "../components/ActionButton";
import DistanceToDefaultScale from "../components/charts/DistanceToDefaultScale";
import PriceIndexChart from "../components/charts/PriceIndexChart";
import type { PriceSeries } from "../components/charts/PriceIndexChart";
import Kpi from "../components/Kpi";
import ScheduleCard from "../components/ScheduleCard";
import { EmptyState, InlineError, LoadingBlock } from "../components/States";
import { human, money, num, pct, probability } from "../components/format";
import type { CompanyData } from "../pages/CompanyDetail";

/**
 * The equity market's view of the company: Merton distance-to-default solved
 * from the share price, the naive closed form beside it, regression beta and
 * monthly risk statistics, all measured up to the fiscal year end.
 */
export default function MarketScreen({
  data,
  busy,
  locked,
  onLink,
  onCompute,
}: {
  data: CompanyData;
  busy: boolean;
  locked: boolean;
  onLink: (draft: ListingDraft) => Promise<void>;
  onCompute: () => Promise<void>;
}) {
  const { listing, market } = data;
  if (!listing) return <ListingForm busy={busy} locked={locked} onLink={onLink} />;
  if (!market) {
    return (
      <EmptyState
        title={`Linked to ${listing.ticker}, not yet measured`}
        action={
          <ActionButton busy={busy} disabled={locked} onClick={() => void onCompute()} busyLabel="Solving Merton">
            Compute market risk
          </ActionButton>
        }
      >
        Solves the Merton model from the share price at the fiscal year end and measures beta and the risk
        statistics on the months before it.
      </EmptyState>
    );
  }
  return <MarketReport market={market} benchmark={listing.benchmark_ticker} busy={busy} locked={locked} onCompute={onCompute} />;
}

function MarketReport({
  market,
  benchmark,
  busy,
  locked,
  onCompute,
}: {
  market: MarketRisk;
  benchmark: string | null;
  busy: boolean;
  locked: boolean;
  onCompute: () => Promise<void>;
}) {
  const basis = market.calculation_basis;
  const metrics = market.risk_metrics;
  const view = basis.market_view;
  return (
    <div className="space-y-6">
      <ScheduleCard
        reference="Schedule 18"
        title={claim(market)}
        aside={
          <ActionButton variant="secondary" busy={busy} disabled={locked} onClick={() => void onCompute()} busyLabel="Solving">
            Recompute
          </ActionButton>
        }
        note={view?.reason}
      >
        <div className="grid gap-6 px-4 py-6 sm:grid-cols-2 xl:grid-cols-4">
          <Kpi label="Merton distance to default" value={num(market.merton_distance_to_default)} foot={`PD ${probability(market.merton_probability_of_default)}, one year`} />
          <Kpi label="Naive distance to default" value={num(market.naive_distance_to_default)} foot={`PD ${probability(market.naive_probability_of_default)}`} />
          <Kpi
            label={`Beta vs ${basis.beta?.benchmark ?? "benchmark"}, Blume-adjusted`}
            value={num(market.adjusted_beta)}
            foot={market.beta === null ? "Refused, see below" : `raw ${num(market.beta)} · R² ${num(basis.beta?.r_squared)}`}
          />
          <Kpi label="Annualised volatility" value={pct(metrics.annualised_volatility)} foot={`max drawdown ${pct(metrics.max_drawdown)}`} />
        </div>
        {view && (
          <div className="border-t border-border px-4 py-6">
            <DistanceToDefaultScale
              solved={market.merton_distance_to_default}
              naive={market.naive_distance_to_default}
              bands={view.bands}
            />
          </div>
        )}
      </ScheduleCard>

      <PriceSection ticker={market.ticker} benchmark={benchmark} cutoff={basis.fiscal_year_end} />

      <div className="grid gap-6 xl:grid-cols-2">
        <RiskStatistics market={market} />
        <MertonInputs market={market} />
      </div>
    </div>
  );
}

/** The section title states the finding, with the market-implied probability in it. */
function claim(market: MarketRisk): string {
  const pd = probability(market.merton_probability_of_default);
  const consensus = market.calculation_basis.market_view?.against_consensus;
  if (market.market_view === "CONFIRMS") return `The equity market agrees: ${pd} market-implied default probability`;
  if (market.market_view === "CONTRADICTS") return `The market disagrees with the ${human(consensus)} verdict: ${pd} implied default`;
  if (market.market_view === "PARTIAL") return `A ${pd} market-implied default probability: neither confirms nor contradicts`;
  return `Market-implied default probability ${pd}; no accounting verdict to compare`;
}

function PriceSection({ ticker, benchmark, cutoff }: { ticker: string; benchmark: string | null; cutoff: string }) {
  const [series, setSeries] = useState<PriceSeries[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    const tickers = benchmark ? [ticker, benchmark] : [ticker];
    Promise.all(tickers.map((t) => api.getSecurity(t)))
      .then((securities: SecurityDetail[]) => {
        if (!live) return;
        setSeries(securities.map((s, i) => ({ key: s.ticker, label: `${s.name} (${s.ticker})`, points: s.prices, highlight: i === 0 })));
      })
      .catch((err: Error) => live && setError(err.message));
    return () => {
      live = false;
    };
  }, [ticker, benchmark]);

  return (
    <ScheduleCard
      reference="Schedule 19"
      title={benchmark ? `${ticker} against ${benchmark}, total return indexed to 100` : `${ticker}, total return indexed to 100`}
      note="Adjusted close, so dividends and splits are in the line. The dashed rule is the fiscal year end: no statistic on this page uses a price after it."
    >
      <div className="px-4 py-5">
        {error && <InlineError message={error} />}
        {!error && !series && <div className="skeleton h-72" />}
        {series && <PriceIndexChart series={series} cutoff={cutoff} />}
      </div>
    </ScheduleCard>
  );
}

function RiskStatistics({ market }: { market: MarketRisk }) {
  const m = market.risk_metrics;
  const basis = market.calculation_basis;
  const confidence = basis.risk_metrics?.var_confidence ?? 0.95;
  const rows: [string, string][] = [
    ["Annualised return", pct(m.annualised_return)],
    ["Annualised volatility", pct(m.annualised_volatility)],
    [`Sharpe ratio (rf ${pct(basis.risk_metrics?.risk_free_rate)})`, num(m.sharpe_ratio)],
    ["Sortino ratio", num(m.sortino_ratio)],
    ["Maximum drawdown", pct(m.max_drawdown)],
    [`Historical VaR, ${pct(confidence, 0)}, one month`, pct(m.historical_var)],
    [`Parametric VaR, ${pct(confidence, 0)}, one month`, pct(m.parametric_var)],
    ["Expected shortfall", pct(m.expected_shortfall)],
    ["Best month", pct(m.best_month)],
    ["Worst month", pct(m.worst_month)],
  ];
  return (
    <ScheduleCard
      reference="Schedule 20"
      title="Monthly risk statistics"
      aside={<span className="chip-neutral">{m.observations ?? "—"} months</span>}
      note={basis.beta?.reason ?? `Beta: ${basis.beta?.adjustment}, ${basis.beta?.observations} months against ${basis.beta?.benchmark}.`}
    >
      {basis.risk_metrics?.reason ? (
        <p className="sheet-note">{basis.risk_metrics.reason}</p>
      ) : (
        <table className="ledger">
          <tbody>
            {rows.map(([label, value]) => (
              <tr key={label}>
                <td className="text-muted-foreground">{label}</td>
                <td className="num">{value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </ScheduleCard>
  );
}

function MertonInputs({ market }: { market: MarketRisk }) {
  const merton = market.calculation_basis.merton;
  if (!merton?.inputs) {
    return (
      <ScheduleCard reference="Schedule 21" title="Merton model">
        <p className="sheet-note">{merton?.refusal ?? "The Merton model was not solved for this company."}</p>
      </ScheduleCard>
    );
  }
  const inputs = merton.inputs;
  const rows: [string, string, string?][] = [
    ["Equity value, E", money(inputs.equity_value), BASIS_LABELS[merton.equity_value_basis ?? ""]],
    ["Equity volatility, σE", pct(inputs.equity_volatility), `${merton.volatility_window_months} months of returns`],
    ["Default point, F", money(inputs.default_point), BASIS_LABELS[merton.default_point_basis ?? ""]],
    ["Risk-free rate, r", pct(inputs.risk_free_rate), market.calculation_basis.currency],
    ["Horizon, T", `${num(inputs.horizon_years, 0)} year`],
    ["Solved asset value, V", money(market.asset_value)],
    ["Solved asset volatility, σV", pct(market.asset_volatility)],
  ];
  return (
    <ScheduleCard
      reference="Schedule 21"
      title="Merton inputs and solution"
      aside={<span className="chip-neutral">{merton.solver_message?.includes("converged") ? "Solver converged" : "Solved"}</span>}
      note={merton.interpretation_limit}
    >
      <table className="ledger">
        <tbody>
          {rows.map(([label, value, detail]) => (
            <tr key={label}>
              <td>
                <span className="text-foreground">{label}</span>
                {detail && <span className="block text-2xs text-muted-foreground">{detail}</span>}
              </td>
              <td className="num">{value}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="space-y-1 border-t border-border px-4 py-3 font-mono text-2xs text-muted-foreground">
        {merton.equations?.map((equation) => <p key={equation}>{equation}</p>)}
        <p>DD = {merton.distance_to_default}</p>
        {merton.gap_vs_reported_pct !== undefined && (
          <p>
            E differs from the filing's reported market value by {num(merton.gap_vs_reported_pct)}%.
          </p>
        )}
      </div>
      <p className="border-t border-border px-4 py-3 text-2xs leading-relaxed text-muted-foreground">
        {merton.citation} {merton.naive_citation}
      </p>
    </ScheduleCard>
  );
}

/** Links the company to a listed security so the market model has prices to read. */
function ListingForm({
  busy,
  locked,
  onLink,
}: {
  busy: boolean;
  locked: boolean;
  onLink: (draft: ListingDraft) => Promise<void>;
}) {
  const [securities, setSecurities] = useState<Security[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<ListingDraft>({ ticker: "", benchmark_ticker: "SPY", fiscal_year_end_month: 12 });

  useEffect(() => {
    api
      .listSecurities()
      .then(setSecurities)
      .catch((err: Error) => setError(err.message));
  }, []);

  if (error) return <InlineError message={error} />;
  if (!securities) return <LoadingBlock rows={3} label="Loading securities" />;
  if (securities.length === 0) {
    return (
      <EmptyState title="No price histories loaded">
        The market model needs monthly prices. Load the sourced file with{" "}
        <code className="font-mono text-foreground">python backend/scripts/load_sample_filings.py</code>.
      </EmptyState>
    );
  }
  return (
    <ScheduleCard
      reference="Schedule 18"
      title="Link this company to its listed security"
      note="Beta is refused when the stock and the benchmark trade in different currencies: the regression would mix market risk with exchange-rate risk."
    >
      <form
        className="grid gap-4 px-4 py-5 sm:grid-cols-3"
        onSubmit={(event) => {
          event.preventDefault();
          void onLink({ ...draft, benchmark_ticker: draft.benchmark_ticker || null });
        }}
      >
        <label className="block">
          <span className="label">Ticker</span>
          <select className="field" required value={draft.ticker} onChange={(e) => setDraft({ ...draft, ticker: e.target.value })}>
            <option value="">Choose a security</option>
            {securities.map((s) => (
              <option key={s.ticker} value={s.ticker}>
                {s.ticker} · {s.name} ({s.currency})
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="label">Benchmark</span>
          <select className="field" value={draft.benchmark_ticker ?? ""} onChange={(e) => setDraft({ ...draft, benchmark_ticker: e.target.value })}>
            <option value="">None</option>
            {securities.map((s) => (
              <option key={s.ticker} value={s.ticker}>
                {s.ticker} ({s.currency})
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="label">Fiscal year ends in</span>
          <select
            className="field"
            value={draft.fiscal_year_end_month}
            onChange={(e) => setDraft({ ...draft, fiscal_year_end_month: Number(e.target.value) })}
          >
            {MONTHS.map((month, index) => (
              <option key={month} value={index + 1}>
                {month}
              </option>
            ))}
          </select>
        </label>
        <div className="sm:col-span-3">
          <ActionButton type="submit" busy={busy} disabled={locked || !draft.ticker} busyLabel="Linking and solving">
            Link and compute
          </ActionButton>
        </div>
      </form>
    </ScheduleCard>
  );
}

const BASIS_LABELS: Record<string, string> = {
  SHARES_X_FISCAL_YEAR_END_CLOSE: "Shares × fiscal-year-end close",
  REPORTED_MARKET_VALUE_EQUITY: "Reported market value of equity",
  KMV_SHORT_PLUS_HALF_LONG: "KMV: short-term debt + half of long-term debt",
  TOTAL_DEBT_NO_SPLIT: "Total debt, no maturity split in the filing",
};

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
