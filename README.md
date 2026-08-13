# FinSight 360

**Corporate financial health and risk intelligence.** A ratio engine, the Altman
bankruptcy models applied to the population each was actually estimated on, and a
weighted health composite benchmarked against peers — with an LLM that writes the
assessment up and computes none of it.

FastAPI · PostgreSQL · React + TypeScript + Tailwind · Docker · Claude API

---

## Why I built this

I got interested in credit analysis after reading about the Altman Z-score and
realising it was a 1968 linear discriminant function that banks still use — five
ratios, five coefficients, three zones, and a paper you can read in an afternoon.
It is unusually honest for a risk model: no black box, no fitted neural net, just
a formula whose weights you can argue with.

Then I found the interesting part. The 1968 model was estimated on **publicly
traded manufacturers**. Almost every online Z-score calculator applies it to
anything with a balance sheet, which means most Z-scores you see for services,
telecom, or retail companies are technically misapplications. Altman published
corrections for exactly this — Z′ for private firms, Z″ for non-manufacturers and
emerging markets — and they are much less widely implemented.

So this project implements all three, chooses between them from the company's
sector class, and **refuses to score banks at all**, because Altman excluded
financial firms from every estimation sample and for a bank high leverage is the
business model rather than a distress signal.

The other thing I wanted to get right: the LLM does not compute anything. It
receives already-computed numbers and writes prose. That constraint is enforced in
code and tested, not just promised in a README.

---

## What it does

Upload a company's financial statement line items, and it:

1. **Computes ten ratios** across liquidity, profitability, leverage and
   efficiency — and reports which ones it *could not* compute, and why.
2. **Selects and runs the applicable Altman model** (Z, Z′ or Z″) based on sector
   class, decomposed term by term so you can see which component drove the verdict.
3. **Scores a weighted health composite** against a peer median or a configured
   reference band, clearly labelled as a project-defined composite rather than a
   published methodology.
4. **Generates a written assessment** from the computed numbers, with any figure
   the model cites that is not in the input silently dropped and counted.

---

## Validated against companies with known outcomes

Two validation pairs from real filings, one per model variant:

| Company | FY | Sector | Model | Score | Zone | Known outcome |
|---|---|---|---|---|---|---|
| Caterpillar Inc. | 2024 | public manufacturer | **Z (1968)** | 3.9203 | **SAFE** | profitable, investment grade ✓ |
| Infosys Ltd | 2024 | non-manufacturer | **Z″** | 8.6494 | **SAFE** | debt-free, high margin ✓ |
| Vodafone Idea Ltd | 2024 | non-manufacturer | **Z″** | −5.9633 | **DISTRESS** | negative net worth of −₹1,041,668m ✓ |

Every figure is reproduced by `backend/tests/test_altman_zscore.py`, which reads
the sample filing JSON directly — edit a filing to a value that no longer produces
the documented verdict and CI fails.

**And the honest caveat, because it matters more than the three ticks:** Vodafone
Idea's score is reported as `confidence: PARTIAL`. Its operating income is not
published in the source used and is not derivable from what is, so `x3` is listed
in `omitted_components` and the score is a four-term partial sum. The verdict does
not depend on the missing term — the remaining four land at −5.96 against a
distress cutoff of 1.10 — but the response says it is partial rather than
presenting a complete-looking number. Full provenance for all three companies,
including the two derived figures, is in
[`data/sample_filings/README.md`](data/sample_filings/README.md).

Caterpillar's total assets figure was cross-checked directly against the SEC's
XBRL extraction from the 10-K (`87,764,000,000`), reproducible via
`backend/scripts/fetch_sec_filing.py`.

---

## Run it

Full step-by-step setup, verification checks and troubleshooting:
**[RUNNING.md](RUNNING.md)**. The short version:

```bash
git clone <this repo> && cd FinSight360

# Optional: without it, insight reports use the deterministic template fallback.
# Every ratio, Z-score and health score is identical either way.
export ANTHROPIC_API_KEY=sk-ant-...

docker compose up --build
```

- API and interactive docs → <http://localhost:8000/docs>
- Dashboard → <http://localhost:5173>
- Parameters actually in force → <http://localhost:8000/methodology>

Load the three sourced companies and see the validation run:

```bash
python backend/scripts/load_sample_filings.py
```

