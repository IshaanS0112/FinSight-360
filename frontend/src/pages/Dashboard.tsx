import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { Company } from "../api/types";

const SECTOR_LABEL: Record<string, string> = {
  PUBLIC_MANUFACTURER: "Public manufacturer",
  PRIVATE_MANUFACTURER: "Private manufacturer",
  NON_MANUFACTURER: "Non-manufacturer",
  FINANCIAL: "Financial",
};

export default function Dashboard() {
  const [companies, setCompanies] = useState<Company[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listCompanies()
      .then(setCompanies)
      .catch((err: Error) => setError(err.message));
  }, []);

  if (error) {
    return (
      <p className="panel p-6 text-sm text-distress">
        Could not reach the API: {error}
      </p>
    );
  }
  if (!companies) return <p className="panel p-6 text-sm text-muted">Loading…</p>;

  return (
    <>
      <div className="mb-5 flex items-center justify-between">
        <h1 className="text-lg font-semibold text-slate-100">Companies</h1>
        <Link to="/new" className="btn-primary">
          Add company
        </Link>
      </div>

      {companies.length === 0 ? (
        <div className="panel p-6 text-sm text-muted">
          <p className="mb-2">No companies yet.</p>
          <p className="text-xs leading-relaxed">
            Load the three sourced sample filings with{" "}
            <code className="font-mono text-slate-400">
              python backend/scripts/load_sample_filings.py
            </code>
            , or add one by hand.
          </p>
        </div>
      ) : (
        <ul className="space-y-2">
          {companies.map((company) => (
            <li key={company.id}>
              <Link
                to={`/companies/${company.id}`}
                className="panel flex flex-wrap items-center justify-between gap-3 p-4 transition hover:border-accent/50"
              >
                <div>
                  <p className="font-medium text-slate-100">{company.name}</p>
                  <p className="mt-0.5 text-xs text-muted">
                    {company.industry ?? "industry unspecified"} · FY{company.fiscal_year} ·{" "}
                    {company.units.toLowerCase()} {company.currency}
                  </p>
                </div>
                <span className="chip border-edge bg-ink text-muted">
                  {SECTOR_LABEL[company.sector_class] ?? company.sector_class}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
