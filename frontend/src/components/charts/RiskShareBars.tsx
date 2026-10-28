import type { RiskComponent } from "../../api/types";
import { pct } from "../format";
import Legend, { Swatch } from "./Legend";

/**
 * Each holding's share of portfolio VaR as a bar, with its weight as a tick on
 * the same scale. The holding whose risk share most exceeds its weight is the
 * one cobalt bar; it is the finding the section title states.
 */
export default function RiskShareBars({ components }: { components: RiskComponent[] }) {
  const held = components.filter((c) => c.weight > 1e-6).sort((a, b) => b.share_of_risk - a.share_of_risk);
  const scaleMax = Math.max(...held.flatMap((c) => [c.share_of_risk, c.weight]), 1e-9);
  const standout = mostOverweightInRisk(held);
  const at = (value: number) => `${(Math.max(0, value) / scaleMax) * 100}%`;

  return (
    <div>
      <Legend
        items={[
          { swatch: Swatch.square("bg-chart-2"), label: "Share of portfolio VaR" },
          { swatch: <span className="inline-block h-3 w-0.5 bg-foreground" />, label: "Portfolio weight" },
        ]}
      />
      <ul className="mt-4 space-y-2.5">
        {held.map((c) => (
          <li key={c.ticker} className="grid grid-cols-[4rem_minmax(0,1fr)_auto] items-center gap-3">
            <span className="font-mono text-xs text-foreground">{c.ticker}</span>
            <span className="relative h-4">
              <span
                className={`absolute inset-y-0 left-0 rounded-r-sm ${c.ticker === standout?.ticker ? "bg-primary" : "bg-chart-2"}`}
                style={{ width: at(c.share_of_risk) }}
              />
              <span className="absolute -inset-y-1 w-0.5 bg-foreground" style={{ left: at(c.weight) }} />
            </span>
            <span className="whitespace-nowrap text-right font-mono text-xs text-muted-foreground">
              <span className="text-foreground">{pct(c.share_of_risk)}</span> risk · {pct(c.weight)} weight
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The holding with the largest gap between its share of risk and its weight. */
export function mostOverweightInRisk(components: RiskComponent[]): RiskComponent | undefined {
  return [...components]
    .filter((c) => c.weight > 1e-6)
    .sort((a, b) => b.share_of_risk - b.weight - (a.share_of_risk - a.weight))[0];
}
