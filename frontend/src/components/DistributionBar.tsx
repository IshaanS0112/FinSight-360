import { num } from "./format";

/** A p5 / p50 / p95 band for one simulated quantity.
 *
 *  A band, not a histogram: the useful questions are "how wide" and "where is
 *  the middle", and two ends plus a median mark answer both.
 */
export default function DistributionBar({
  label,
  p5,
  p50,
  p95,
  pointEstimate,
  digits = 2,
}: {
  label: string;
  p5: number;
  p50: number;
  p95: number;
  pointEstimate?: number | null;
  digits?: number;
}) {
  const lo = Math.min(p5, pointEstimate ?? p5);
  const hi = Math.max(p95, pointEstimate ?? p95);
  const span = hi - lo || 1;
  const at = (value: number) => `${(((value - lo) / span) * 100).toFixed(2)}%`;

  return (
    <div className="py-2">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <span className="text-sm text-foreground">{label}</span>
        <span className="font-mono text-xs text-muted-foreground">
          p5 {num(p5, digits)} · p50 <span className="text-foreground">{num(p50, digits)}</span> · p95{" "}
          {num(p95, digits)}
        </span>
      </div>
      <div className="relative mt-2 h-3">
        <div className="absolute inset-x-0 top-1/2 h-px bg-border" />
        <div
          className="absolute inset-y-0.5 rounded-sm bg-chart-3"
          style={{ left: at(p5), right: `calc(100% - ${at(p95)})` }}
        />
        <div className="absolute inset-y-0 w-0.5 bg-foreground" style={{ left: at(p50) }} />
        {pointEstimate !== null && pointEstimate !== undefined && (
          <div
            className="absolute -inset-y-0.5 w-0.5 bg-primary"
            style={{ left: at(pointEstimate) }}
            title={`Point estimate ${num(pointEstimate, digits)}`}
          />
        )}
      </div>
    </div>
  );
}
