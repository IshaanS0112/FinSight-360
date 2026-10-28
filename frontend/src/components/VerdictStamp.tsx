import type { ConsensusVerdict } from "../api/types";

/** The consensus verdict, as a rotated rubber stamp.
 *
 *  MIXED SIGNAL carries the same visual weight as the other two on purpose: a
 *  disagreement between two models is a finding, not an inconclusive result.
 */

const FACE: Record<ConsensusVerdict, { label: string; sub: string; tone: string }> = {
  LOW_RISK: { label: "Low risk", sub: "Altman and Ohlson concur", tone: "text-success" },
  HIGH_RISK: { label: "High risk", sub: "Altman and Ohlson concur", tone: "text-destructive" },
  MIXED_SIGNAL: { label: "Mixed signal", sub: "The models disagree", tone: "text-warning" },
  INDETERMINATE: { label: "No verdict", sub: "One model declined", tone: "text-muted-foreground" },
};

export default function VerdictStamp({
  verdict,
  reason,
}: {
  verdict: ConsensusVerdict | null;
  reason?: string;
}) {
  const face = FACE[verdict ?? "INDETERMINATE"];
  return (
    <figure className="flex flex-col items-center gap-4">
      <div className={`stamp ${face.tone}`} role="img" aria-label={`Consensus verdict: ${face.label}`}>
        <span className="stamp-label">{face.label}</span>
      </div>
      <figcaption className="max-w-xs text-center">
        <span className="block font-mono text-2xs uppercase tracking-label text-muted-foreground">
          {face.sub}
        </span>
        {reason && <span className="mt-1 block text-xs leading-relaxed text-muted-foreground">{reason}</span>}
      </figcaption>
    </figure>
  );
}
