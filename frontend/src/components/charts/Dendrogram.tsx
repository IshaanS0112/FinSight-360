import { useMemo } from "react";

import { pct } from "../format";
import { linear } from "./scale";
import { useElementWidth } from "./useElementWidth";

const MARGIN = { top: 12, right: 8, bottom: 56, left: 8 };

/**
 * The single-linkage tree Hierarchical Risk Parity clusters on, drawn from the
 * SciPy linkage matrix ([child_a, child_b, distance, size] per merge). Leaves sit
 * in HRP's quasi-diagonal order with each asset's HRP weight underneath, so the
 * first split, the one HRP allocates across first, reads left to right.
 */
export default function Dendrogram({
  tickers,
  order,
  linkage,
  weights,
}: {
  tickers: string[];
  order: number[];
  linkage: number[][];
  weights: Record<string, number>;
}) {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const height = 240;
  const narrow = width / Math.max(1, order.length) < 52;

  const links = useMemo(() => {
    const n = tickers.length;
    const slot = (width - MARGIN.left - MARGIN.right) / n;
    const position = new Map(order.map((leaf, i) => [leaf, MARGIN.left + slot * (i + 0.5)]));
    const maxDistance = Math.max(...linkage.map((row) => row[2]), 1e-9);
    const y = linear([0, maxDistance], [height - MARGIN.bottom, MARGIN.top]);
    const nodes: { x: number; h: number }[] = tickers.map((_, leaf) => ({ x: position.get(leaf) ?? 0, h: 0 }));
    return linkage.map(([a, b, distance]) => {
      const left = nodes[a];
      const right = nodes[b];
      nodes.push({ x: (left.x + right.x) / 2, h: distance });
      return `M${left.x.toFixed(1)} ${y(left.h).toFixed(1)}V${y(distance).toFixed(1)}H${right.x.toFixed(1)}V${y(right.h).toFixed(1)}`;
    });
  }, [tickers, order, linkage, width]);

  const slot = (width - MARGIN.left - MARGIN.right) / tickers.length;
  return (
    <div ref={ref}>
      <svg width={width} height={height} role="img" aria-label={`HRP cluster tree. Leaf order: ${order.map((i) => tickers[i]).join(", ")}.`}>
        {links.map((d, i) => (
          <path key={i} d={d} fill="none" stroke={i === links.length - 1 ? "var(--foreground)" : "var(--muted-foreground)"} strokeWidth="1.5" />
        ))}
        {order.map((leaf, i) => {
          const cx = MARGIN.left + slot * (i + 0.5);
          const base = height - MARGIN.bottom + 14;
          return (
            <g key={tickers[leaf]}>
              <text
                x={cx}
                y={base}
                textAnchor={narrow ? "end" : "middle"}
                transform={narrow ? `rotate(-40 ${cx} ${base})` : undefined}
                className="fill-foreground font-mono text-2xs"
              >
                {tickers[leaf]}
              </text>
              {!narrow && (
                <text x={cx} y={base + 16} textAnchor="middle" className="fill-muted-foreground font-mono text-2xs">
                  {pct(weights[tickers[leaf]] ?? 0)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
