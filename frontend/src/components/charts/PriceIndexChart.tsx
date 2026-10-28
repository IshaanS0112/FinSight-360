import { useMemo, useState } from "react";
import type { PointerEvent } from "react";

import type { PricePoint } from "../../api/types";
import { monthYear, num, signed } from "../format";
import ChartTooltip, { TipRow } from "./ChartTooltip";
import Legend, { Swatch } from "./Legend";
import { linear, niceTicks, paddedExtent } from "./scale";
import { useElementWidth } from "./useElementWidth";

export interface PriceSeries {
  key: string;
  label: string;
  points: PricePoint[];
  highlight: boolean;
}

const MARGIN = { top: 20, right: 64, bottom: 32, left: 44 };

/**
 * Total-return index (adjusted close, first common month = 100) for a stock and
 * its benchmark, with a crosshair tooltip and a marker where the fiscal year
 * ends: every statistic on the page stops at that line.
 */
export default function PriceIndexChart({ series, cutoff }: { series: PriceSeries[]; cutoff?: string }) {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const height = 280;
  const indexed = useMemo(() => rebase(series), [series]);

  const geometry = useMemo(() => {
    const values = indexed.lines.flatMap((line) => line.values);
    const yDomain = paddedExtent(values, 0.08);
    const x = linear([0, Math.max(1, indexed.dates.length - 1)], [MARGIN.left, width - MARGIN.right]);
    const y = linear(yDomain, [height - MARGIN.bottom, MARGIN.top]);
    const paths = indexed.lines.map((line) =>
      line.values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(""),
    );
    return { x, y, paths, yTicks: niceTicks(...yDomain, 4) };
  }, [indexed, width]);

  if (indexed.dates.length < 2) {
    return <p className="text-sm text-muted-foreground">Not enough overlapping months to draw an index.</p>;
  }

  const { x, y } = geometry;
  const last = indexed.dates.length - 1;
  const cutoffIndex = cutoff ? indexed.dates.findIndex((d) => d >= cutoff) : -1;
  const years = indexed.dates.flatMap((d, i) => (d.slice(5, 7) === "01" ? [{ i, label: d.slice(0, 4) }] : []));
  const endLabels = spreadEndLabels(indexed.lines.map((line) => y(line.values[last])));

  const onMove = (event: PointerEvent<SVGRectElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    const fraction = (event.clientX - box.left) / box.width;
    setHoverIndex(Math.max(0, Math.min(last, Math.round(fraction * last))));
  };

  return (
    <div>
      {series.length > 1 && (
        <Legend
          items={series.map((s) => ({
            swatch: Swatch.line(s.highlight ? "bg-primary" : "bg-chart-2"),
            label: s.label,
          }))}
        />
      )}
      <div ref={ref} className="relative mt-3">
        <svg width={width} height={height} role="img" aria-label={describe(indexed)}>
          {geometry.yTicks.map((tick) => (
            <g key={tick}>
              <line x1={MARGIN.left} x2={width - MARGIN.right} y1={y(tick)} y2={y(tick)} stroke="var(--border)" />
              <text x={MARGIN.left - 8} y={y(tick) + 4} textAnchor="end" className="fill-muted-foreground font-mono text-2xs">
                {tick}
              </text>
            </g>
          ))}
          {years.map(({ i, label }) => (
            <text key={label} x={x(i)} y={height - 10} textAnchor="middle" className="fill-muted-foreground font-mono text-2xs">
              {label}
            </text>
          ))}
          {cutoffIndex >= 0 && (
            <g>
              <line x1={x(cutoffIndex)} x2={x(cutoffIndex)} y1={MARGIN.top - 8} y2={height - MARGIN.bottom} stroke="var(--foreground)" strokeDasharray="3 3" />
              <text x={x(cutoffIndex) - 6} y={MARGIN.top - 8} textAnchor="end" className="fill-foreground text-2xs">
                Fiscal year end
              </text>
            </g>
          )}
          {indexed.lines.map((line, i) => (
            <path
              key={line.key}
              d={geometry.paths[i]}
              fill="none"
              stroke={line.highlight ? "var(--primary)" : "var(--chart-2)"}
              strokeWidth={line.highlight ? 2 : 1.5}
              strokeLinejoin="round"
            />
          ))}
          {indexed.lines.map((line, i) => (
            <text key={`end-${line.key}`} x={width - MARGIN.right + 6} y={endLabels[i] + 4} className="fill-foreground font-mono text-2xs">
              {line.key} {num(line.values[last], 0)}
            </text>
          ))}
          {hoverIndex !== null && (
            <g>
              <line x1={x(hoverIndex)} x2={x(hoverIndex)} y1={MARGIN.top} y2={height - MARGIN.bottom} stroke="var(--border-strong)" />
              {indexed.lines.map((line) => (
                <circle
                  key={line.key}
                  cx={x(hoverIndex)}
                  cy={y(line.values[hoverIndex])}
                  r={4}
                  fill={line.highlight ? "var(--primary)" : "var(--chart-2)"}
                  stroke="var(--card)"
                  strokeWidth="2"
                />
              ))}
            </g>
          )}
          <rect
            x={MARGIN.left}
            y={MARGIN.top}
            width={Math.max(0, width - MARGIN.left - MARGIN.right)}
            height={height - MARGIN.top - MARGIN.bottom}
            fill="transparent"
            onPointerMove={onMove}
            onPointerLeave={() => setHoverIndex(null)}
          />
        </svg>
        {hoverIndex !== null && (
          <ChartTooltip x={x(hoverIndex)} y={MARGIN.top + 8} containerWidth={width}>
            <p className="mb-1 font-medium text-foreground">{monthYear(indexed.dates[hoverIndex])}</p>
            {indexed.lines.map((line) => (
              <TipRow key={line.key} label={line.key} value={`${num(line.values[hoverIndex], 1)} (${signed(line.values[hoverIndex] - 100, 1)}%)`} />
            ))}
          </ChartTooltip>
        )}
      </div>
    </div>
  );
}

/** Aligns the series on their common month-end dates and rebases each to 100. */
function rebase(series: PriceSeries[]) {
  const common = series
    .map((s) => new Set(s.points.map((p) => p.date)))
    .reduce((acc, dates) => new Set([...acc].filter((d) => dates.has(d))));
  const dates = [...common].sort();
  const lines = series.map((s) => {
    const byDate = new Map(s.points.map((p) => [p.date, p.adj_close]));
    const base = byDate.get(dates[0]) ?? 1;
    return { key: s.key, highlight: s.highlight, values: dates.map((d) => ((byDate.get(d) ?? base) / base) * 100) };
  });
  return { dates, lines };
}

/** Nudges end-of-line labels apart so two series ending close together stay legible. */
function spreadEndLabels(ys: number[]): number[] {
  const order = ys.map((y, i) => ({ y, i })).sort((a, b) => a.y - b.y);
  for (let k = 1; k < order.length; k += 1) {
    order[k].y = Math.max(order[k].y, order[k - 1].y + 14);
  }
  const out = [...ys];
  order.forEach(({ y, i }) => {
    out[i] = y;
  });
  return out;
}

function describe(indexed: ReturnType<typeof rebase>): string {
  const last = indexed.dates.length - 1;
  const parts = indexed.lines.map((line) => `${line.key} ends at ${num(line.values[last], 0)}`);
  return `Total-return index from ${monthYear(indexed.dates[0])} to ${monthYear(indexed.dates[last])}, start = 100. ${parts.join("; ")}.`;
}
