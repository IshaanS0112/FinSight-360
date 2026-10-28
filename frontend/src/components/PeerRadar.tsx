import { CATEGORY_LABELS, num } from "./format";

/** Four-axis radar of category percentiles against the peer set.
 *
 *  The dashed 50th-percentile ring is the peer median, the reference the shape
 *  is read against.
 */
export default function PeerRadar({
  percentiles,
}: {
  percentiles: Record<string, number | null>;
}) {
  const axes = ["profitability", "liquidity", "leverage", "efficiency"];
  const size = 300;
  const cx = size / 2;
  const cy = size / 2 + 6;
  const radius = 84;

  const at = (index: number, fraction: number) => {
    const angle = -Math.PI / 2 + (index * 2 * Math.PI) / axes.length;
    return [cx + radius * fraction * Math.cos(angle), cy + radius * fraction * Math.sin(angle)] as const;
  };
  const ring = (fraction: number) =>
    axes.map((_, index) => at(index, fraction).map((v) => v.toFixed(1)).join(",")).join(" ");
  const polygon = axes
    .map((axis, index) => at(index, (percentiles[axis] ?? 0) / 100).map((v) => v.toFixed(1)).join(","))
    .join(" ");

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      className="max-w-full"
      role="img"
      aria-label="Category percentiles against the peer set"
    >
      {[0.25, 0.75, 1].map((fraction) => (
        <polygon key={fraction} points={ring(fraction)} fill="none" stroke="var(--border)" strokeWidth="1" />
      ))}
      <polygon points={ring(0.5)} fill="none" stroke="var(--muted-foreground)" strokeDasharray="3 3" strokeWidth="1" />
      {axes.map((_, index) => {
        const [x, y] = at(index, 1);
        return <line key={index} x1={cx} y1={cy} x2={x} y2={y} stroke="var(--border)" strokeWidth="1" />;
      })}
      <polygon points={polygon} fill="var(--brand-tint)" stroke="var(--primary)" strokeWidth="2" />
      {axes.map((axis, index) => {
        const [x, y] = at(index, 1.27);
        const value = percentiles[axis];
        // Anchor by position, or the left and right labels clip at the edge.
        const anchor = index === 1 ? "end" : index === 3 ? "start" : "middle";
        return (
          <g key={axis}>
            <text x={x} y={y - 3} textAnchor={anchor} className="fill-muted-foreground text-2xs">
              {CATEGORY_LABELS[axis]}
            </text>
            <text x={x} y={y + 11} textAnchor={anchor} className="fill-foreground font-mono text-xs">
              {value === null || value === undefined ? "—" : num(value, 0)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
