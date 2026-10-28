import type { ReactNode } from "react";

/**
 * A tooltip pinned beside the hovered mark, flipped to the left near the right
 * edge so it never overflows the chart box.
 */
export default function ChartTooltip({
  x,
  y,
  containerWidth,
  children,
}: {
  x: number;
  y: number;
  containerWidth: number;
  children: ReactNode;
}) {
  const flip = x > containerWidth - 200;
  return (
    <div
      className="chart-tooltip"
      style={{ left: flip ? undefined : x + 14, right: flip ? containerWidth - x + 14 : undefined, top: Math.max(0, y - 12) }}
      role="status"
    >
      {children}
    </div>
  );
}

/** A label and value row inside a tooltip. */
export function TipRow({ label, value }: { label: ReactNode; value: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono text-foreground">{value}</span>
    </div>
  );
}