```
Loading 3 sample filing(s) into http://localhost:8000
  OK Caterpillar Inc.: Z_1968 = 3.9203 -> SAFE (expected SAFE, confidence COMPLETE), health 63.81, narrative by template_fallback
  OK Infosys Limited: Z_DOUBLE_PRIME = 8.6494 -> SAFE (expected SAFE, confidence COMPLETE), health 65.11, narrative by template_fallback
  OK Vodafone Idea Limited: Z_DOUBLE_PRIME = -5.9633 -> DISTRESS (expected DISTRESS, confidence PARTIAL), health 12.97, narrative by template_fallback
     omitted components: ['x3']
```

Caterpillar and Infosys land close together on the health composite (63.8 vs 65.1)
despite very different balance sheets — Caterpillar scores far higher on
profitability, Infosys on leverage and efficiency. That is the composite behaving
as designed rather than a bug, and it is a fair illustration of why a single
blended number is the least informative output in this system. The component
breakdown and the Z-score are the useful parts.

### Tests, with nothing running

```bash
cd backend && pip install -r requirements-dev.txt && pytest
```

**88 tests, no database container required.** The SQLAlchemy models declare JSONB
and UUID as *dialect variants*, so the same schema loads on SQLite and the API
integration tests exercise the real FastAPI app end to end on a fresh clone. The
engine tests import the computation functions directly — no database, no network,
no model — because every analytical claim this project makes is a claim about
those functions.

---

## The models

### Altman, all three variants

| Model | Population | X4 numerator | Terms | Cutoffs |
|---|---|---|---|---|
| `Z_1968` | public manufacturers | **market** value of equity | X1…X5 | 2.99 / 1.81 |
| `Z_PRIME` | private manufacturers | **book** value of equity | X1…X5 | 2.90 / 1.23 |
| `Z_DOUBLE_PRIME` | non-manufacturers, emerging markets | book value of equity | X1…X4 (no X5) | 2.60 / 1.10 |

```
X1 = working capital / total assets      short-term liquidity relative to size
X2 = retained earnings / total assets    how much of the balance sheet was self-funded
X3 = EBIT / total assets                 operating earning power, before capital structure
X4 = equity value / total liabilities    how far assets can fall before liabilities exceed them
X5 = sales / total assets                asset productivity (dropped in Z″)
```

Selection is by **sector class, not by which inputs happen to be present**. A
public manufacturer with no fiscal-year-end market cap gets Z′ — not Z-1968 with
book equity substituted in, which is a common shortcut and is wrong, because Z′
re-estimated every coefficient precisely to account for that switch.

`docs/architecture.md` constructs a company scoring **2.74 (SAFE) under Z″ and
1.36 (DISTRESS) under the 1968 coefficients** — same balance sheet, opposite
verdict. That test is why selection is not left to the caller.

### Ratios

```
Liquidity      current ratio, quick ratio
Profitability  ROE, ROA, net margin, gross margin
Leverage       debt-to-equity, interest coverage
Efficiency     asset turnover, inventory turnover
```

Ratio definitions genuinely disagree between providers, so the form implemented is
recorded in every response. `docs/architecture.md` works through two real
disagreements against published S&P figures for Vodafone Idea — a quick ratio 0.05
apart on definition, and an asset turnover 0.01 apart on ending-vs-average
balances — alongside a Caterpillar gross margin that ties to the published 37.97%
exactly.

### Health score — a composite this project defines

```
health = 0.35·profitability + 0.25·liquidity + 0.20·leverage + 0.20·efficiency
```

This one is **not** an established model, and it says so in the API response, in
`/methodology`, and above the number in the UI. The weights are a judgement and
the normalisation is a judgement; both are declared in `config.py` so you can
disagree with the specific values rather than guess at them.

---

## Design decisions worth defending

**Missing is never zero.** A quick ratio computed with inventory silently
defaulted to zero *equals the current ratio* — a wrong number that looks entirely
reasonable. Absent line items omit the ratios that need them, and the omission is
stored as data with a reason.

**Undefined ratios are withheld, not reported.** Vodafone Idea's ROE naively
computes to **+29.99%** — a ₹312bn loss divided by negative equity. That reads as
strong performance for a company whose liabilities exceed its assets. ROE and
debt-to-equity are withheld at non-positive equity; the test asserts the naive
value *would* have been positive, so it documents the trap it prevents.

