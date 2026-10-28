import { num } from "./format";

/** A 0-100 dial for the health composite.
 *
 *  The tick at 50 is drawn because 50 is the only value with an external
 *  meaning on this scale: exactly at benchmark.
 */
export default function GaugeDial({
  score,
  percentile,
}: {
  score: number | null;
  percentile?: number | null;
}) {
  const width = 200;
  const height = 112;
  const cx = width / 2;
  const cy = height - 12;
  const radius = 82;

  const point = (fraction: number, r = radius) => {
    const angle = Math.PI * (1 - fraction);
    return [cx + r * Math.cos(angle), cy - r * Math.sin(angle)] as const;
  };

  const arc = (from: number, to: number, r = radius) => {
    const [x1, y1] = point(from, r);
    const [x2, y2] = point(to, r);
    return `M${x1.toFixed(2)} ${y1.toFixed(2)} A${r} ${r} 0 0 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`;
  };

  const fraction = score === null ? 0 : Math.max(0, Math.min(1, score / 100));
  const [markX, markY] = point(0.5, radius + 8);
  const [markInnerX, markInnerY] = point(0.5, radius - 8);

  return (
    <div className="flex flex-col items-center">
      <p className="text-xs text-muted-foreground">Health composite</p>
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={score === null ? "No health score" : `Health score ${num(score)} of 100`}
      >
        <path d={arc(0, 1)} fill="none" stroke="var(--surface-2)" strokeWidth="8" strokeLinecap="round" />
        {score !== null && (
          <path
            d={arc(0, Math.max(fraction, 0.002))}
            fill="none"
            stroke="var(--primary)"
            strokeWidth="8"
            strokeLinecap="round"
          />
        )}
        <line x1={markInnerX} y1={markInnerY} x2={markX} y2={markY} stroke="var(--foreground)" strokeWidth="1.5" />
        <text x={cx} y={cy - 20} textAnchor="middle" className="fill-foreground font-mono text-3xl">
          {score === null ? "—" : num(score, 1)}
        </text>
        <text x={cx} y={cy - 2} textAnchor="middle" className="fill-muted-foreground font-mono text-2xs">
          of 100
        </text>
      </svg>
      <p className="mt-1 text-center text-xs text-muted-foreground">Tick marks 50: exactly at benchmark</p>
      <p className="mt-1 text-center text-xs text-muted-foreground">
        {percentile === null || percentile === undefined ? (
          <>Peer percentile withheld: no sourced peer set</>
        ) : (
          <>
            Peer percentile <span className="font-mono text-foreground">{num(percentile, 1)}</span>
          </>
        )}
      </p>
    </div>
  );
}
