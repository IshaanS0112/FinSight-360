import type { InsightReport } from "../api/types";

/**
 * The narrative, plus the structured context it was allowed to use.
 *
 * The context is one click away on purpose. The claim the project makes is that
 * every figure in the prose existed before the model was called, and the only way
 * to make that checkable rather than asserted is to put both on the same screen.
 */
export default function InsightsPanel({ report }: { report: InsightReport }) {
  const narrative = report.ai_narrative;
  const isFallback = report.generated_by === "template_fallback";

  return (
    <section className="panel p-5">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-muted">
          Health assessment
        </h2>
        <span
          className={`chip ${
            isFallback ? "border-edge bg-ink text-muted" : "border-accent/40 bg-accent/10 text-accent"
          }`}
        >
          {isFallback ? "template fallback" : "LLM narration"}
        </span>
      </div>

      {isFallback && narrative.fallback_reason && (
        <p className="mb-4 rounded border border-edge bg-ink p-2 text-xs text-muted">
          No LLM narration: {narrative.fallback_reason}. Every figure below is identical
          either way — only the prose differs.
        </p>
      )}

      {typeof narrative.dropped_citations === "number" && narrative.dropped_citations > 0 && (
        <p className="mb-4 rounded border border-grey/40 bg-grey/10 p-2 text-xs text-grey">
          {narrative.dropped_citations} cited metric
          {narrative.dropped_citations === 1 ? "" : "s"} did not appear in the structured
          context and {narrative.dropped_citations === 1 ? "was" : "were"} dropped.
        </p>
      )}

      <div className="space-y-4 text-sm leading-relaxed text-slate-300">
        {narrative.executive_summary && <p>{narrative.executive_summary}</p>}

        {narrative.bankruptcy_risk_assessment && (
          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wider text-accent">
              Bankruptcy risk
            </h3>
            <p>{narrative.bankruptcy_risk_assessment}</p>
          </div>
        )}

        {narrative.key_findings && narrative.key_findings.length > 0 && (
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-accent">
              Key findings
            </h3>
            <ul className="space-y-2">
              {narrative.key_findings.map((finding, index) => (
                <li key={`${finding.metric}-${index}`} className="text-xs">
                  <span className="font-mono text-slate-200">{finding.metric}</span>
                  <span className="text-muted"> — {finding.observation}</span>
                  {finding.implication && (
                    <div className="mt-0.5 text-muted">{finding.implication}</div>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        {narrative.data_limitations && (
          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wider text-grey">
              Data limitations
            </h3>
            <p className="text-xs text-muted">{narrative.data_limitations}</p>
          </div>
        )}

        {narrative.recommendation && (
          <div className="rounded border border-accent/30 bg-accent/5 p-3">
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wider text-accent">
              Next step
            </h3>
            <p className="text-xs">{narrative.recommendation}</p>
          </div>
        )}
      </div>

      <details className="mt-5 text-xs">
        <summary className="cursor-pointer text-muted hover:text-accent">
          Structured context the model was given (every figure above comes from here)
        </summary>
        <pre className="mt-2 max-h-96 overflow-auto rounded border border-edge bg-ink p-3 font-mono text-[10px] leading-relaxed text-muted">
          {JSON.stringify(report.structured_context, null, 2)}
        </pre>
      </details>
    </section>
  );
}