**Banks get no score.** `zone: NOT_APPLICABLE`, with an explanation and a pointer
to CAMELS-style ratios or a Merton distance-to-default instead.

**The balance sheet must balance.** Assets = liabilities + equity within 0.5%, or
the upload is rejected with the residual in the message. Every ratio and every
Altman component is scaled by total assets, so one dropped digit moves the whole
analysis by one consistent wrong factor and nothing downstream looks odd.

**`peer_percentile` is always null.** A percentile over four companies presented
as an industry position would be a claim this dataset cannot support.

**The reference benchmark bands are labelled placeholders.** No invented
attribution. Load three same-industry companies and the engine switches to the
peer median; or point `REFERENCE_BENCHMARKS_PATH` at your own sourced table.
Every scored ratio reports which basis produced its benchmark.

**The LLM narrates and cannot introduce a figure.** The full structured context is
frozen before the call, stored beside the narrative, and returned by the API. Any
metric the model cites that is not in that context is dropped and counted. So
"the AI did not invent this" is checkable by diffing the two, not taken on trust —
and with no API key configured, the template fallback produces the same report
minus the prose.

---

## API

```
POST   /companies                                  create
GET    /companies                                  list
POST   /companies/{id}/financial-statements        upload (validates the balance sheet)
GET    /companies/{id}/line-items                  exactly what the engines see

POST   /companies/{id}/compute-ratios              ratio engine
POST   /companies/{id}/compute-bankruptcy-risk     Altman (optional model override)
POST   /companies/{id}/compute-health-score        weighted composite
POST   /companies/{id}/generate-insights           narrative over the stored results
POST   /companies/{id}/run-full-analysis           all four, in order

GET    /companies/{id}/ratio-analysis              latest of each
GET    /companies/{id}/bankruptcy-risk
GET    /companies/{id}/health-score
GET    /companies/{id}/insights-report

GET    /methodology                                every coefficient, cutoff and weight in force
GET    /health
```

Analysis tables are **append-only**: re-running a stage after correcting a filing
inserts a new row and leaves the old one. "The number changed when we fixed the
statement" is the audit trail this kind of tool needs.

---

## Layout

```
FinSight360/
├── backend/
│   ├── app/
│   │   ├── services/
│   │   │   ├── ratio_engine.py        10 ratios, and the refusals
│   │   │   ├── altman_zscore.py       Z / Z′ / Z″, model selection, sector refusal
│   │   │   ├── health_score.py        weighted composite, renormalisation
│   │   │   ├── insights_generator.py  structured context → constrained LLM → validated
│   │   │   ├── line_items.py          closed line-item vocabulary, safe reads
│   │   │   ├── benchmarks.py          peer median / reference bands / provenance
│   │   │   └── analysis_pipeline.py   orchestration, balance-sheet check
│   │   ├── models/  schemas/  routers/  db/
│   │   ├── config.py                  every coefficient, cutoff and weight
│   │   └── main.py                    app + /methodology
│   ├── tests/                         88 tests, no DB container needed
│   └── scripts/
│       ├── load_sample_filings.py     load the 3 companies, print the validation
│       └── fetch_sec_filing.py        primary-source XBRL pull for US filers
├── frontend/src/
│   ├── components/  ZScoreGauge · RatioDashboard · HealthScoreView · InsightsPanel
│   └── pages/       Dashboard · CompanyDetail · NewCompany · Methodology
├── data/sample_filings/               3 real filings + full provenance
├── docs/  architecture.md · schema.sql
└── docker-compose.yml
```

---

## Roadmap

**V2 — multi-year trend analysis.** The single biggest limitation. One fiscal year
cannot distinguish a stable position from a deteriorating one, and it is also why
turnover ratios currently use ending rather than average balances.

**V2 — DCF valuation.** Deliberately not in V1. Genuinely more complex than a
ratio table, and rushing it would produce exactly the kind of invented number this
project exists to avoid.

**V2 — a real reference population**, at which point `peer_percentile` can carry a
number instead of a null and an explanation.

**Also queued:** Alembic migrations (needed the moment a column changes shape),
Ohlson O-score and Zmijewski as alternative models to compare Altman against, and
authentication before this goes anywhere near real credit data.
