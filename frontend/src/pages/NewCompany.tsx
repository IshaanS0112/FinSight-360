import { useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import ActionButton from "../components/ActionButton";
import PageHeader from "../components/PageHeader";
import { InlineError } from "../components/States";
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

/** Create a company and upload its first balance sheet and income statement by hand. */
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
  const [createdId, setCreatedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A rejected statement must not leave a duplicate company behind on resubmit,
  // so the company is created once and the statements are retried against it.
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const id =
        createdId ??
        (
          await api.createCompany({
            name,
            industry: industry || null,
            sector_class: sectorClass,
            fiscal_year: fiscalYear ? Number(fiscalYear) : null,
            currency,
            units,
            data_source: dataSource,
          })
        ).id;
      setCreatedId(id);
      await uploadStatements(id, dataSource, numeric(balanceSheet), numeric(income));
      navigate(`/companies/${id}`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const selected = SECTOR_OPTIONS.find((option) => option.value === sectorClass)!;

  return (
    <form onSubmit={submit} className="space-y-6">
      <PageHeader
        eyebrow="New company"
        title={
          <>
            Add a company from its <em>filing</em>
          </>
        }
        summary="A company with no filing provenance is not an analysis input. Leave any line item blank that the filing does not disclose: the engine omits the ratios that need it rather than assuming zero."
      />

      <FormSection no="01" title="Company">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name">
            <input className="field" value={name} onChange={(e) => setName(e.target.value)} required placeholder="Caterpillar Inc." disabled={Boolean(createdId)} />
          </Field>
          <Field label="Industry">
            <input className="field" value={industry} onChange={(e) => setIndustry(e.target.value)} placeholder="Industrial machinery" disabled={Boolean(createdId)} />
          </Field>
          <Field label="Fiscal year">
            <input className="field" type="number" value={fiscalYear} onChange={(e) => setFiscalYear(e.target.value)} disabled={Boolean(createdId)} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Currency">
              <input className="field" value={currency} onChange={(e) => setCurrency(e.target.value.toUpperCase())} maxLength={3} disabled={Boolean(createdId)} />
            </Field>
            <Field label="Units">
              <select className="field" value={units} onChange={(e) => setUnits(e.target.value)} disabled={Boolean(createdId)}>
                {["UNITS", "THOUSANDS", "LAKHS", "MILLIONS", "CRORE", "BILLIONS"].map((u) => (
                  <option key={u} value={u}>
                    {u.toLowerCase()}
                  </option>
                ))}
              </select>
            </Field>
          </div>
        </div>
        <Field label="Sector class" hint={selected.hint}>
          <select className="field" value={sectorClass} onChange={(e) => setSectorClass(e.target.value as SectorClass)} disabled={Boolean(createdId)}>
            {SECTOR_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Data source (required)" hint="The filing and the statement the figures were copied from.">
          <input
            className="field"
            value={dataSource}
            onChange={(e) => setDataSource(e.target.value)}
            required
            minLength={3}
            placeholder="Caterpillar Inc. FY2024 10-K, consolidated balance sheet"
            disabled={Boolean(createdId)}
          />
        </Field>
      </FormSection>

      <FormSection
        no="02"
        title="Balance sheet"
        lead="Assets must equal liabilities plus equity within 0.5%, or the upload is rejected: every asset-scaled ratio would inherit a transcription error."
      >
        <AmountGrid keys={BALANCE_SHEET_KEYS} draft={balanceSheet} onChange={setBalanceSheet} />
      </FormSection>

      <FormSection no="03" title="Income statement">
        <AmountGrid keys={INCOME_KEYS} draft={income} onChange={setIncome} />
      </FormSection>

      {error && (
        <InlineError
          message={createdId ? `The company was created, but a statement was rejected: ${error} Correct it and submit again.` : error}
          onDismiss={() => setError(null)}
        />
      )}

      <div className="flex gap-3">
        <ActionButton type="submit" busy={busy} busyLabel="Saving">
          {createdId ? "Upload statements" : "Create company"}
        </ActionButton>
        <button type="button" onClick={() => navigate(createdId ? `/companies/${createdId}` : "/")} className="btn-secondary">
          {createdId ? "Skip to company" : "Cancel"}
        </button>
      </div>
    </form>
  );
}

/** Blank or non-numeric inputs are dropped, never sent as zero. */
function numeric(draft: Draft): Record<string, number> {
  return Object.fromEntries(
    Object.entries(draft)
      .filter(([, value]) => value.trim() !== "" && Number.isFinite(Number(value)))
      .map(([key, value]) => [key, Number(value)]),
  );
}

/** Uploads whichever statements have at least one figure, balance sheet first. */
async function uploadStatements(
  companyId: string,
  sourceNote: string,
  balanceSheet: Record<string, number>,
  income: Record<string, number>,
) {
  const statements: { type: StatementTypeName; items: Record<string, number> }[] = [
    { type: "BALANCE_SHEET", items: balanceSheet },
    { type: "INCOME_STATEMENT", items: income },
  ];
  for (const statement of statements) {
    if (Object.keys(statement.items).length === 0) continue;
    await api.uploadStatement(companyId, {
      statement_type: statement.type,
      line_items: statement.items,
      source_note: sourceNote,
    });
  }
}

function FormSection({ no, title, lead, children }: { no: string; title: string; lead?: string; children: ReactNode }) {
  return (
    <section className="sheet space-y-4 p-4 sm:p-6">
      <div>
        <p className="section-no">{no}</p>
        <h2 className="sheet-title mt-0.5">{title}</h2>
        {lead && <p className="prose-measure mt-1 text-xs leading-relaxed text-muted-foreground">{lead}</p>}
      </div>
      {children}
    </section>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-muted-foreground">{hint}</span>}
    </label>
  );
}

function AmountGrid({ keys, draft, onChange }: { keys: string[]; draft: Draft; onChange: (next: (prev: Draft) => Draft) => void }) {
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      {keys.map((key) => (
        <Field key={key} label={key.replace(/_/g, " ")}>
          <input
            className="field font-mono"
            type="number"
            step="any"
            inputMode="decimal"
            value={draft[key] ?? ""}
            onChange={(e) => onChange((prev) => ({ ...prev, [key]: e.target.value }))}
          />
        </Field>
      ))}
    </div>
  );
}
