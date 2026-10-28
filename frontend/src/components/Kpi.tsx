import type { ReactNode } from "react";

/** A headline figure: sans label, mono value, one line of context underneath. */
export default function Kpi({
  label,
  value,
  foot,
  tone = "text-foreground",
}: {
  label: ReactNode;
  value: ReactNode;
  foot?: ReactNode;
  tone?: string;
}) {
  return (
    <div className="min-w-0 border-l border-border-strong pl-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`mt-1 font-mono text-3xl leading-tight ${tone}`}>{value}</p>
      {foot && <p className="mt-1 text-xs text-muted-foreground">{foot}</p>}
    </div>
  );
}
