import { ChevronDown, ChevronRight } from "lucide-react";

import type { MemoSection, ResearchMemo, TraceNode } from "../api/types";
import ActionButton from "../components/ActionButton";
import ScheduleCard from "../components/ScheduleCard";
import { EmptyState } from "../components/States";
import { human, num, stamp } from "../components/format";

const STAGES: { title: string; nodes: string[] }[] = [
  { title: "Grounding", nodes: ["grounding"] },
  { title: "Specialists, in parallel", nodes: ["credit_analyst", "forensic_accountant", "valuation_analyst", "market_analyst"] },
  { title: "Curator", nodes: ["curator"] },
  { title: "Disagreements", nodes: ["disagreements"] },
  { title: "Editor", nodes: ["editor"] },
];

const STATUS_CHIP: Record<string, string> = {
  ok: "chip-safe",
  fallback: "chip-grey",
  skipped: "chip-neutral",
  error: "chip-distress",
};

/**
 * The multi-agent research memo: what the editor wrote, where the models
 * disagree, what each specialist said, and the trace of every node that ran.
 * Every figure in the memo was checked against the computed context.
 */
export default function ResearchMemoScreen({
  memo,
  ready,
  busy,
  locked,
  onRun,
}: {
  memo: ResearchMemo | null;
  ready: boolean;
  busy: boolean;
  locked: boolean;
  onRun: () => Promise<void>;
}) {
  const runButton = (
    <ActionButton busy={busy} disabled={locked || !ready} onClick={() => void onRun()} busyLabel="Agents writing" variant={memo ? "secondary" : "primary"}>
      {memo ? "Re-run memo" : "Write research memo"}
    </ActionButton>
  );
  if (!memo) {
    return (
      <EmptyState title={ready ? "No research memo yet" : "Run the analysis first"} action={runButton}>
        Four specialists (credit, forensic accounting, valuation, market) each read only their own slice of the
        computed results. A curator drops any sentence carrying a figure that is not in that slice, code finds
        where the models disagree, and an editor writes the memo from what survives.
      </EmptyState>
    );
  }

  const fromModel = memo.generated_by === "llm";
  return (
    <div className="space-y-6">
      <ScheduleCard
        reference="Memorandum"
        title={memo.memo.title}
        aside={
          <>
            <span className={fromModel ? "chip-brand" : "chip-neutral"}>{fromModel ? "written by the model" : "template fallback"}</span>
            {runButton}
          </>
        }
        note={`Generated ${stamp(memo.generated_at)}. ${memo.curator_report.figures_checked} figures checked against the computed context, ${memo.curator_report.sentences_removed} sentence${memo.curator_report.sentences_removed === 1 ? "" : "s"} removed.`}
      >
        <div className="space-y-5 px-4 py-5">
          <p className="prose-measure text-base leading-relaxed text-foreground">{memo.memo.executive_summary}</p>
          <div className="callout-info prose-measure">
            <p className="text-xs font-medium text-primary">Recommendation</p>
            <p className="mt-1">{memo.memo.recommendation}</p>
          </div>
        </div>
      </ScheduleCard>

      <Disagreements memo={memo} />

      <ScheduleCard reference="Specialists" title="What each analyst wrote, after curation">
        <div className="divide-y divide-border">
          {memo.sections.map((section) => (
            <SectionBlock key={section.key} section={section} />
          ))}
        </div>
      </ScheduleCard>

      <ScheduleCard reference="Trace" title="Every node that ran, in order" note={memo.curator_report.rule}>
        <PipelineTrace trace={memo.trace} />
      </ScheduleCard>
    </div>
  );
}

function Disagreements({ memo }: { memo: ResearchMemo }) {
  const items = memo.memo.disagreements;
  return (
    <ScheduleCard
      reference="Disagreements"
      title={items.length ? `The models disagree in ${items.length} place${items.length === 1 ? "" : "s"}` : "The models agree everywhere they overlap"}
      note="Found by code that compares the stored results, never by the model. A disagreement is a finding to resolve, not noise to average away."
    >
      {items.length > 0 && (
        <ol className="divide-y divide-border">
          {items.map((item, index) => (
            <li key={item.kind} className="flex gap-4 px-4 py-4">
              <span className="font-mono text-xs text-muted-foreground">{String(index + 1).padStart(2, "0")}</span>
              <div className="min-w-0">
                <p className="text-sm font-medium text-foreground">{item.title}</p>
                <p className="prose-measure mt-1 text-sm leading-relaxed text-muted-foreground">{item.detail}</p>
                <span className="chip-grey mt-2">{human(item.kind)}</span>
              </div>
            </li>
          ))}
        </ol>
      )}
    </ScheduleCard>
  );
}

function SectionBlock({ section }: { section: MemoSection }) {
  return (
    <article className="px-4 py-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium text-foreground">
          {section.title}
          <span className="ml-2 font-normal text-muted-foreground">{section.headline}</span>
        </h3>
        <span className="font-mono text-2xs text-muted-foreground">
          {section.numbers_checked} figure{section.numbers_checked === 1 ? "" : "s"} checked · {section.source}
        </span>
      </div>
      <p className="prose-measure mt-2 text-sm leading-relaxed text-foreground">{section.text}</p>
      {section.removed.length > 0 && (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs text-muted-foreground">
            Curator removed {section.removed.length} sentence{section.removed.length === 1 ? "" : "s"}
          </summary>
          <ul className="mt-2 space-y-2">
            {section.removed.map((removed) => (
              <li key={removed.sentence} className="callout-warning text-xs">
                <p className="line-through decoration-muted-foreground">{removed.sentence}</p>
                <p className="mt-1 font-mono text-muted-foreground">Not in the context: {removed.ungrounded.join(", ")}</p>
              </li>
            ))}
          </ul>
        </details>
      )}
    </article>
  );
}

/** The five stages left to right (top to bottom on a phone), each node with its status and timing. */
function PipelineTrace({ trace }: { trace: TraceNode[] }) {
  const byNode = new Map(trace.map((node) => [node.node, node]));
  return (
    <ol className="grid gap-3 px-4 py-5 xl:grid-cols-[1fr_auto_1.3fr_auto_1fr_auto_1fr_auto_1fr] xl:items-center">
      {STAGES.map((stage, index) => (
        <li key={stage.title} className="contents">
          {index > 0 && (
            <span className="flex justify-center text-muted-foreground" aria-hidden>
              <ChevronRight size={16} strokeWidth={1.5} className="hidden xl:block" />
              <ChevronDown size={16} strokeWidth={1.5} className="xl:hidden" />
            </span>
          )}
          <div className="min-w-0">
            <p className="section-no mb-2">{stage.title}</p>
            <div className="space-y-2">
              {stage.nodes.map((name) => {
                const node = byNode.get(name);
                return node ? <TraceCard key={name} node={node} /> : null;
              })}
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}

function TraceCard({ node }: { node: TraceNode }) {
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2">
      <p className="text-xs font-medium text-foreground">{human(node.node)}</p>
      <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className={STATUS_CHIP[node.status] ?? "chip-neutral"}>{node.status}</span>
        <span className="font-mono text-2xs text-muted-foreground">
          {node.source} · {num(node.duration_ms, node.duration_ms < 10 ? 2 : 0)} ms
        </span>
      </div>
      <p className="mt-1.5 text-2xs leading-snug text-muted-foreground">{node.detail}</p>
    </div>
  );
}
