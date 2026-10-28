import { useState } from "react";

import ActionButton from "../components/ActionButton";
import DistributionBar from "../components/DistributionBar";
import Legend, { Swatch } from "../components/charts/Legend";
import ScheduleCard from "../components/ScheduleCard";
import { ALTMAN_LABELS, human, money, num, signed } from "../components/format";
import type { Company, DcfValuation, ScenarioRun } from "../api/types";
import type { DcfDraft } from "../api/client";

const SLIDERS = [
  { key: "revenue_growth", label: "Revenue growth", min: -0.2, max: 0.25, step: 0.005 },
  { key: "terminal_growth", label: "Terminal growth", min: 0, max: 0.06, step: 0.0025 },
  { key: "beta", label: "Beta", min: 0.2, max: 2.5, step: 0.05 },
  { key: "risk_free_rate", label: "Risk-free rate", min: 0, max: 0.12, step: 0.0025 },
  { key: "equity_risk_premium", label: "Equity risk premium", min: 0.01, max: 0.12, step: 0.0025 },
  { key: "tax_rate", label: "Tax rate", min: 0, max: 0.5, step: 0.01 },
] as const;

export default function Valuation({
  company,
  valuation,
  scenario,
  onRun,
  onSimulate,
  busy,
}: {
  company: Company;
  valuation: DcfValuation | null;
  scenario: ScenarioRun | null;
  onRun: (draft: DcfDraft) => Promise<void>;
  onSimulate: () => Promise<void>;
  busy: string | null;
}) {
  const [draft, setDraft] = useState<DcfDraft>({});
  const applied = valuation?.assumptions;
  const value = (key: (typeof SLIDERS)[number]["key"]) =>
    draft[key] ?? applied?.[key] ?? DEFAULTS[key];

  const refusal = valuation?.calculation_basis?.refusal as string | undefined;
  const negativeEbit = valuation?.calculation_basis?.negative_ebit_warning as string | undefined;
  const omitted = (valuation?.calculation_basis?.omitted ?? []) as { input: string; reason: string }[];
  const terminalShare = valuation?.calculation_basis?.terminal_value_share_of_ev as number | undefined;
  const betaNote = valuation?.calculation_basis?.beta_note as string | undefined;

  return (
    <div className="space-y-6">
      <ScheduleCard
        reference="Schedule 12"
        title="DCF assumptions"
        aside={
          <ActionButton busy={busy === "valuation"} disabled={busy !== null} onClick={() => void onRun(draft)} busyLabel="Discounting">
            {valuation ? "Recompute" : "Value the company"}
          </ActionButton>
        }
        note={
          <>
            Every assumption is a labelled, adjustable input, and the set that produced the figures below is stored
            with them. {betaNote}
          </>
        }
      >
        <div className="grid gap-x-6 gap-y-3 px-4 py-4 sm:grid-cols-2 lg:grid-cols-3">
          {SLIDERS.map((slider) => (
            <label key={slider.key} className="block">
              <span className="flex items-baseline justify-between">
                <span className="label mb-0">{slider.label}</span>
                <span className="font-mono text-xs text-foreground">
                  {slider.key === "beta" ? num(value(slider.key), 2) : `${num(value(slider.key) * 100, 2)}%`}
                </span>
              </span>
              <input
                type="range"
                className="mt-1 w-full accent-primary"
                min={slider.min}
                max={slider.max}
                step={slider.step}
                value={value(slider.key)}
                onChange={(event) =>
                  setDraft((current) => ({ ...current, [slider.key]: Number(event.target.value) }))
                }
              />
            </label>
          ))}
        </div>
      </ScheduleCard>

      {refusal && (
        <ScheduleCard reference="Refusal" title="No valuation was produced">
          <p className="sheet-note text-destructive">{refusal}</p>
        </ScheduleCard>
      )}

      {omitted.length > 0 && !refusal && (
        <ScheduleCard reference="Refusal" title="Missing inputs">
          <ul className="space-y-2 px-4 py-3">
            {omitted.map((entry) => (
              <li key={entry.input} className="text-xs leading-relaxed text-foreground">
                <span className="font-mono text-xs text-foreground">{entry.input}</span>: {entry.reason}
              </li>
            ))}
          </ul>
        </ScheduleCard>
      )}

      {valuation?.enterprise_value !== null && valuation !== null && (
        <>
          <ScheduleCard
            reference="Schedule 13"
            title="Free cash flow to the firm"
            aside={
              <span className="chip-neutral">
                WACC {valuation.wacc === null ? "—" : `${num(valuation.wacc * 100, 2)}%`}
              </span>
            }
            note={valuation.calculation_basis?.driver_note as string | undefined}
          >
            <div className="overflow-x-auto">
              <table className="ledger">
                <thead>
                  <tr>
                    <th>Year</th>
                    <th className="text-right">Revenue</th>
                    <th className="text-right">EBIT</th>
                    <th className="text-right">NOPAT</th>
                    <th className="text-right">+ D&amp;A</th>
                    <th className="text-right">− CapEx</th>
                    <th className="text-right">− ΔNWC</th>
                    <th className="text-right">FCFF</th>
                    <th className="text-right">PV</th>
                  </tr>
                </thead>
                <tbody>
                  {valuation.fcff_projection.map((row) => (
                    <tr key={row.year}>
                      <td className="font-mono text-2xs text-foreground">+{row.year}</td>
                      <td className="num-dim">{money(row.revenue)}</td>
                      <td className="num-dim">{money(row.ebit)}</td>
                      <td className="num-dim">{money(row.nopat)}</td>
                      <td className="num-dim">{money(row.depreciation_amortization)}</td>
                      <td className="num-dim">{money(row.capital_expenditure)}</td>
                      <td className="num-dim">{money(row.change_in_nwc)}</td>
                      <td className="num">{money(row.fcff)}</td>
                      <td className="num">{money(row.present_value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </ScheduleCard>

          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Figure label="Enterprise value" value={money(valuation.enterprise_value)} unit={company.units} />
            <Figure label="Equity value" value={money(valuation.equity_value)} unit={company.units} />
            <Figure
              label="Implied share price"
              value={valuation.implied_share_price === null ? "—" : num(valuation.implied_share_price)}
              unit={company.currency}
            />
            <Figure
              label="vs. year-end price"
              value={
                valuation.upside_downside_pct === null
                  ? "—"
                  : `${signed(valuation.upside_downside_pct, 1)}%`
              }
              tone={
                valuation.upside_downside_pct === null
                  ? "text-muted-foreground"
                  : valuation.upside_downside_pct >= 0
                    ? "text-success"
                    : "text-destructive"
              }
            />
          </div>

          {terminalShare !== undefined && (
            <ScheduleCard reference="Diagnostic" title="How much of this is the terminal value">
              <div className="px-4 py-4">
                <div className="h-3 w-full border border-border bg-surface-2">
                  <div
                    className="h-full bg-primary"
                    style={{ width: `${Math.min(100, terminalShare * 100).toFixed(1)}%` }}
                  />
                </div>
                <p className="mt-2 font-mono text-sm text-foreground">
                  {num(terminalShare * 100, 1)}% of enterprise value
                </p>
                <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                  {valuation.calculation_basis?.terminal_value_note as string}
                </p>
              </div>
            </ScheduleCard>
          )}

          {negativeEbit && (
            <ScheduleCard reference="Warning" title="Negative base-year operating profit">
              <p className="sheet-note text-destructive">{negativeEbit}</p>
            </ScheduleCard>
          )}
        </>
      )}

      <ScheduleCard
        reference="Schedule 14"
        title="Monte Carlo: how much the answer depends on the assumptions"
        aside={
          <ActionButton
            variant="secondary"
            busy={busy === "scenario"}
            disabled={busy !== null}
            onClick={() => void onSimulate()}
            busyLabel="Simulating"
          >
            {scenario ? "Re-run" : "Run 5,000 trials"}
          </ActionButton>
        }
        note={
          scenario
            ? (scenario.calculation_basis?.perturbation_model as string)
            : "The simulator adds no model. It re-runs the same Altman, Ohlson, health-score and DCF code under sampled inputs and reports the spread."
        }
      >
        {scenario && (
          <div className="px-4 py-3">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
              <p className="font-mono text-2xs uppercase tracking-label text-muted-foreground">
                {scenario.n_trials.toLocaleString("en-US")} trials · seed {scenario.seed} ·{" "}
                {scenario.result_summary.dcf_trials_refused} produced no valuation
              </p>
              <Legend
                items={[
                  { swatch: Swatch.square("bg-chart-3"), label: "p5 to p95" },
                  { swatch: <span className="inline-block h-3 w-0.5 bg-foreground" />, label: "Median" },
                  { swatch: <span className="inline-block h-3 w-0.5 bg-primary" />, label: "Point estimate" },
                ]}
              />
            </div>
            {scenario.result_summary.z_score && (
              <DistributionBar
                label={`Altman ${ALTMAN_LABELS[scenario.result_summary.altman_model] ?? scenario.result_summary.altman_model}`}
                p5={scenario.result_summary.z_score.p5}
                p50={scenario.result_summary.z_score.p50}
                p95={scenario.result_summary.z_score.p95}
              />
            )}
            {scenario.result_summary.health_score && (
              <DistributionBar
                label="Health composite"
                p5={scenario.result_summary.health_score.p5}
                p50={scenario.result_summary.health_score.p50}
                p95={scenario.result_summary.health_score.p95}
                digits={1}
              />
            )}
            {scenario.result_summary.dcf_equity_value && (
              <DistributionBar
                label="DCF equity value"
                p5={scenario.result_summary.dcf_equity_value.p5}
                p50={scenario.result_summary.dcf_equity_value.p50}
                p95={scenario.result_summary.dcf_equity_value.p95}
                pointEstimate={valuation?.equity_value}
                digits={0}
              />
            )}
            <div className="mt-3 flex flex-wrap gap-2 border-t border-border pt-3">
              {Object.entries(scenario.result_summary.zone_shares).map(([zone, share]) => (
                <span
                  key={zone}
                  className={
                    zone === "SAFE" ? "chip-safe" : zone === "DISTRESS" ? "chip-distress" : "chip-grey"
                  }
                >
                  {human(zone)} {num((share ?? 0) * 100, 1)}%
                </span>
              ))}
              <span className="chip-neutral">
                distress probability {num(scenario.result_summary.distress_probability * 100, 1)}%
              </span>
            </div>
            <p className="mt-2 text-2xs leading-relaxed text-muted-foreground">
              {scenario.calculation_basis?.distress_probability_meaning as string}
            </p>
          </div>
        )}
      </ScheduleCard>
    </div>
  );
}

const DEFAULTS: Record<string, number> = {
  revenue_growth: 0.03,
  terminal_growth: 0.025,
  beta: 1.0,
  risk_free_rate: 0.045,
  equity_risk_premium: 0.055,
  tax_rate: 0.25,
};

function Figure({
  label,
  value,
  unit,
  tone = "text-foreground",
}: {
  label: string;
  value: string;
  unit?: string;
  tone?: string;
}) {
  return (
    <div className="sheet p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`mt-1 font-mono text-2xl leading-tight ${tone}`}>{value}</p>
      {unit && <p className="mt-0.5 font-mono text-2xs text-muted-foreground">{unit.toLowerCase()}</p>}
    </div>
  );
}
