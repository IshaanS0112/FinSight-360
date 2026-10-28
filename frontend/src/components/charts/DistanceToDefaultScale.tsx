import { inverseNormal, num } from "../format";
import Legend, { Swatch } from "./Legend";

const AXIS_MAX = 8;

/**
 * Distance-to-default on a 0-8 axis, banded by the same probability cutoffs the
 * market view uses (PD = N(-DD)), with the solved Merton DD and the naive
 * Bharath-Shumway DD marked. A DD beyond the axis is pinned to the end and its
 * value printed. Zones are labelled, so the reading never rests on colour.
 */
export default function DistanceToDefaultScale({
  solved,
  naive,
  bands,
}: {
  solved: number | null;
  naive: number | null;
  bands: { low_pd_below: number; high_pd_above: number };
}) {
  const highRiskBelow = -inverseNormal(bands.high_pd_above);
  const lowRiskAbove = -inverseNormal(bands.low_pd_below);
  const at = (dd: number) => `${(Math.max(0, Math.min(dd, AXIS_MAX)) / AXIS_MAX) * 100}%`;
  const zones = [
    { from: 0, to: highRiskBelow, label: `PD above ${pctLabel(bands.high_pd_above)}`, tone: "bg-destructive/15" },
    { from: highRiskBelow, to: lowRiskAbove, label: "Between", tone: "bg-warning/15" },
    { from: lowRiskAbove, to: AXIS_MAX, label: `PD below ${pctLabel(bands.low_pd_below)}`, tone: "bg-success/15" },
  ];

  return (
    <div>
      <Legend
        items={[
          { swatch: Swatch.square("bg-foreground"), label: "Merton, solved (1974)" },
          { swatch: Swatch.ring("border-muted-foreground"), label: "Naive closed form (Bharath-Shumway 2008)" },
        ]}
      />
      <div className="relative mt-8 mb-10 h-9">
        {zones.map((zone) => (
          <div
            key={zone.label}
            className={`absolute inset-y-0 flex items-center justify-center overflow-hidden border-x border-card ${zone.tone}`}
            style={{ left: at(zone.from), right: `calc(100% - ${at(zone.to)})` }}
          >
            <span className="truncate px-1 font-mono text-2xs text-foreground">{zone.label}</span>
          </div>
        ))}
        {naive !== null && <Marker value={naive} at={at(naive)} kind="naive" />}
        {solved !== null && <Marker value={solved} at={at(solved)} kind="solved" />}
        {[0, 2, 4, 6, 8].map((tick) => (
          <span
            key={tick}
            className="absolute top-full mt-1 -translate-x-1/2 font-mono text-2xs text-muted-foreground"
            style={{ left: at(tick) }}
          >
            {tick === AXIS_MAX ? `${tick}+` : tick}
          </span>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">
        Distance to default in standard deviations of asset value. Bands from the market-view cutoffs:
        DD {num(highRiskBelow, 2)} is a {pctLabel(bands.high_pd_above)} default probability, DD{" "}
        {num(lowRiskAbove, 2)} is {pctLabel(bands.low_pd_below)}.
      </p>
    </div>
  );
}

function Marker({ value, at, kind }: { value: number; at: string; kind: "solved" | "naive" }) {
  const solved = kind === "solved";
  const clipped = value > AXIS_MAX;
  return (
    <div className="absolute inset-y-0" style={{ left: at }}>
      <div className={`absolute -inset-y-1 -translate-x-1/2 ${solved ? "w-1 bg-foreground" : "w-0.5 bg-muted-foreground"}`} />
      <span
        className={`absolute -translate-x-1/2 whitespace-nowrap font-mono text-2xs ${
          solved ? "bottom-full mb-2 text-foreground" : "top-full mt-5 text-muted-foreground"
        } ${clipped ? "-translate-x-full" : ""}`}
      >
        {solved ? "Merton" : "Naive"} {num(value, 2)}
        {clipped ? " →" : ""}
      </span>
    </div>
  );
}

function pctLabel(fraction: number): string {
  return `${num(fraction * 100, fraction < 0.01 ? 1 : 0)}%`;
}
