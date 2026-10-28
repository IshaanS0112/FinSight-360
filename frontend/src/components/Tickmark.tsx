import { Check, Minus, X } from "lucide-react";

import type { TestStatus } from "../api/types";

/** An auditor's tickmark: pass, fail, and not-evaluated.
 *
 *  The third state is visually distinct from a fail. A data gap is not a finding.
 */
export default function Tickmark({ status }: { status: TestStatus }) {
  if (status === "PASS") {
    return (
      <span className="tickmark border-success/50 bg-success/10 text-success" title="Pass">
        <Check size={14} strokeWidth={2} aria-label="Pass" />
      </span>
    );
  }
  if (status === "FAIL") {
    return (
      <span className="tickmark border-destructive/50 bg-destructive/10 text-destructive" title="Fail">
        <X size={14} strokeWidth={2} aria-label="Fail" />
      </span>
    );
  }
  return (
    <span
      className="tickmark border-dashed border-border-strong text-muted-foreground"
      title="Not evaluated: the inputs for this test were not reported"
    >
      <Minus size={14} strokeWidth={1.5} aria-label="Not evaluated" />
    </span>
  );
}
