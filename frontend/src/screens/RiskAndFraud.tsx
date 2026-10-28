import { useState } from "react";

import ScheduleCard from "../components/ScheduleCard";
import { EmptyState } from "../components/States";
import Tickmark from "../components/Tickmark";
import VerdictStamp from "../components/VerdictStamp";
import { num } from "../components/format";
import type { AltmanModelName, BankruptcyRisk, EarningsQuality } from "../api/types";

const VARIANT_LABELS: Record<AltmanModelName, string> = {
  Z_1968: "Z (1968), public manufacturers",
  Z_PRIME: "Z′, private manufacturers",
  Z_DOUBLE_PRIME: "Z″, non-manufacturers and emerging markets",
};

export default function RiskAndFraud({
  risk,
  quality,
}: {
  risk: BankruptcyRisk | null;
  quality: EarningsQuality | null;
}) {
  const [showVariants, setShowVariants] = useState(false);

  if (!risk) {
    return (
      <EmptyState title="No risk suite yet">
        Run the analysis to compute Altman, Ohlson, Piotroski and Beneish on this filing.
      </EmptyState>
    );
  }

  const basis = risk.calculation_basis;
  const ohlsonBasis = (basis.ohlson ?? {}) as Record<string, any>;
  const consensus = (basis.consensus ?? {}) as Record<string, string>;
  const definitions = (ohlsonBasis.term_definitions ?? {}) as Record<string, string>;
  const meanings = (ohlsonBasis.term_meanings ?? {}) as Record<string, string>;

  return (
    <div className="space-y-6">
      <ScheduleCard
        reference="Schedule 8"
        title="Bankruptcy risk from two independent models"
        aside={<span className="chip-neutral">FY{risk.fiscal_year}</span>}
        note={consensus.why_two_models}
      >
        <div className="grid gap-4 px-4 py-4 lg:grid-cols-2">
          {/* --- Altman ------------------------------------------------- */}
          <div className="rounded-lg border border-border p-4">
            <div className="flex items-baseline justify-between">
              <h3 className="text-sm font-medium text-foreground">Altman</h3>
              <span className={`chip-${zoneChip(risk.zone)}`}>{risk.zone.replace(/_/g, " ")}</span>
            </div>
            <p className="mt-0.5 text-2xs text-muted-foreground">{VARIANT_LABELS[risk.model]}</p>
            <p className="mt-2 font-mono text-3xl text-foreground">
              {risk.altman_z_score === null ? "—" : num(risk.altman_z_score)}
            </p>
            {basis.cutoffs && (
              <p className="font-mono text-2xs text-muted-foreground">
                safe &gt; {basis.cutoffs.safe_above} · distress &lt; {basis.cutoffs.distress_below}
              </p>
            )}
            <table className="ledger mt-3">
              <thead>
                <tr>
                  <th>X</th>
                  <th className="text-right">Ratio</th>
                  <th className="text-right">Coef.</th>
                  <th className="text-right">Contribution</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(risk.component_scores).map(([key, component]) => (
                  <tr key={key} title={basis.component_meanings?.[key]}>
                    <td className="font-mono text-2xs text-foreground">{key.toUpperCase()}</td>
                    <td className="num">{num(component.ratio, 4)}</td>
                    <td className="num-dim">{component.coefficient}</td>
                    <td className="num">{num(component.contribution, 4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {risk.omitted_components.length > 0 && (
              <p className="callout-warning mt-3 text-xs">
                Omitted: {risk.omitted_components.map((c) => c.component).join(", ")}: the score is a
                partial sum and is biased toward the cutoffs.
              </p>
            )}
          </div>

          {/* --- Ohlson ------------------------------------------------- */}
          <div className="rounded-lg border border-border p-4">
            <div className="flex items-baseline justify-between">
              <h3 className="text-sm font-medium text-foreground">Ohlson O-Score</h3>
              <span className="chip-neutral">logit, 1980</span>
            </div>
            <p className="mt-0.5 text-2xs text-muted-foreground">
              2,163 firms, and it returns a probability rather than an index
            </p>
            <p className="mt-2 font-mono text-3xl text-foreground">
              {risk.ohlson_probability === null ? "—" : `${num(risk.ohlson_probability * 100, 1)}%`}
            </p>
            <p className="font-mono text-2xs text-muted-foreground">
              O = {risk.ohlson_o_score === null ? "—" : num(risk.ohlson_o_score)} · distress above{" "}
              {ohlsonBasis.distress_cutoff_probability ?? 0.5}
            </p>
            <table className="ledger mt-3">
              <thead>
                <tr>
                  <th>Term</th>
                  <th className="text-right">Value</th>
                  <th className="text-right">Coef.</th>
                  <th className="text-right">Contribution</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(risk.ohlson_components).map(([key, term]) => (
                  <tr key={key} title={`${definitions[key] ?? ""}: ${meanings[key] ?? ""}`}>
                    <td className="font-mono text-2xs text-foreground">{key.toUpperCase()}</td>
                    <td className="num">{num(term.value, 4)}</td>
                    <td className="num-dim">{term.coefficient}</td>
                    <td className="num">{num(term.contribution, 4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {risk.ohlson_omitted.length > 0 && (
              <p className="callout-warning mt-3 text-xs">
                Omitted: {risk.ohlson_omitted.map((t) => t.term).join(", ")}. A partial logit cannot be
                read directionally: the transform is non-linear.
              </p>
            )}
          </div>
        </div>

        <div className="flex flex-col items-center gap-4 border-t border-border px-4 py-6">
          <VerdictStamp verdict={risk.consensus_verdict} reason={consensus.consensus_reason} />
          <p className="max-w-2xl text-center text-2xs leading-relaxed text-muted-foreground">
            {consensus.consensus_rule}
          </p>
        </div>
      </ScheduleCard>

      <ScheduleCard
        reference="Schedule 9"
        title="What the other Altman variants would have said"
        aside={
          <button className="btn-secondary" onClick={() => setShowVariants((open) => !open)}>
            {showVariants ? "Hide" : "Show"}
          </button>
        }
        note="Selection is by sector class, not by which inputs happen to be present. This table exists to make the consequence of the wrong choice visible rather than argued."
      >
        {showVariants && (
          <div className="overflow-x-auto">
            <table className="ledger">
              <thead>
                <tr>
                  <th>Variant</th>
                  <th>X4 equity basis</th>
                  <th className="text-right">Score</th>
                  <th className="text-right">Zone</th>
                  <th className="text-right">Applies here</th>
                </tr>
              </thead>
              <tbody>
                {(Object.entries(risk.variant_scores) as [AltmanModelName, any][]).map(
                  ([variant, entry]) => (
                    <tr key={variant}>
                      <td className="text-foreground">{VARIANT_LABELS[variant]}</td>
                      <td className="font-mono text-2xs text-muted-foreground">
                        {entry.x4_equity_basis?.replace(/_/g, " ").toLowerCase() ?? "—"}
                      </td>
                      <td className="num">{entry.score === null ? "—" : num(entry.score)}</td>
                      <td className="px-3 py-2 text-right">
                        <span className={`chip-${zoneChip(entry.zone)}`}>
                          {entry.zone.replace(/_/g, " ")}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right">
                        {entry.applicable ? (
                          <span className="chip-brand">selected</span>
                        ) : (
                          <span className="font-mono text-2xs text-muted-foreground">—</span>
                        )}
                      </td>
                    </tr>
                  ),
                )}
              </tbody>
            </table>
          </div>
        )}
      </ScheduleCard>

      <PiotroskiSchedule quality={quality} />
      <BeneishSchedule quality={quality} />

      {ohlsonBasis.size_substitution && (
        <ScheduleCard reference="Note" title="Deviation from the published Ohlson model">
          <p className="sheet-note">{ohlsonBasis.size_substitution}</p>
        </ScheduleCard>
      )}
    </div>
  );
}

function zoneChip(zone: string): string {
  if (zone === "SAFE") return "safe";
  if (zone === "DISTRESS") return "distress";
  if (zone === "GREY") return "grey";
  return "neutral";
}

function PiotroskiSchedule({ quality }: { quality: EarningsQuality | null }) {
  if (!quality) return null;
  const tests = Object.entries(quality.f_score_components);
  const evaluated = tests.filter(([, t]) => t.status !== "NOT_EVALUATED").length;
  const bandNote = (quality.calculation_basis?.piotroski as Record<string, string> | undefined)
    ?.band_withheld_reason;

  return (
    <ScheduleCard
      reference="Schedule 10"
      title="Piotroski F-Score: nine tests, one point each"
      aside={
        <>
          <span className="chip-neutral">{evaluated} of 9 evaluated</span>
          <span className="chip-brand">
            {quality.piotroski_f_score ?? "—"}
            {quality.f_score_band ? ` · ${quality.f_score_band}` : ""}
          </span>
        </>
      }
      note={
        bandNote ??
        "Piotroski asks whether the fundamentals are getting stronger, a question neither bankruptcy model asks."
      }
    >
      <ul className="divide-y divide-border">
        {tests.map(([key, test]) => (
          <li key={key} className="flex items-start gap-3 px-4 py-2.5">
            <Tickmark status={test.status} />
            <div className="min-w-0 flex-1">
              <p className="text-sm text-foreground">{test.question}</p>
              <p className="font-mono text-2xs text-muted-foreground">{test.definition}</p>
              {test.status === "NOT_EVALUATED" && test.reason && (
                <p className="mt-0.5 text-xs italic text-muted-foreground">{test.reason}</p>
              )}
              {test.meaning && test.status !== "NOT_EVALUATED" && (
                <p className="mt-0.5 text-2xs leading-relaxed text-muted-foreground">{test.meaning}</p>
              )}
            </div>
            <span className="shrink-0 font-mono text-2xs uppercase tracking-label text-muted-foreground">
              {test.group.replace(/_/g, " ")}
            </span>
          </li>
        ))}
      </ul>
    </ScheduleCard>
  );
}

function BeneishSchedule({ quality }: { quality: EarningsQuality | null }) {
  if (!quality) return null;
  const beneish = (quality.calculation_basis?.beneish ?? {}) as Record<string, any>;
  const thresholds = (beneish.thresholds ?? {}) as Record<string, number>;
  const definitions = (beneish.component_definitions ?? {}) as Record<string, string>;
  const meanings = (beneish.component_meanings ?? {}) as Record<string, string>;
  const strictFlag = quality.calculation_basis?.beneish_strict_manipulation_flag as boolean | null;
  const components = Object.entries(quality.m_score_components);

  return (
    <ScheduleCard
      reference="Schedule 11"
      title="Beneish M-Score: is the filing itself trustworthy"
      aside={
        quality.beneish_m_score === null ? (
          <span className="chip-neutral">withheld</span>
        ) : (
          <span className={quality.manipulation_flag ? "chip-distress" : "chip-safe"}>
            M = {num(quality.beneish_m_score)}
          </span>
        )
      }
      note={beneish.refusal ?? beneish.interpretation_limit}
    >
      {quality.beneish_m_score !== null && (
        <div className="flex flex-wrap gap-4 border-b border-border px-4 py-3">
          <Threshold
            label="Beneish (1999)"
            cutoff={thresholds.beneish_1999}
            flagged={quality.manipulation_flag}
          />
          <Threshold
            label="Stricter, commonly cited"
            cutoff={thresholds.stricter_commonly_cited}
            flagged={strictFlag ?? null}
          />
        </div>
      )}
      {components.length > 0 && (
        <div className="overflow-x-auto">
          <table className="ledger">
            <thead>
              <tr>
                <th>Index</th>
                <th>Definition</th>
                <th className="text-right">Ratio</th>
                <th className="text-right">Coef.</th>
                <th className="text-right">Contribution</th>
              </tr>
            </thead>
            <tbody>
              {components.map(([key, component]) => (
                <tr key={key} title={meanings[key]}>
                  <td className="font-mono text-2xs text-foreground">{key.toUpperCase()}</td>
                  <td className="font-mono text-2xs leading-snug text-muted-foreground">
                    {definitions[key] ?? "—"}
                  </td>
                  <td className="num">{num(component.ratio, 4)}</td>
                  <td className="num-dim">{component.coefficient ?? "—"}</td>
                  <td className="num">
                    {component.contribution === undefined ? "—" : num(component.contribution, 4)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </ScheduleCard>
  );
}

function Threshold({
  label,
  cutoff,
  flagged,
}: {
  label: string;
  cutoff?: number;
  flagged: boolean | null;
}) {
  return (
    <div className="min-w-44 border border-border px-3 py-2">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="font-mono text-sm text-foreground">threshold {cutoff ?? "—"}</p>
      <p
        className={`mt-1 text-2xs ${
          flagged === null ? "text-muted-foreground" : flagged ? "text-destructive" : "text-success"
        }`}
      >
        {flagged === null ? "not evaluated" : flagged ? "flagged for review" : "below threshold"}
      </p>
    </div>
  );
}
