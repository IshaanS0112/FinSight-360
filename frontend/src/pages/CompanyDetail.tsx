import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import HealthScoreView from "../components/HealthScoreView";
import InsightsPanel from "../components/InsightsPanel";
import RatioDashboard from "../components/RatioDashboard";
import ZScoreGauge from "../components/ZScoreGauge";
import { api, optional } from "../api/client";
import type {
  BankruptcyRisk,
  Company,
  HealthScore,
  InsightReport,
  RatioAnalysis,
} from "../api/types";

export default function CompanyDetail() {
  const { companyId = "" } = useParams();
  const [company, setCompany] = useState<Company | null>(null);
  const [ratios, setRatios] = useState<RatioAnalysis | null>(null);
  const [risk, setRisk] = useState<BankruptcyRisk | null>(null);
  const [health, setHealth] = useState<HealthScore | null>(null);
  const [report, setReport] = useState<InsightReport | null>(null);
  const [lineItems, setLineItems] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const [companyData, items, ratioData, riskData, healthData, reportData] = await Promise.all([
        api.getCompany(companyId),
        optional(api.lineItems(companyId)),
        optional(api.getRatios(companyId)),
        optional(api.getRisk(companyId)),
        optional(api.getHealth(companyId)),
        optional(api.getInsights(companyId)),
      ]);
      setCompany(companyData);
      setLineItems(items?.line_items ?? {});
      setRatios(ratioData);
      setRisk(riskData);
      setHealth(healthData);
      setReport(reportData);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [companyId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const runAnalysis = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.runFullAnalysis(companyId);
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (error && !company) {
    return <p className="panel p-6 text-sm text-distress">{error}</p>;
  }
  if (!company) return <p className="panel p-6 text-sm text-muted">Loading…</p>;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link to="/" className="text-xs text-muted hover:text-accent">
            ← Companies
          </Link>
          <h1 className="mt-1 text-lg font-semibold text-slate-100">{company.name}</h1>
          <p className="mt-0.5 text-xs text-muted">
            {company.industry ?? "industry unspecified"} · {company.sector_class} · FY
            {company.fiscal_year} · figures in {company.units.toLowerCase()} {company.currency}
          </p>
        </div>
        <button onClick={runAnalysis} disabled={busy} className="btn-primary">
          {busy ? "Running…" : ratios ? "Re-run analysis" : "Run analysis"}
        </button>
      </div>

      {error && <p className="panel p-3 text-xs text-distress">{error}</p>}

      {company.data_source && (
        <details className="panel p-4 text-xs">
          <summary className="cursor-pointer text-muted hover:text-accent">
            Source and line items ({Object.keys(lineItems).length} reported)
          </summary>
          <p className="mt-2 leading-relaxed text-muted">{company.data_source}</p>
          <table className="mt-3 w-full text-left">
            <tbody>
              {Object.entries(lineItems).map(([key, value]) => (
                <tr key={key} className="border-b border-edge/50 last:border-0">
                  <td className="py-1 font-mono text-[11px] text-slate-400">{key}</td>
                  <td className="stat py-1 text-right text-slate-300">
                    {value.toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}

      {!ratios && (
        <p className="panel p-6 text-sm text-muted">
          No analysis yet. Run it to compute ratios, the applicable Altman score, and the
          weighted health composite.
        </p>
      )}

      {risk && <ZScoreGauge risk={risk} />}
      {ratios && <RatioDashboard ratios={ratios} health={health} />}
      {health && <HealthScoreView health={health} />}
      {report && <InsightsPanel report={report} />}
    </div>
  );
}
