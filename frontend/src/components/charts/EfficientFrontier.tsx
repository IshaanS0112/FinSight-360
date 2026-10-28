import { useMemo, useState } from "react";

import type { PortfolioKey, PortfolioResults } from "../../api/types";
import { PORTFOLIO_LABELS, PORTFOLIO_ORDER, num, pct } from "../format";
import ChartTooltip, { TipRow } from "./ChartTooltip";
import Legend, { Swatch } from "./Legend";
import { linear, niceTicks, paddedExtent, placeLabels } from "./scale";
import { useElementWidth } from "./useElementWidth";

interface Mark {
  id: string;
  kind: "portfolio" | "asset";
  label: string;
  volatility: number;
  expectedReturn: number;
  sharpe?: number;
  key?: PortfolioKey;
}

const MARGIN = { top: 16, right: 20, bottom: 44, left: 52 };

/**
 * Risk-return plane for one Portfolio Lab run, in highlight mode: the selected
 * optimiser is the only cobalt mark; the frontier, the random long-only cloud,
 * the other optimisers and the single assets are greys for context.
 * Clicking an optimiser's mark selects it.
 */
export default function EfficientFrontier({
  results,
  selected,
  onSelect,
}: {
  results: PortfolioResults;
  selected: PortfolioKey;
  onSelect: (key: PortfolioKey) => void;
}) {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const [hover, setHover] = useState<Mark | null>(null);
  const height = width < 520 ? 300 : 380;
  const marks = useMemo(() => collectMarks(results), [results]);

  const geometry = useMemo(() => {
    const points = [...results.random_portfolios, ...results.frontier];
    const xs = [...points.map((p) => p.volatility), ...marks.map((m) => m.volatility)];
    const ys = [...points.map((p) => p.expected_return), ...marks.map((m) => m.expectedReturn)];
    const xDomain = paddedExtent(xs);
    const yDomain = paddedExtent(ys);
    const x = linear(xDomain, [MARGIN.left, width - MARGIN.right]);
    const y = linear(yDomain, [height - MARGIN.bottom, MARGIN.top]);
    const cloud = results.random_portfolios
      .map((p) => `M${x(p.volatility).toFixed(1)} ${y(p.expected_return).toFixed(1)}h0`)
      .join("");
    const frontier = results.frontier
      .map((p, i) => `${i ? "L" : "M"}${x(p.volatility).toFixed(1)} ${y(p.expected_return).toFixed(1)}`)
      .join("");
    return { x, y, cloud, frontier, xTicks: niceTicks(...xDomain, 6), yTicks: niceTicks(...yDomain, 5) };
  }, [results, marks, width, height]);

  const { x, y } = geometry;
  const labels = useMemo(() => {
    const ordered = [...marks].sort((a, b) => rank(a, selected) - rank(b, selected));
    const requests = ordered.map((m) => ({ id: m.id, x: x(m.volatility), y: y(m.expectedReturn), text: m.label }));
    return placeLabels(requests, {
      left: MARGIN.left + 4,
      top: MARGIN.top,
      right: width - MARGIN.right,
      bottom: height - MARGIN.bottom,
    });
  }, [marks, selected, x, y, width, height]);
  const chosen = marks.find((m) => m.key === selected);

  return (
    <div>
      <Legend
        items={[
          { swatch: Swatch.dot("bg-primary"), label: `Selected: ${PORTFOLIO_LABELS[selected]}` },
          { swatch: Swatch.diamond("bg-muted-foreground"), label: "Other optimisers" },
          { swatch: Swatch.line("bg-chart-2"), label: "Efficient frontier" },
          { swatch: Swatch.dot("bg-chart-3"), label: `${results.random_portfolios.length.toLocaleString("en-US")} random long-only portfolios` },
          { swatch: Swatch.ring("border-muted-foreground"), label: "Single assets" },
        ]}
      />
      <div ref={ref} className="relative mt-3" onMouseLeave={() => setHover(null)}>
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={
            chosen
              ? `Efficient frontier. ${chosen.label}: expected return ${pct(chosen.expectedReturn)}, volatility ${pct(chosen.volatility)}.`
              : "Efficient frontier"
          }
        >
          <Axes geometry={geometry} width={width} height={height} />
          <path d={geometry.cloud} stroke="var(--chart-3)" strokeWidth="3.5" strokeLinecap="round" fill="none" />
          <path d={geometry.frontier} stroke="var(--chart-2)" strokeWidth="2" fill="none" strokeLinejoin="round" />
          {marks.map((mark) => (
            <MarkGlyph key={mark.id} mark={mark} cx={x(mark.volatility)} cy={y(mark.expectedReturn)} selected={mark.key === selected} />
          ))}
          {labels.map((label) => (
            <text
              key={label.id}
              x={label.lx}
              y={label.ly}
              textAnchor={label.anchor}
              stroke="var(--card)"
              strokeWidth={3}
              paintOrder="stroke"
              className={`text-2xs ${label.id === `p-${selected}` ? "fill-foreground font-semibold" : "fill-muted-foreground"}`}
            >
              {label.text}
            </text>
          ))}
          {marks.map((mark) => (
            <circle
              key={`hit-${mark.id}`}
              cx={x(mark.volatility)}
              cy={y(mark.expectedReturn)}
              r={11}
              fill="transparent"
              className={mark.key ? "cursor-pointer" : undefined}
              onMouseEnter={() => setHover(mark)}
              onClick={() => mark.key && onSelect(mark.key)}
            />
          ))}
        </svg>
        {hover && (
          <ChartTooltip x={x(hover.volatility)} y={y(hover.expectedReturn)} containerWidth={width}>
            <p className="mb-1 font-medium text-foreground">{hover.label}</p>
            <TipRow label="Expected return" value={pct(hover.expectedReturn)} />
            <TipRow label="Volatility" value={pct(hover.volatility)} />
            {hover.sharpe !== undefined && <TipRow label="Sharpe" value={num(hover.sharpe)} />}
            {hover.key && hover.key !== selected && <p className="mt-1 text-muted-foreground">Click to select</p>}
          </ChartTooltip>
        )}
      </div>
    </div>
  );
}

