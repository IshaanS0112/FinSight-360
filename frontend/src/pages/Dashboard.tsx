import { ArrowRight } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api } from "../api/client";
import type { CompanySummary } from "../api/types";
import PageHeader from "../components/PageHeader";
import { EmptyState, ErrorState, LoadingBlock } from "../components/States";
import { SECTOR_LABELS, VERDICT_LABELS, human, marketViewChip, num, probability, verdictChip, zoneChip } from "../components/format";

const PIPELINE = [
  ["Ratios", "Ten ratios, DuPont, cash cycle, multi-year trend"],
  ["Distress", "Altman Z, Z′, Z″ and Ohlson, reconciled into one verdict"],
  ["Quality", "Piotroski F-Score and Beneish M-Score on the filing itself"],
  ["Market", "Merton distance-to-default and regression beta from prices"],
  ["Value", "DCF with every assumption exposed, Monte Carlo over all of it"],
  ["Memo", "Four specialist agents, a numeric-grounding curator, an editor"],
];

/** The index: every company on file with its latest verdicts, from one request. */
export default function Dashboard() {
  const [companies, setCompanies] = useState<CompanySummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    api
      .companySummaries()
      .then(setCompanies)
      .catch((err: Error) => setError(err.message));
  }, []);

  useEffect(load, [load]);

  return (
    <div className="space-y-10">
      <PageHeader
        eyebrow="Corporate credit, earnings quality and value"
        title={
          <>
            Every figure <em>computed</em>, none narrated into being
          </>
        }
        summary="Two bankruptcy models reconciled into one verdict, two forensic scores on the quality of the numbers, the equity market's own view of default, a DCF with no hidden assumptions, and a research memo whose every figure is checked against the computed context."
        actions={
          <>
            <Link to="/portfolio" className="btn-secondary">
              Portfolio Lab
            </Link>
            <Link to="/new" className="btn-primary">
              Add company
            </Link>
          </>
        }
      />

      <section aria-labelledby="companies-heading">
        <div className="mb-3 flex items-baseline justify-between gap-3">
          <div>
            <p className="section-no">01</p>
            <h2 id="companies-heading" className="sheet-title mt-0.5">
              Companies on file
            </h2>
          </div>
          {companies && <span className="font-mono text-xs text-muted-foreground">{companies.length} on file</span>}
        </div>
        <CompanyTable companies={companies} error={error} onRetry={load} />
      </section>

      <section aria-labelledby="pipeline-heading">
        <p className="section-no">02</p>
        <h2 id="pipeline-heading" className="sheet-title mt-0.5">
          What runs on each company
        </h2>
        <ol className="mt-4 grid border-t border-border sm:grid-cols-2 lg:grid-cols-3">
          {PIPELINE.map(([name, detail], index) => (
            <li key={name} className="border-b border-border py-4 sm:pr-6">
              <p className="font-mono text-xs text-muted-foreground">{String(index + 1).padStart(2, "0")}</p>
              <p className="mt-1 text-sm font-medium text-foreground">{name}</p>
              <p className="mt-1 text-sm text-muted-foreground">{detail}</p>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}

function CompanyTable({
  companies,
  error,
  onRetry,
}: {
  companies: CompanySummary[] | null;
  error: string | null;
  onRetry: () => void;
}) {
  const navigate = useNavigate();
  if (error) return <ErrorState title="Could not reach the API" message={error} onRetry={onRetry} />;
  if (!companies) return <LoadingBlock rows={3} label="Loading companies" />;
  if (companies.length === 0) {
    return (
      <EmptyState title="No companies yet" action={<Link to="/new" className="btn-primary">Add company</Link>}>
        Load the three sourced sample filings and their price histories with{" "}
        <code className="font-mono text-foreground">python backend/scripts/load_sample_filings.py</code>, or
        add a company by hand.
      </EmptyState>
    );
  }
  return (
    <div className="sheet overflow-x-auto">
      <table className="ledger">
        <thead>
          <tr>
            <th>Company</th>
            <th className="hidden md:table-cell">Sector class</th>
            <th>Verdict</th>
            <th className="hidden sm:table-cell">Altman zone</th>
            <th className="hidden sm:table-cell text-right">Health</th>
            <th className="hidden lg:table-cell">Market view</th>
            <th className="hidden lg:table-cell text-right">Merton PD</th>
            <th className="w-8">
              <span className="sr-only">Open</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {companies.map((company) => (
            <tr
              key={company.id}
              className="cursor-pointer"
              onClick={() => navigate(`/companies/${company.id}`)}
            >
              <td>
                <Link to={`/companies/${company.id}`} className="link font-medium text-foreground" onClick={(e) => e.stopPropagation()}>
                  {company.name}
                </Link>
                <p className="mt-0.5 font-mono text-2xs text-muted-foreground">
                  {[company.ticker, company.fiscal_year && `FY${company.fiscal_year}`, `${company.units.toLowerCase()} ${company.currency}`]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              </td>
              <td className="hidden md:table-cell text-muted-foreground">
                {SECTOR_LABELS[company.sector_class] ?? human(company.sector_class)}
              </td>
              <td>
                {company.consensus_verdict ? (
                  <span className={verdictChip(company.consensus_verdict)}>{VERDICT_LABELS[company.consensus_verdict]}</span>
                ) : (
                  <span className="chip-neutral">Not run</span>
                )}
              </td>
              <td className="hidden sm:table-cell">
                {company.altman_zone ? <span className={zoneChip(company.altman_zone)}>{human(company.altman_zone)}</span> : "—"}
              </td>
              <td className="hidden sm:table-cell num">{num(company.health_score, 1)}</td>
              <td className="hidden lg:table-cell">
                {company.market_view ? <span className={marketViewChip(company.market_view)}>{human(company.market_view)}</span> : "—"}
              </td>
              <td className="hidden lg:table-cell num">{probability(company.merton_probability_of_default)}</td>
              <td className="text-right text-muted-foreground">
                <ArrowRight size={16} strokeWidth={1.5} aria-hidden />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
