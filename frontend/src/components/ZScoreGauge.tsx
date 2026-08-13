import type { BankruptcyRisk } from "../api/types";

const ZONE_STYLE: Record<string, string> = {
  SAFE: "border-safe/40 bg-safe/10 text-safe",
  GREY: "border-grey/40 bg-grey/10 text-grey",
  DISTRESS: "border-distress/40 bg-distress/10 text-distress",
  NOT_APPLICABLE: "border-edge bg-panel text-muted",
};

const MODEL_LABEL: Record<string, string> = {
  Z_1968: "Altman Z (1968)",
  Z_PRIME: "Altman Z′",
  Z_DOUBLE_PRIME: "Altman Z″",
};

/**
 * The score, the zone, and the per-component decomposition that produced it.
 *
 * The decomposition is not decoration. A single Z number invites the question
 * "where does that come from", and the honest answer is five weighted ratios --
 * so the component table is shown by default rather than hidden behind a toggle.
 */
export default function ZScoreGauge({ risk }: { risk: BankruptcyRisk }) {
  const cutoffs = risk.calculation_basis.cutoffs;
  const zoneStyle = ZONE_STYLE[risk.zone] ?? ZONE_STYLE.NOT_APPLICABLE;

  // Position on the bar: the distress cutoff and the safe cutoff anchor the
  // middle band, with one band's width of runway on either side.
  const position = (() => {
    if (risk.altman_z_score === null || !cutoffs) return null;
    const { distress_below: low, safe_above: high } = cutoffs;
    const span = high - low;
    const min = low - span;
    const max = high + span;
    const pct = ((risk.altman_z_score - min) / (max - min)) * 100;
    return Math.max(0, Math.min(100, pct));
  })();

  return (
    <section className="panel p-5">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wider text-muted">
            Bankruptcy risk
          </h2>
          <p className="mt-1 text-xs text-muted">
            {MODEL_LABEL[risk.model] ?? risk.model} · X4 uses{" "}
            {risk.calculation_basis.x4_equity_basis === "MARKET_VALUE"
              ? "market value"
              : "book value"}{" "}
            of equity
          </p>
        </div>
        <div className="text-right">
          <div className="stat text-3xl font-semibold text-slate-100">
            {risk.altman_z_score ?? "—"}
          </div>
          <span className={`chip mt-1 ${zoneStyle}`}>{risk.zone.replace("_", " ")}</span>
        </div>
      </div>

      {position !== null && cutoffs && (
        <div className="mb-4">
          <div className="relative h-2 overflow-hidden rounded-full bg-ink">
            <div className="absolute inset-y-0 left-0 w-1/3 bg-distress/30" />
            <div className="absolute inset-y-0 left-1/3 w-1/3 bg-grey/30" />
            <div className="absolute inset-y-0 left-2/3 w-1/3 bg-safe/30" />
            <div
              className="absolute -top-1 h-4 w-0.5 bg-slate-100"
              style={{ left: `${position}%` }}
            />
          </div>
          <div className="mt-1 flex justify-between text-[11px] text-muted">
            <span>distress &lt; {cutoffs.distress_below}</span>
            <span>grey</span>
            <span>safe &gt; {cutoffs.safe_above}</span>
          </div>
        </div>
      )}

      {risk.calculation_basis.borderline && (
        <p className="mb-3 rounded border border-grey/40 bg-grey/10 p-2 text-xs text-grey">
          Borderline: the score sits within {String(risk.calculation_basis.borderline_margin ?? "")}
          {" "}of a cutoff, so treat the zone as provisional rather than a verdict.
        </p>
      )}

      {risk.calculation_basis.partial_score_warning && (
        <p className="mb-3 rounded border border-grey/40 bg-grey/10 p-2 text-xs text-grey">
          {risk.calculation_basis.partial_score_warning}
        </p>
      )}

      {risk.zone === "NOT_APPLICABLE" && (
        <p className="mb-3 rounded border border-edge bg-ink p-3 text-xs leading-relaxed text-muted">
          {risk.calculation_basis.model_selection}
        </p>
      )}

      {Object.keys(risk.component_scores).length > 0 && (
        <table className="w-full text-left text-xs">
          <thead className="text-muted">
            <tr className="border-b border-edge">
              <th className="py-2 font-medium">Component</th>
              <th className="py-2 font-medium">Definition</th>
              <th className="py-2 text-right font-medium">Ratio</th>
              <th className="py-2 text-right font-medium">×</th>
              <th className="py-2 text-right font-medium">Contribution</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(risk.component_scores).map(([key, value]) => (
              <tr key={key} className="border-b border-edge/50 last:border-0">
                <td className="py-2 font-mono uppercase text-slate-300">{key}</td>
                <td className="py-2 font-mono text-[11px] text-muted">
                  {risk.calculation_basis.component_definitions?.[key] ?? ""}
                </td>
                <td className="stat py-2 text-right text-slate-300">{value.ratio.toFixed(4)}</td>
                <td className="stat py-2 text-right text-muted">{value.coefficient}</td>
                <td
                  className={`stat py-2 text-right ${
                    value.contribution < 0 ? "text-distress" : "text-slate-100"
                  }`}
                >
                  {value.contribution.toFixed(4)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {risk.omitted_components.length > 0 && (
        <div className="mt-3 rounded border border-edge bg-ink p-3 text-xs">
          <p className="mb-1 font-medium text-grey">Components omitted (unknown, not zero)</p>
          <ul className="space-y-1 text-muted">
            {risk.omitted_components.map((entry) => (
              <li key={entry.component}>
                <span className="font-mono uppercase text-slate-400">{entry.component}</span>{" "}
                — {entry.reason}
              </li>
            ))}
          </ul>
        </div>
      )}

      <details className="mt-3 text-xs text-muted">
        <summary className="cursor-pointer hover:text-accent">Model provenance</summary>
        <p className="mt-2 leading-relaxed">{risk.calculation_basis.citation}</p>
        <p className="mt-2 leading-relaxed">{risk.calculation_basis.model_selection}</p>
        <p className="mt-2 font-mono text-[11px]">{risk.calculation_basis.formula}</p>
      </details>
    </section>
  );
}
