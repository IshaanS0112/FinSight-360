import type { ReactNode } from "react";

import type { CompanyData } from "../pages/CompanyDetail";
import GaugeDial from "../components/GaugeDial";
import ScheduleCard from "../components/ScheduleCard";
import { EmptyState } from "../components/States";
import TrendSparkline from "../components/TrendSparkline";
import VerdictStamp from "../components/VerdictStamp";
import { ALTMAN_LABELS, CATEGORY_LABELS, human, num, probability, ratioLabel, ratioValue, zoneChip } from "../components/format";
import type { RatioAnalysis } from "../api/types";

const CATEGORIES: { key: string; bucket: keyof RatioAnalysis }[] = [
  { key: "profitability", bucket: "profitability_ratios" },
  { key: "liquidity", bucket: "liquidity_ratios" },
  { key: "leverage", bucket: "leverage_ratios" },
  { key: "efficiency", bucket: "efficiency_ratios" },
];

/** The verdict at a glance: both accounting models, the market's view, the stamp, the health dial. */
export default function Overview({ data }: { data: CompanyData }) {
  const { risk, health, quality, ratios, market } = data;
  if (!risk && !ratios) {
    return (
      <EmptyState title="No analysis yet">
        Run the analysis to compute the ratios, both bankruptcy models, the earnings-quality scores and the
        health composite.
      </EmptyState>
    );
  }
  const consensusReason = (risk?.calculation_basis?.consensus as Record<string, string> | undefined)?.consensus_reason;

  return (
    <div className="space-y-6">
      <ScheduleCard
        reference="Verdict"
        title="Consensus bankruptcy risk"
        aside={risk && <span className="chip-neutral">Altman {ALTMAN_LABELS[risk.model] ?? risk.model} · FY{risk.fiscal_year}</span>}
        note={
          risk?.ohlson_o_score === null && risk?.altman_z_score === null
            ? "Neither model produced a score for this issuer."
            : undefined
        }
      >
        <div className="grid gap-8 px-4 py-8 lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] lg:items-center">
          <div className="grid gap-6 sm:grid-cols-3 lg:grid-cols-1">
            <Metric
              label={`Altman ${risk ? (ALTMAN_LABELS[risk.model] ?? risk.model) : ""}`}
              value={risk?.altman_z_score == null ? "—" : num(risk.altman_z_score)}
              foot={risk && <span className={zoneChip(risk.zone)}>{human(risk.zone)}</span>}
            />
            <Metric
              label="Ohlson, probability of distress"
              value={risk?.ohlson_probability == null ? "—" : `${num(risk.ohlson_probability * 100, 1)}%`}
              foot={risk?.ohlson_o_score == null ? undefined : <span className="font-mono">O = {num(risk.ohlson_o_score)}</span>}
            />
            <Metric
              label="Merton, market-implied default"
              value={market ? probability(market.merton_probability_of_default) : "—"}
              foot={
                market ? (
                  <span className="font-mono">
                    DD {num(market.merton_distance_to_default)} · {human(market.market_view)}
                  </span>
                ) : (
                  "Link a ticker on Market and Merton"
                )
              }
            />
          </div>
          <div className="flex justify-center">
            <VerdictStamp verdict={risk?.consensus_verdict ?? null} reason={consensusReason} />
          </div>
          <div className="flex flex-col items-center gap-3">
            <GaugeDial score={health?.overall_score ?? null} percentile={health?.peer_percentile} />
            {quality && (
              <div className="flex flex-wrap justify-center gap-2">
                <span className="chip-neutral">
                  F-Score {quality.piotroski_f_score ?? "—"}
                  {quality.f_score_band ? ` · ${quality.f_score_band}` : " · partial"}
                </span>
                <span
                  className={
                    quality.manipulation_flag === null ? "chip-neutral" : quality.manipulation_flag ? "chip-distress" : "chip-safe"
                  }
                >
                  M-Score {quality.beneish_m_score === null ? "withheld" : num(quality.beneish_m_score)}
                </span>
              </div>
            )}
          </div>
        </div>
      </ScheduleCard>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {CATEGORIES.map(({ key, bucket }) => (
          <CategoryCard key={key} category={key} ratios={(ratios?.[bucket] ?? {}) as Record<string, number>} data={data} />
        ))}
      </div>
    </div>
  );
}

function CategoryCard({
  category,
  ratios,
  data,
}: {
  category: string;
  ratios: Record<string, number>;
  data: CompanyData;
}) {
  const componentScore = data.health?.component_scores?.[category] ?? null;
  const trend = data.ratios?.trend?.ratios ?? {};
  return (
    <section className="sheet p-4">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium text-foreground">{CATEGORY_LABELS[category]}</h3>
        <span className="font-mono text-base text-foreground" title="Component score, 0 to 100">
          {componentScore === null ? "—" : num(componentScore, 1)}
        </span>
      </div>
      <p className="text-2xs text-muted-foreground">component score of 100</p>
      <ul className="mt-3 space-y-2">
        {Object.entries(ratios).map(([key, value]) => (
          <li key={key} className="flex items-center justify-between gap-2">
            <span className="text-xs text-muted-foreground">{ratioLabel(key)}</span>
            <span className="flex items-center gap-2">
              {trend[key] && (
                <TrendSparkline points={Object.values(trend[key].by_year)} direction={trend[key].direction} width={44} height={16} />
              )}
              <span className="font-mono text-xs text-foreground">{ratioValue(key, value)}</span>
            </span>
          </li>
        ))}
        {Object.keys(ratios).length === 0 && <li className="text-xs text-muted-foreground">No ratio in this category was computed.</li>}
      </ul>
    </section>
  );
}

function Metric({ label, value, foot }: { label: string; value: string; foot?: ReactNode }) {
  return (
    <div className="min-w-0 border-l border-border-strong pl-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 font-mono text-3xl leading-tight text-foreground">{value}</p>
      {foot && <div className="mt-1.5 text-xs text-muted-foreground">{foot}</div>}
    </div>
  );
}
