import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";

import { api } from "../api/client";
import type { CreditOverlay, PortfolioConfig, PortfolioRun, PortfolioRunSummary, Security } from "../api/types";
import ActionButton from "../components/ActionButton";
import PageHeader from "../components/PageHeader";
import { EmptyState, ErrorState, InlineError, LoadingBlock } from "../components/States";
import { PORTFOLIO_LABELS, num, pct, stamp } from "../components/format";
import PortfolioResults from "../screens/PortfolioResults";

const BENCHMARK_SECTOR = "US large-cap equity index";

const OVERLAYS: { value: CreditOverlay; label: string }[] = [
  { value: "cap_mixed", label: "Exclude high risk, cap mixed at 10%" },
  { value: "exclude_high_risk", label: "Exclude high risk" },
  { value: "none", label: "None" },
];

/**
 * Portfolio Lab: six optimisers over one universe of sourced monthly prices,
 * side by side, with the FinSight credit verdicts available as a constraint.
 * Opens on the most recent stored run.
 */
export default function PortfolioLab() {
  const [securities, setSecurities] = useState<Security[] | null>(null);
  const [runs, setRuns] = useState<PortfolioRunSummary[]>([]);
  const [run, setRun] = useState<PortfolioRun | null>(null);
  const [config, setConfig] = useState<PortfolioConfig | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const [list, history] = await Promise.all([api.listSecurities(), api.portfolioRuns(8)]);
      setSecurities(list);
      setRuns(history);
      setConfig((current) => current ?? defaultConfig(list));
      if (history.length) setRun(await api.getPortfolioRun(history[0].id));
    } catch (err) {
      setLoadError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const optimise = async () => {
    if (!config) return;
    setBusy(true);
    setRunError(null);
    try {
      const created = await api.optimizePortfolio({ ...config, name: config.name?.trim() || null });
      setRun(created);
      setRuns(await api.portfolioRuns(8));
    } catch (err) {
      setRunError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const open = async (id: string) => {
    setRunError(null);
    try {
      setRun(await api.getPortfolioRun(id));
    } catch (err) {
      setRunError((err as Error).message);
    }
  };

  return (
    <div className="space-y-8">
      <PageHeader eyebrow="Portfolio Lab" title={headline(run)} summary={summary(run)} />
      {loadError && <ErrorState title="Could not load the Portfolio Lab" message={loadError} onRetry={() => void load()} />}
      {!loadError && (!securities || !config) && <LoadingBlock rows={8} label="Loading securities" />}
      {securities && config && (
        <div className="grid grid-cols-[minmax(0,1fr)] gap-8 xl:grid-cols-[20rem_minmax(0,1fr)]">
          <aside className="min-w-0 space-y-6 xl:sticky xl:top-6 xl:self-start">
            <ConfigPanel securities={securities} config={config} onChange={setConfig} busy={busy} onSubmit={() => void optimise()} />
            <RunHistory runs={runs} activeId={run?.id} onOpen={(id) => void open(id)} />
          </aside>
          <div className="min-w-0 space-y-6">
            {runError && <InlineError message={runError} onDismiss={() => setRunError(null)} />}
            {run ? (
              <PortfolioResults run={run} sectors={Object.fromEntries(securities.map((sec) => [sec.ticker, sec.sector]))} />
            ) : (
              <EmptyState title="No portfolio run yet">
                Choose at least two securities that trade in the same currency and press Optimise. Every optimiser runs
                on the same estimates, so the differences between them are the methods, not the data.
              </EmptyState>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/** Every equity in the price file except the benchmark index, in the largest currency group. */
function defaultConfig(securities: Security[]): PortfolioConfig {
  const equities = securities.filter((s) => s.sector !== BENCHMARK_SECTOR);
  const counts = new Map<string, number>();
  equities.forEach((s) => counts.set(s.currency, (counts.get(s.currency) ?? 0) + 1));
  const currency = [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0];
  const benchmark = securities.find((s) => s.sector === BENCHMARK_SECTOR);
  return {
    name: "",
    tickers: equities.filter((s) => s.currency === currency).map((s) => s.ticker),
    expected_returns: "mean_historical",
    risk_model: "ledoit_wolf",
    max_weight: 0.35,
    target_return: null,
    budget: 100000,
    credit_overlay: "cap_mixed",
    benchmark_ticker: benchmark?.ticker ?? null,
  };
}

/** The page headline states the selected run's result, with its numbers. */
function headline(run: PortfolioRun | null): ReactNode {
  const key = run?.calculation_basis.headline_portfolio;
  const best = key ? run?.results.portfolios[key] : undefined;
  if (!run || !key || best?.expected_return === undefined || best.volatility === undefined) {
    return (
      <>
        Six optimisers, <em>one</em> universe, every refusal explained
      </>
    );
  }
  return (
    <>
      {PORTFOLIO_LABELS[key]} earns <em>{pct(best.expected_return)}</em> at {pct(best.volatility)} volatility
    </>
  );
}

function summary(run: PortfolioRun | null): string {
  if (!run) {
    return "Mean-variance and Hierarchical Risk Parity over sourced monthly prices, with the FinSight credit verdict as a constraint and component VaR showing where the risk sits.";
  }
  const u = run.results.universe;
  return `${u.tickers.length} securities, ${u.observations} months from ${u.start} to ${u.end}, in ${u.currency}. In-sample: a description of the past, not a forecast.`;
}

function ConfigPanel({
  securities,
  config,
  onChange,
  busy,
  onSubmit,
}: {
  securities: Security[];
  config: PortfolioConfig;
  onChange: (next: PortfolioConfig) => void;
  busy: boolean;
  onSubmit: () => void;
}) {
  const set = <K extends keyof PortfolioConfig>(key: K, value: PortfolioConfig[K]) => onChange({ ...config, [key]: value });
  const toggle = (ticker: string) =>
    set("tickers", config.tickers.includes(ticker) ? config.tickers.filter((t) => t !== ticker) : [...config.tickers, ticker]);
  const equities = securities.filter((s) => s.sector !== BENCHMARK_SECTOR);

  return (
    <form
      className="sheet space-y-5 p-4"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <div>
        <p className="section-no">Universe</p>
        <p className="mt-1 text-xs text-muted-foreground">{config.tickers.length} selected. Mixed currencies are refused.</p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {equities.map((s) => {
            const on = config.tickers.includes(s.ticker);
            return (
              <button
                key={s.ticker}
                type="button"
                aria-pressed={on}
                title={`${s.name}, ${s.sector ?? "sector not recorded"}, ${s.currency}`}
                onClick={() => toggle(s.ticker)}
                className={`inline-flex h-8 items-center gap-1 rounded-sm border px-2 font-mono text-xs transition-colors duration-120 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring ${
                  on ? "border-primary/40 bg-brand-tint text-foreground" : "border-border-strong text-muted-foreground hover:bg-surface-2"
                }`}
              >
                {s.ticker}
                {s.currency !== "USD" && <span className="text-2xs text-muted-foreground">{s.currency}</span>}
              </button>
            );
          })}
        </div>
      </div>

      <Segmented
        label="Expected returns"
        value={config.expected_returns}
        options={[
          ["mean_historical", "Historical"],
          ["ema_historical", "EMA"],
          ["capm", "CAPM"],
        ]}
        onChange={(v) => set("expected_returns", v)}
      />
      <Segmented
        label="Risk model"
        value={config.risk_model}
        options={[
          ["ledoit_wolf", "Ledoit-Wolf"],
          ["sample", "Sample"],
        ]}
        onChange={(v) => set("risk_model", v)}
      />

      <div className="grid grid-cols-2 gap-3">
        <PercentField label="Max weight" value={config.max_weight} onChange={(v) => set("max_weight", v ?? 1)} />
        <PercentField label="Target return" value={config.target_return ?? null} optional onChange={(v) => set("target_return", v)} />
      </div>
      <label className="block">
        <span className="label">Budget for whole shares</span>
        <input
          className="field font-mono"
          type="number"
          min={1}
          step="any"
          inputMode="decimal"
          value={config.budget ?? ""}
          onChange={(e) => set("budget", e.target.value === "" ? null : Number(e.target.value))}
        />
      </label>
      <label className="block">
        <span className="label">Credit overlay</span>
        <select className="field" value={config.credit_overlay} onChange={(e) => set("credit_overlay", e.target.value as CreditOverlay)}>
          {OVERLAYS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <span className="mt-1 block text-xs text-muted-foreground">Uses the stored consensus verdict of any company linked to a ticker.</span>
      </label>
      <label className="block">
        <span className="label">Run name</span>
        <input className="field" value={config.name ?? ""} onChange={(e) => set("name", e.target.value)} placeholder="Machinery against IT services" />
      </label>
      <ActionButton type="submit" busy={busy} disabled={config.tickers.length < 2} busyLabel="Optimising">
        Optimise
      </ActionButton>
    </form>
  );
}

function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: [T, string][];
  onChange: (value: T) => void;
}) {
  return (
    <div>
      <span className="label">{label}</span>
      <div className="segmented" role="radiogroup" aria-label={label}>
        {options.map(([key, text]) => (
          <button
            key={key}
            type="button"
            role="radio"
            aria-checked={value === key}
            className={`segment ${value === key ? "segment-active" : ""}`}
            onClick={() => onChange(key)}
          >
            {text}
          </button>
        ))}
      </div>
    </div>
  );
}

/** A fraction edited as a percentage; empty means "not set" when the field is optional. */
function PercentField({
  label,
  value,
  optional,
  onChange,
}: {
  label: string;
  value: number | null;
  optional?: boolean;
  onChange: (value: number | null) => void;
}) {
  return (
    <label className="block">
      <span className="label">
        {label}
        {optional ? ", optional" : ""}
      </span>
      <span className="relative block">
        <input
          className="field pr-8 font-mono"
          type="number"
          step="any"
          inputMode="decimal"
          value={value === null ? "" : Number((value * 100).toFixed(4))}
          placeholder={optional ? "none" : undefined}
          onChange={(e) => onChange(e.target.value === "" ? (optional ? null : 1) : Number(e.target.value) / 100)}
        />
        <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-xs text-muted-foreground">%</span>
      </span>
    </label>
  );
}

function RunHistory({ runs, activeId, onOpen }: { runs: PortfolioRunSummary[]; activeId?: string; onOpen: (id: string) => void }) {
  if (runs.length === 0) return null;
  return (
    <section className="sheet">
      <p className="section-no border-b border-border px-4 py-3">Recent runs</p>
      <ul className="divide-y divide-border">
        {runs.map((r) => (
          <li key={r.id}>
            <button
              type="button"
              onClick={() => onOpen(r.id)}
              aria-current={r.id === activeId ? "true" : undefined}
              className={`block w-full px-4 py-2.5 text-left transition-colors duration-120 hover:bg-surface-2 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring ${
                r.id === activeId ? "bg-brand-tint" : ""
              }`}
            >
              <span className="block truncate text-sm text-foreground">{r.name || `${r.tickers.length} securities`}</span>
              <span className="mt-0.5 block font-mono text-2xs text-muted-foreground">
                {stamp(r.run_at)} · Sharpe {num(r.sharpe_ratio)}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
