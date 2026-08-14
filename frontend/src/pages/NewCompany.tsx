import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import type { SectorClass, StatementTypeName } from "../api/types";

const SECTOR_OPTIONS: { value: SectorClass; label: string; hint: string }[] = [
  {
    value: "PUBLIC_MANUFACTURER",
    label: "Public manufacturer",
    hint: "Altman Z (1968) applies as published, needs market value of equity at FY end.",
  },
  {
    value: "PRIVATE_MANUFACTURER",
    label: "Private manufacturer",
    hint: "Altman Z′, book value of equity, re-estimated coefficients.",
  },
  {
    value: "NON_MANUFACTURER",
    label: "Non-manufacturer",
    hint: "Altman Z″, drops sales/assets. Services, telecom, retail, IT.",
  },
  {
    value: "FINANCIAL",
    label: "Financial (bank, insurer)",
    hint: "No Z-score is reported: Altman excluded financial firms from every sample.",
  },
];

const BALANCE_SHEET_KEYS = [
  "total_assets",
  "current_assets",
  "current_liabilities",
  "total_liabilities",
  "inventory",
  "shareholder_equity",
  "retained_earnings",
  "total_debt",
  "market_value_equity",
];

const INCOME_KEYS = ["revenue", "cogs", "gross_profit", "ebit", "net_income", "interest_expense"];

type Draft = Record<string, string>;

export default function NewCompany() {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [industry, setIndustry] = useState("");
  const [sectorClass, setSectorClass] = useState<SectorClass>("PUBLIC_MANUFACTURER");
  const [fiscalYear, setFiscalYear] = useState("2024");
  const [currency, setCurrency] = useState("USD");
  const [units, setUnits] = useState("MILLIONS");
  const [dataSource, setDataSource] = useState("");
  const [balanceSheet, setBalanceSheet] = useState<Draft>({});
  const [income, setIncome] = useState<Draft>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const numeric = (draft: Draft): Record<string, number> =>
    Object.fromEntries(
      Object.entries(draft)
        .filter(([, value]) => value.trim() !== "" && Number.isFinite(Number(value)))
        .map(([key, value]) => [key, Number(value)]),
    );

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const company = await api.createCompany({
        name,
        industry: industry || null,
        sector_class: sectorClass,
        fiscal_year: fiscalYear ? Number(fiscalYear) : null,
        currency,
        units,
        data_source: dataSource,
      });

      const statements: { type: StatementTypeName; items: Record<string, number> }[] = [
        { type: "BALANCE_SHEET", items: numeric(balanceSheet) },
        { type: "INCOME_STATEMENT", items: numeric(income) },
      ];
      for (const statement of statements) {
        if (Object.keys(statement.items).length === 0) continue;
        await api.uploadStatement(company.id, {
          statement_type: statement.type,
          line_items: statement.items,
          source_note: dataSource,
        });
      }

      navigate(`/companies/${company.id}`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const selected = SECTOR_OPTIONS.find((option) => option.value === sectorClass)!;

  return (
    <form onSubmit={submit} className="space-y-5">
      <h1 className="text-lg font-semibold text-slate-100">Add a company</h1>

      <section className="panel space-y-4 p-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label">Name</label>
            <input
              className="field"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              minLength={1}
              placeholder="Caterpillar Inc."
            />
          </div>
          <div>
            <label className="label">Industry</label>
            <input
              className="field"
              value={industry}
              onChange={(e) => setIndustry(e.target.value)}
              placeholder="industrial machinery"
            />
          </div>
          <div>
            <label className="label">Fiscal year</label>
            <input
              className="field"
              type="number"
              value={fiscalYear}
              onChange={(e) => setFiscalYear(e.target.value)}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">Currency</label>
              <input
                className="field"
                value={currency}
                onChange={(e) => setCurrency(e.target.value.toUpperCase())}
                maxLength={3}
              />
            </div>
            <div>
              <label className="label">Units</label>
              <select
                className="field"
                value={units}
                onChange={(e) => setUnits(e.target.value)}
              >
                {["UNITS", "THOUSANDS", "LAKHS", "MILLIONS", "CRORE", "BILLIONS"].map((u) => (
                  <option key={u} value={u}>
                    {u.toLowerCase()}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>

        <div>
          <label className="label">Sector class</label>
          <select
            className="field"
            value={sectorClass}
            onChange={(e) => setSectorClass(e.target.value as SectorClass)}
          >
            {SECTOR_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-muted">{selected.hint}</p>
        </div>

        <div>
          <label className="label">Data source (required)</label>
          <input
            className="field"
            value={dataSource}
            onChange={(e) => setDataSource(e.target.value)}
            required
            minLength={3}
            placeholder="Caterpillar Inc. FY2024 10-K, consolidated balance sheet"
          />
          <p className="mt-1 text-xs text-muted">
            A company with no filing provenance is not an analysis input.
          </p>
        </div>
      </section>

      <section className="panel p-5">
        <h2 className="mb-1 text-sm font-semibold uppercase tracking-wider text-muted">
          Balance sheet
        </h2>
        <p className="mb-3 text-xs text-muted">
          Assets must equal liabilities plus equity within 0.5%, or the upload is rejected -
          every asset-scaled ratio would inherit a transcription error. Leave a field blank if
          the filing does not disclose it; the engine will omit the ratios that need it rather
          than assume zero.
        </p>
        <div className="grid gap-3 sm:grid-cols-3">
          {BALANCE_SHEET_KEYS.map((key) => (
            <div key={key}>
              <label className="label">{key.replace(/_/g, " ")}</label>
              <input
                className="field"
                type="number"
                step="any"
                value={balanceSheet[key] ?? ""}
                onChange={(e) =>
                  setBalanceSheet((prev) => ({ ...prev, [key]: e.target.value }))
                }
              />
            </div>
          ))}
        </div>
      </section>

      <section className="panel p-5">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted">
          Income statement
        </h2>
        <div className="grid gap-3 sm:grid-cols-3">
          {INCOME_KEYS.map((key) => (
            <div key={key}>
              <label className="label">{key.replace(/_/g, " ")}</label>
              <input
                className="field"
                type="number"
                step="any"
                value={income[key] ?? ""}
                onChange={(e) => setIncome((prev) => ({ ...prev, [key]: e.target.value }))}
              />
            </div>
          ))}
        </div>
      </section>

      {error && <p className="panel p-3 text-xs text-distress">{error}</p>}

      <div className="flex gap-3">
        <button type="submit" disabled={busy} className="btn-primary">
          {busy ? "Saving…" : "Create and analyse"}
        </button>
        <button type="button" onClick={() => navigate("/")} className="btn-ghost">
          Cancel
        </button>
      </div>
    </form>
  );
}