/** Optimiser results and single assets as plottable marks; refused optimisers are skipped. */
function collectMarks(results: PortfolioResults): Mark[] {
  const portfolios = PORTFOLIO_ORDER.flatMap((key) => {
    const p = results.portfolios[key];
    if (!p || p.volatility === undefined || p.expected_return === undefined) return [];
    const mark: Mark = {
      id: `p-${key}`,
      kind: "portfolio",
      key,
      label: PORTFOLIO_LABELS[key],
      volatility: p.volatility,
      expectedReturn: p.expected_return,
      sharpe: p.sharpe_ratio,
    };
    return [mark];
  });
  const assets: Mark[] = results.assets.map((a) => ({
    id: `a-${a.ticker}`,
    kind: "asset",
    label: a.ticker,
    volatility: a.volatility,
    expectedReturn: a.expected_return,
  }));
  return [...portfolios, ...assets];
}

/** Label priority: the selected optimiser, then the other optimisers, then assets. */
function rank(mark: Mark, selected: PortfolioKey): number {
  if (mark.key === selected) return 0;
  return mark.kind === "portfolio" ? 1 : 2;
}

function MarkGlyph({ mark, cx, cy, selected }: { mark: Mark; cx: number; cy: number; selected: boolean }) {
  if (mark.kind === "asset") {
    return <circle cx={cx} cy={cy} r={4} fill="var(--card)" stroke="var(--muted-foreground)" strokeWidth="1.5" />;
  }
  if (selected) {
    return <circle cx={cx} cy={cy} r={6.5} fill="var(--primary)" stroke="var(--card)" strokeWidth="2" />;
  }
  return (
    <rect
      x={cx - 4.5}
      y={cy - 4.5}
      width={9}
      height={9}
      transform={`rotate(45 ${cx} ${cy})`}
      fill="var(--muted-foreground)"
      stroke="var(--card)"
      strokeWidth="2"
    />
  );
}

function Axes({
  geometry,
  width,
  height,
}: {
  geometry: { x: (v: number) => number; y: (v: number) => number; xTicks: number[]; yTicks: number[] };
  width: number;
  height: number;
}) {
  const { x, y, xTicks, yTicks } = geometry;
  const bottom = height - MARGIN.bottom;
  return (
    <g>
      {yTicks.map((tick) => (
        <g key={`y-${tick}`}>
          <line x1={MARGIN.left} x2={width - MARGIN.right} y1={y(tick)} y2={y(tick)} stroke="var(--border)" />
          <text x={MARGIN.left - 8} y={y(tick) + 4} textAnchor="end" className="fill-muted-foreground font-mono text-2xs">
            {pct(tick, 0)}
          </text>
        </g>
      ))}
      <line x1={MARGIN.left} x2={width - MARGIN.right} y1={bottom} y2={bottom} stroke="var(--border-strong)" />
      {xTicks.map((tick) => (
        <text key={`x-${tick}`} x={x(tick)} y={bottom + 16} textAnchor="middle" className="fill-muted-foreground font-mono text-2xs">
          {pct(tick, 0)}
        </text>
      ))}
      <text x={(MARGIN.left + width - MARGIN.right) / 2} y={height - 6} textAnchor="middle" className="fill-muted-foreground text-2xs">
        Annualised volatility
      </text>
      <text
        transform={`translate(12 ${(MARGIN.top + bottom) / 2}) rotate(-90)`}
        textAnchor="middle"
        className="fill-muted-foreground text-2xs"
      >
        Expected annual return
      </text>
    </g>
  );
}
