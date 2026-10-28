import { ArrowLeft } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { api, optional } from "../api/client";
import type { DcfDraft, ListingDraft } from "../api/client";
import type {
  BankruptcyRisk,
  Company,
  DcfValuation,
  EarningsQuality,
  HealthScore,
  InsightReport,
  Listing,
  MarketRisk,
  PeerBenchmark,
  PeerCompany,
  RatioAnalysis,
  ResearchMemo,
  ScenarioRun,
} from "../api/types";
import ActionButton from "../components/ActionButton";
import BinderTabs from "../components/BinderTabs";
import type { BinderTab } from "../components/BinderTabs";
import { ErrorState, InlineError, LoadingBlock } from "../components/States";
import { SECTOR_LABELS, human } from "../components/format";
import InsightsPanel from "../screens/InsightsPanel";
import MarketScreen from "../screens/MarketScreen";
import Overview from "../screens/Overview";
import PeerBenchmarkScreen from "../screens/PeerBenchmark";
import RatioSchedules from "../screens/RatioSchedules";
import ResearchMemoScreen from "../screens/ResearchMemo";
import RiskAndFraud from "../screens/RiskAndFraud";
import Valuation from "../screens/Valuation";

const TAB_KEYS = ["overview", "schedules", "risk", "market", "valuation", "peers", "memo", "insights"] as const;
type TabKey = (typeof TAB_KEYS)[number];
export type ActionKey = "analysis" | "valuation" | "scenario" | "ask" | "market" | "memo";

export interface CompanyData {
  company: Company;
  years: number[];
  lineItems: Record<string, Record<string, number>>;
  ratios: RatioAnalysis | null;
  risk: BankruptcyRisk | null;
  health: HealthScore | null;
  quality: EarningsQuality | null;
  valuation: DcfValuation | null;
  scenario: ScenarioRun | null;
  peers: PeerCompany[];
  benchmark: PeerBenchmark | null;
  report: InsightReport | null;
  listing: Listing | null;
  market: MarketRisk | null;
  memo: ResearchMemo | null;
}

/** What an action returns: the stages it changed, or a function of the current data. */
type Patch = Partial<CompanyData> | ((current: CompanyData) => Partial<CompanyData>);

/**
 * Every stored stage for one company, fetched in parallel. A stage that has not
 * run is a 404 and comes back as null; only a missing company is an error.
 */
async function loadCompany(id: string): Promise<CompanyData> {
  const [company, items, ratios, risk, health, quality, valuation, scenarios, peers, benchmark, report, listing, market, memo] =
    await Promise.all([
      api.getCompany(id),
      optional(api.lineItems(id)),
      optional(api.getRatios(id)),
      optional(api.getRisk(id)),
      optional(api.getHealth(id)),
      optional(api.getEarningsQuality(id)),
      optional(api.getValuation(id)),
      optional(api.listScenarios(id)),
      optional(api.getPeerSet(id)),
      // 409 until ratios exist, which is expected rather than an error here.
      api.getPeerBenchmark(id).catch(() => null),
      optional(api.getInsights(id)),
      optional(api.getListing(id)),
      optional(api.getMarketRisk(id)),
      optional(api.getResearchMemo(id)),
    ]);
  return {
    company,
    years: items?.fiscal_years_on_file ?? [],
    lineItems: items?.line_items_by_year ?? {},
    ratios,
    risk,
    health,
    quality,
    valuation,
    scenario: scenarios?.length ? scenarios[scenarios.length - 1] : null,
    peers: peers ?? [],
    benchmark,
    report,
    listing,
    market,
    memo,
  };
}

