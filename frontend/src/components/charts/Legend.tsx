import type { ReactNode } from "react";

export interface LegendItem {
  label: ReactNode;
  swatch: ReactNode;
}

/** One row of swatches above a chart. Present whenever a chart has two or more series. */
export default function Legend({ items }: { items: LegendItem[] }) {
  return (
    <ul className="legend">
      {items.map((item, index) => (
        <li key={index} className="inline-flex items-center gap-1.5">
          {item.swatch}
          <span>{item.label}</span>
        </li>
      ))}
    </ul>
  );
}

/** Swatch shapes, so identity never rests on colour alone. */
export const Swatch = {
  dot: (className: string) => <span className={`inline-block size-2.5 rounded-full ${className}`} />,
  ring: (className: string) => <span className={`inline-block size-2.5 rounded-full border-2 ${className}`} />,
  line: (className: string) => <span className={`inline-block h-0.5 w-4 ${className}`} />,
  dash: (className: string) => <span className={`inline-block w-4 border-t-2 border-dashed ${className}`} />,
  square: (className: string) => <span className={`inline-block size-2.5 rounded-sm ${className}`} />,
  diamond: (className: string) => <span className={`inline-block size-2 rotate-45 ${className}`} />,
};
