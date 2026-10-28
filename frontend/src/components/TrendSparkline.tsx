/** A sparkline, hand-drawn in SVG so the line weight matches the ledger rules.
 *
 *  Two points render as a straight segment with an endpoint dot: a smooth curve
 *  through two points would imply data that does not exist. Direction is also
 *  carried by the signed change next to it, never by colour alone.
 */
export default function TrendSparkline({
  points,
  direction,
  width = 96,
  height = 26,
}: {
  points: number[];
  direction?: "up" | "down" | "flat";
  width?: number;
  height?: number;
}) {
  if (points.length < 2) {
    return <span className="font-mono text-2xs text-muted-foreground">one year</span>;
  }

  const pad = 3;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || Math.abs(max) || 1;
  const stepX = (width - pad * 2) / (points.length - 1);

  const coords = points.map((value, index) => {
    const x = pad + index * stepX;
    const y = height - pad - ((value - min) / span) * (height - pad * 2);
    return [x, y] as const;
  });
  const path = coords.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const [lastX, lastY] = coords[coords.length - 1];
  const stroke =
    direction === "up" ? "var(--success)" : direction === "down" ? "var(--destructive)" : "var(--muted-foreground)";

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <path d={path} fill="none" stroke={stroke} strokeWidth="1.5" strokeLinecap="round" />
      <circle cx={lastX} cy={lastY} r="2.5" fill={stroke} />
    </svg>
  );
}