/** One company's workpaper: header, numbered section rail, and the active section. */
export default function CompanyDetail() {
  const { companyId = "" } = useParams();
  // The open section lives in the URL (?tab=market), so every section has a shareable link.
  const [params, setParams] = useSearchParams();
  const requested = params.get("tab") as TabKey | null;
  const tab: TabKey = requested && TAB_KEYS.includes(requested) ? requested : "overview";
  const setTab = (key: TabKey) => setParams(key === "overview" ? {} : { tab: key }, { replace: true });
  const [data, setData] = useState<CompanyData | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState<ActionKey | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const reload = useCallback(() => {
    setLoadError(null);
    loadCompany(companyId)
      .then(setData)
      .catch((err: Error) => setLoadError(err.message));
  }, [companyId]);

  useEffect(reload, [reload]);

  // Each action patches only the stage it changed; only the full analysis refetches everything.
  const run = async (key: ActionKey, work: () => Promise<Patch>) => {
    setBusy(key);
    setActionError(null);
    try {
      const patch = await work();
      setData((current) => (current ? { ...current, ...(typeof patch === "function" ? patch(current) : patch) } : current));
    } catch (err) {
      setActionError((err as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const actions = {
    analysis: () => run("analysis", async () => api.runFullAnalysis(companyId).then(() => loadCompany(companyId))),
    valuation: (draft: DcfDraft) => run("valuation", async () => ({ valuation: await api.runValuation(companyId, draft) })),
    scenario: () => run("scenario", async () => ({ scenario: await api.runScenario(companyId, { n_trials: 5000 }) })),
    market: () => run("market", async () => ({ market: await api.runMarketRisk(companyId) })),
    link: (draft: ListingDraft) =>
      run("market", async () => {
        const listing = await api.setListing(companyId, draft);
        return { listing, market: await api.runMarketRisk(companyId) };
      }),
    memo: () => run("memo", async () => ({ memo: await api.runResearchMemo(companyId) })),
    ask: (question: string) =>
      run("ask", async () => {
        const entry = await api.ask(companyId, question);
        return ({ report }: CompanyData) => (report ? { report: { ...report, qa_thread: [...report.qa_thread, entry] } } : {});
      }),
  };

  const tabs = useMemo<BinderTab[]>(
    () => [
      { key: "overview", label: "Overview", ready: Boolean(data?.risk || data?.ratios) },
      { key: "schedules", label: "Ratio schedules", ready: Boolean(data?.ratios) },
      { key: "risk", label: "Risk and fraud", ready: Boolean(data?.risk) },
      { key: "market", label: "Market and Merton", ready: Boolean(data?.market) },
      { key: "valuation", label: "Valuation", ready: Boolean(data?.valuation) },
      { key: "peers", label: "Peer benchmark", ready: Boolean(data?.peers.length) },
      { key: "memo", label: "Research memo", ready: Boolean(data?.memo) },
      { key: "insights", label: "Insights and Q&A", ready: Boolean(data?.report) },
    ],
    [data],
  );

  if (loadError && !data) {
    return <ErrorState title="This company could not be loaded" message={loadError} onRetry={reload} />;
  }
  if (!data) return <LoadingBlock rows={8} label="Loading company" />;

  return (
    <div className="space-y-6">
      <CompanyHeader data={data} busy={busy} onRun={actions.analysis} />
      {actionError && <InlineError message={actionError} onDismiss={() => setActionError(null)} />}
      <div className="grid grid-cols-[minmax(0,1fr)] gap-6 md:grid-cols-[13rem_minmax(0,1fr)]">
        <aside className="min-w-0 md:sticky md:top-6 md:self-start">
          <BinderTabs tabs={tabs} active={tab} onSelect={(key) => setTab(key as TabKey)} />
        </aside>
        <div className="min-w-0">
          {tab === "overview" && <Overview data={data} />}
          {tab === "schedules" && <RatioSchedules ratios={data.ratios} health={data.health} />}
          {tab === "risk" && <RiskAndFraud risk={data.risk} quality={data.quality} />}
          {tab === "market" && (
            <MarketScreen data={data} busy={busy === "market"} locked={busy !== null} onLink={actions.link} onCompute={actions.market} />
          )}
          {tab === "valuation" && (
            <Valuation
              company={data.company}
              valuation={data.valuation}
              scenario={data.scenario}
              busy={busy}
              onRun={actions.valuation}
              onSimulate={actions.scenario}
            />
          )}
          {tab === "peers" && <PeerBenchmarkScreen benchmark={data.benchmark} peers={data.peers} />}
          {tab === "memo" && (
            <ResearchMemoScreen memo={data.memo} ready={Boolean(data.ratios && data.risk)} busy={busy === "memo"} locked={busy !== null} onRun={actions.memo} />
          )}
          {tab === "insights" && <InsightsPanel report={data.report} busy={busy === "ask"} onAsk={actions.ask} />}
        </div>
      </div>
    </div>
  );
}

function CompanyHeader({
  data,
  busy,
  onRun,
}: {
  data: CompanyData;
  busy: ActionKey | null;
  onRun: () => void;
}) {
  const { company, years, listing, ratios } = data;
  const fiscal = years.length ? years.map((y) => `FY${y}`).join(", ") : company.fiscal_year ? `FY${company.fiscal_year}` : null;
  const meta = [company.industry, SECTOR_LABELS[company.sector_class] ?? human(company.sector_class), fiscal, `${company.units.toLowerCase()} ${company.currency}`, listing?.ticker]
    .filter(Boolean)
    .join(" · ");
  return (
    <header className="border-b border-border pb-6">
      <Link to="/" className="link inline-flex items-center gap-1 text-xs text-muted-foreground">
        <ArrowLeft size={14} strokeWidth={1.5} aria-hidden />
        Companies
      </Link>
      <div className="mt-3 flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="display text-4xl text-foreground sm:text-5xl">{company.name}</h1>
          <p className="mt-2 font-mono text-xs text-muted-foreground">{meta}</p>
        </div>
        <ActionButton
          variant={ratios ? "secondary" : "primary"}
          busy={busy === "analysis"}
          disabled={busy !== null}
          onClick={onRun}
          busyLabel="Running analysis"
        >
          {ratios ? "Re-run analysis" : "Run analysis"}
        </ActionButton>
      </div>
      {company.data_source && <SourceDisclosure data={data} />}
    </header>
  );
}

function SourceDisclosure({ data }: { data: CompanyData }) {
  const { company, years, lineItems } = data;
  const keys = [...new Set(Object.values(lineItems).flatMap((items) => Object.keys(items)))].sort();
  return (
    <details className="mt-4 text-sm">
      <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">
        Source and line items ({years.length} fiscal year{years.length === 1 ? "" : "s"} on file)
      </summary>
      <p className="prose-measure mt-2 text-xs leading-relaxed text-muted-foreground">{company.data_source}</p>
      <div className="sheet mt-3 overflow-x-auto">
        <table className="ledger">
          <thead>
            <tr>
              <th>Line item</th>
              {years.map((year) => (
                <th key={year} className="text-right">
                  FY{year}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {keys.map((key) => (
              <tr key={key}>
                <td className="font-mono text-xs">{key}</td>
                {years.map((year) => (
                  <td key={year} className="num-dim">
                    {lineItems[String(year)]?.[key]?.toLocaleString("en-US") ?? "—"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
