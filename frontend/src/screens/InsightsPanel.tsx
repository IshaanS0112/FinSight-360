import { useState } from "react";

import ActionButton from "../components/ActionButton";
import ScheduleCard from "../components/ScheduleCard";
import { EmptyState } from "../components/States";
import type { InsightReport, QaEntry } from "../api/types";

export default function InsightsPanel({
  report,
  onAsk,
  busy,
}: {
  report: InsightReport | null;
  onAsk: (question: string) => Promise<void>;
  busy: boolean;
}) {
  const [question, setQuestion] = useState("");

  if (!report) {
    return (
      <EmptyState title="No written assessment yet">
        Run the analysis: the narrative and the follow-up Q&A read the report it stores.
      </EmptyState>
    );
  }

  const narrative = report.ai_narrative;
  const fromModel = report.generated_by === "llm";

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const text = question.trim();
    if (!text) return;
    await onAsk(text);
    setQuestion("");
  };

  return (
    <div className="space-y-6">
      <ScheduleCard
        reference="Memorandum"
        title="Written assessment"
        aside={
          <>
            <span className={fromModel ? "chip-brand" : "chip-neutral"}>
              {fromModel ? "narrated by the model" : "template fallback"}
            </span>
            {narrative.dropped_citations ? (
              <span className="chip-grey">{narrative.dropped_citations} citation dropped</span>
            ) : null}
          </>
        }
        note={
          narrative.fallback_reason
            ? `Fallback: ${narrative.fallback_reason}. Every figure is identical either way; only the prose is missing.`
            : "Every figure the narrative cites exists in structured_context before the model is called. A cited metric absent from that context is dropped and counted."
        }
      >
        <div className="space-y-4 px-4 py-4">
          <Block title="Executive summary" body={narrative.executive_summary} />
          <Block title="Bankruptcy risk" body={narrative.bankruptcy_risk_assessment} />
          {narrative.key_findings && narrative.key_findings.length > 0 && (
            <div>
              <h3 className="label">Key findings</h3>
              <ul className="divide-y divide-border border border-border">
                {narrative.key_findings.map((finding, index) => (
                  <li key={`${finding.metric}-${index}`} className="px-3 py-2">
                    <span className="chip-brand">{finding.metric}</span>
                    <p className="mt-1.5 text-sm leading-relaxed text-foreground">
                      {finding.observation}
                    </p>
                    <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                      {finding.implication}
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <Block title="Data limitations" body={narrative.data_limitations} />
          <Block title="Recommendation" body={narrative.recommendation} />
        </div>
      </ScheduleCard>

      <ScheduleCard
        reference="Q&A"
        title="Follow-up, answered only from the computed context"
        note="The endpoint reads this report's frozen context and nothing else. A question needing a figure that was never computed comes back as an explicit refusal naming the figure, because an answer grounded in nothing is indistinguishable from an invented one."
      >
        <form onSubmit={submit} className="flex gap-2 border-b border-border px-4 py-3">
          <input
            className="field"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="e.g. what drove the current_ratio, or why was the M-Score withheld?"
            aria-label="Follow-up question"
          />
          {/* Explicit type so Enter in the single input submits the form. */}
          <ActionButton type="submit" busy={busy} disabled={!question.trim()} busyLabel="Asking">
            Ask
          </ActionButton>
        </form>
        {report.qa_thread.length === 0 ? (
          <p className="sheet-note">No questions asked yet.</p>
        ) : (
          <ul className="divide-y divide-border">
            {report.qa_thread.map((entry, index) => (
              <QaRow key={`${entry.asked_at}-${index}`} entry={entry} />
            ))}
          </ul>
        )}
      </ScheduleCard>
    </div>
  );
}

function QaRow({ entry }: { entry: QaEntry }) {
  return (
    <li className="px-4 py-3">
      <p className="text-sm font-medium text-foreground">{entry.question}</p>
      <p
        className={`mt-1.5 text-sm leading-relaxed ${
          entry.refused ? "text-muted-foreground" : "text-foreground"
        }`}
      >
        {entry.answer}
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {entry.refused ? (
          <span className="chip-grey">refused</span>
        ) : (
          entry.grounded_in.map((field) => (
            <span key={field} className="chip-neutral">
              {field}
            </span>
          ))
        )}
        {entry.dropped_citations > 0 && (
          <span className="chip-distress">{entry.dropped_citations} ungrounded citation</span>
        )}
        {entry.answered_by && (
          <span className="font-mono text-2xs text-muted-foreground">
            {entry.answered_by.replace(/_/g, " ")}
          </span>
        )}
      </div>
    </li>
  );
}

function Block({ title, body }: { title: string; body?: string }) {
  if (!body) return null;
  return (
    <div>
      <h3 className="label">{title}</h3>
      <p className="text-sm leading-relaxed text-foreground">{body}</p>
    </div>
  );
}
