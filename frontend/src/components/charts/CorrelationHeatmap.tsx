import { useState } from "react";

import { num } from "../format";
import ChartTooltip from "./ChartTooltip";
import Legend, { Swatch } from "./Legend";
import { useElementWidth } from "./useElementWidth";

const LABEL = 56;
const MAX_TINT = 0.63;

/**
 * Pairwise return correlations, rows and columns in HRP's leaf order so the
 * clusters show up as blocks on the diagonal. One hue for positive correlation,
 * a second for negative, white at zero. The tint is capped so the printed value
 * in every cell keeps AA contrast.
 */
export default function CorrelationHeatmap({
  tickers,
  matrix,
  order,
}: {
  tickers: string[];
  matrix: number[][];
  order: number[];
}) {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const [hover, setHover] = useState<{ row: number; col: number } | null>(null);
  const n = order.length;
  const cell = Math.max(24, Math.min(44, Math.floor((width - LABEL) / n)));
  const size = LABEL + cell * n;

  return (
    <div>
      <Legend
        items={[
          { swatch: Swatch.square("bg-primary/60"), label: "Positive" },
          { swatch: Swatch.square("bg-chart-4/60"), label: "Negative" },
          { swatch: Swatch.square("border border-border bg-card"), label: "Zero" },
        ]}
      />
      <div ref={ref} className="relative mt-3 overflow-x-auto" onMouseLeave={() => setHover(null)}>
        <svg width={size} height={size} role="img" aria-label="Correlation matrix of monthly returns, ordered by the HRP tree">
          {order.map((leaf, i) => (
            <g key={tickers[leaf]}>
              <text x={LABEL - 6} y={LABEL + cell * i + cell / 2 + 4} textAnchor="end" className="fill-foreground font-mono text-2xs">
                {tickers[leaf]}
              </text>
              <text
                x={LABEL + cell * i + cell / 2}
                y={LABEL - 6}
                transform={`rotate(-45 ${LABEL + cell * i + cell / 2} ${LABEL - 6})`}
                className="fill-foreground font-mono text-2xs"
              >
                {tickers[leaf]}
              </text>
            </g>
          ))}
          {order.map((rowLeaf, row) =>
            order.map((colLeaf, col) => {
              const value = matrix[rowLeaf][colLeaf];
              return (
                <g key={`${row}-${col}`} onMouseEnter={() => setHover({ row, col })}>
                  <rect
                    x={LABEL + cell * col}
                    y={LABEL + cell * row}
                    width={cell - 2}
                    height={cell - 2}
                    rx={2}
                    fill={value >= 0 ? "var(--primary)" : "var(--chart-4)"}
                    fillOpacity={Math.min(1, Math.abs(value)) * MAX_TINT}
                  />
                  {cell >= 34 && (
                    <text
                      x={LABEL + cell * col + (cell - 2) / 2}
                      y={LABEL + cell * row + (cell - 2) / 2 + 4}
                      textAnchor="middle"
                      className="pointer-events-none fill-foreground font-mono text-2xs"
                    >
                      {num(value, 2)}
                    </text>
                  )}
                </g>
              );
            }),
          )}
        </svg>
        {hover && (
          <ChartTooltip x={LABEL + cell * (hover.col + 1)} y={LABEL + cell * hover.row} containerWidth={width}>
            <span className="font-mono text-foreground">
              {tickers[order[hover.row]]} × {tickers[order[hover.col]]}: {num(matrix[order[hover.row]][order[hover.col]], 2)}
            </span>
          </ChartTooltip>
        )}
      </div>
    </div>
  );
}
