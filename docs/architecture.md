# FinSight 360: architecture

```
React + TS + Tailwind  ◄──►  FastAPI  ──►  PostgreSQL 16
                                │
        ┌───────────────────────┼──────────────────┬──────────────────┐
        ▼                       ▼                  ▼                  ▼
  Ratio engine          Altman Z / Z′ / Z″    Health score      Insight generator
  (10 ratios,           (model chosen by      (weighted         (structured context
   arithmetic)           sector class)         composite)        ──► LLM ──► validated)
                                                                        │
                                                                   Claude API
                                                              (narration only; falls
                                                               back to a template)
```

Backend layout mirrors the other projects in this portfolio (`AstraSynth`,
`OpsForge`, `StrategySphere`): `models/` for persistence, `schemas/` for the HTTP
contract, `services/` for pure computation, `routers/` for transport only. Every
service function is importable and testable without a database, which is why
`backend/tests/` can verify the analytical claims with nothing running.

---

## What's real vs simulated

**Real, all of it.**

| Layer | Status |
|---|---|
| Ratio arithmetic | Real. Ten standard ratios over reported line items. No estimation, no model. |
| Altman Z (1968), Z′, Z″ | Real, published discriminant functions with the published coefficients and cutoffs. Cited in code and returned in every response. |
| Model selection by sector | Real logic, and the part most implementations get wrong (see below). |
| Financial-sector refusal | Real. Banks and insurers get no score, with an explanation. |
| Balance-sheet identity check | Real. Assets = liabilities + equity within 0.5% or the upload is rejected. |
| Sample company data | Real public filings for Caterpillar FY2024, Infosys FY2024, Vodafone Idea FY2024. Provenance and the two derived figures are documented in `data/sample_filings/README.md`. |

**Not an established model, and labelled as such everywhere it appears:**

- **The weighted health score.** The 0.35/0.25/0.20/0.20 weights and the 0–100
  normalisation are this project's judgement, not a published methodology.
  `GET /methodology` returns `"status": "PROJECT-DEFINED COMPOSITE, not an
  established model"`, and the UI prints that line above the number.

**Placeholders, and labelled as such:**

- **The reference benchmark bands** in `services/benchmarks.py` are illustrative
  round numbers. They are unattributed, because inventing an
  attribution would be worse than admitting they are placeholders. Two real paths
  exist and neither needs a code change: load three or more same-industry
  companies and the engine benchmarks against the peer median, or point
  `REFERENCE_BENCHMARKS_PATH` at your own sourced table. Every scored ratio
  carries its `benchmark_basis` so a reader can always see which path produced a
  number.

- **`peer_percentile` is always `null`.** A percentile needs a distribution, and
  three peers is not one. The field stays null rather than reporting a percentile
  of four companies as an industry position.

**Simulated: nothing.** There is no synthetic data generator, no random
component, no seeded noise. The same line items always produce the same numbers.

---

## The decision this project turns on

The original spec asked for one bankruptcy model:

```
Z = 1.2·X1 + 1.4·X2 + 3.3·X3 + 0.6·X4 + 1.0·X5      safe > 2.99, distress < 1.81
```

That is Altman (1968), and it was estimated on a sample of **publicly traded
manufacturing firms**. Implementing only that model and then running it on an IT
services company or a telecom operator would produce numbers that look right and
mean nothing. The arithmetic works, but the coefficients and cutoffs were fitted
to a population those firms are not drawn from.

Altman published the corrections himself. All three are implemented:

| Model | Population | X4 numerator | Terms | Cutoffs |
|---|---|---|---|---|
| `Z_1968` | public manufacturers | **market** value of equity | X1…X5 | 2.99 / 1.81 |
| `Z_PRIME` (Z′) | private manufacturers | **book** value of equity | X1…X5 | 2.90 / 1.23 |
| `Z_DOUBLE_PRIME` (Z″) | non-manufacturers, emerging markets | book value of equity | X1…X4 (no X5) | 2.60 / 1.10 |

Three consequences, each with a test:

**1. Selection is by sector class, not by which inputs happen to be present.**
`test_non_manufacturer_never_gets_the_1968_model` supplies a market value of
equity for Infosys and confirms Z″ is still chosen. A naive implementation
switches on data availability and silently misapplies the 1968 model to every
services company that happens to be listed.

**2. Getting the variant wrong can flip the verdict.**
`test_misapplied_1968_model_can_flip_a_verdict` constructs a non-manufacturer
scoring **2.74 under Z″: SAFE**, above the 2.60 cutoff, and **1.36 under the 1968
coefficients, DISTRESS**, below the 1.81 cutoff. Same balance sheet, opposite
conclusion, purely from applying coefficients fitted elsewhere against cutoffs
calibrated for them.

**3. A public manufacturer with no year-end market cap gets Z′, not
Z-1968-with-book-equity.** Substituting book equity into the 1968 coefficients is
a common shortcut and it is wrong: Z′ re-estimated *every* coefficient precisely
to account for that switch. Covered by
`test_public_manufacturer_without_market_cap_falls_back_to_z_prime`.

### And a refusal

Financial-sector issuers get `zone: NOT_APPLICABLE` and no score. Altman excluded
banks and insurers from every estimation sample, and for a good reason: for a
bank, high leverage *is* the business model, so "liabilities near assets" is
normal rather than terminal, and the asset side is not comparable to an operating
company's. The response says so, and points at CAMELS-style supervisory ratios or
a Merton distance-to-default instead.

---

## Validation against companies with known outcomes

Two pairs, one per model variant, from real filings. Every figure below is
reproduced by `backend/tests/test_altman_zscore.py`, which reads the JSON files in
`data/sample_filings/` directly, so a filing edited to a value that no longer
produces the documented verdict fails CI.

| Company | FY | Sector | Model | Score | Zone | Expected |
|---|---|---|---|---|---|---|
| Caterpillar Inc. | 2024 | public manufacturer | Z (1968) | **3.9203** | SAFE | healthy ✓ |
| Infosys Ltd | 2024 | non-manufacturer | Z″ | **8.6494** | SAFE | healthy ✓ |
| Vodafone Idea Ltd | 2024 | non-manufacturer | Z″ | **−5.9633** | DISTRESS | distressed ✓ |

Caterpillar, term by term:

```
X1 = 13,410 / 87,764 = 0.15280   × 1.2 =  0.18336
X2 = 59,352 / 87,764 = 0.67626   × 1.4 =  0.94676
X3 = 13,072 / 87,764 = 0.14894   × 3.3 =  0.49150
X4 = 177,528 / 68,270 = 2.60039  × 0.6 =  1.56023
X5 = 64,809 / 87,764 = 0.73845   × 1.0 =  0.73845
                                          -------
                                     Z =  3.9203   →  SAFE (> 2.99)
```

Vodafone Idea's verdict is driven by two balance-sheet facts, not estimates:
working capital of **−412,315**m INR (X1) and an accumulated deficit of
**−2,339,687**m against total assets of 1,849,977m (X2). Its shareholders' equity
is **−1,041,668**m: liabilities exceed assets outright.

### The honest part of the validation

Vodafone Idea's result is **`confidence: PARTIAL`**. Operating income is not
published as a standardised line item in the source used, and it is not derivable
without a depreciation figure that is also unavailable. So `ebit` is absent from
the filing, `x3` is listed in `omitted_components`, the response carries a
`partial_score_warning`, and the score is a four-term partial sum.

The verdict does not depend on the missing term. The four remaining terms land at
−5.96 against a distress cutoff of 1.10, and no plausible X3 closes a seven-point
gap. But the result says it is partial rather than presenting a complete-looking
number, because a partial sum is biased toward the cutoffs and a reader is
entitled to know.

### A primary-source cross-check

Caterpillar's total assets figure was verified straight against the SEC's XBRL
extraction from the 10-K:

```
GET https://data.sec.gov/api/xbrl/companyconcept/CIK0000018230/us-gaap/Assets.json
  → {"end":"2024-12-31","val":87764000000,"form":"10-K","fy":2024}
```

`backend/scripts/fetch_sec_filing.py` reproduces that for any US filer.

---

## Ratio definitions disagree, and the disagreement is worth showing

Ratio definitions vary between data providers. Two worked comparisons against figures published by
S&P Global Market Intelligence for **Vodafone Idea FY2024**:

**Current ratio: agreement.** Both compute 129,098 / 541,413 = **0.24**. The
definition is not contested, so an exact tie is evidence that the transcription
and the arithmetic are both right. `test_gross_margin_reproduces_the_published_figure`
does the same job for Caterpillar's gross margin (37.97%, exact).

**Quick ratio: definitional difference.**

```
This project (spec form):  (129,098 − 12) / 541,413        = 0.24
S&P (strict form):   (1,684 cash + 101,972 recv) / 541,413 = 0.19
```

Vodafone Idea holds essentially no inventory (12m INR), so subtracting it changes
nothing and the "quick" ratio collapses onto the current ratio. S&P's stricter
form counts only cash, short-term investments and receivables (excluding the
125,000m+ of *other* current assets) and lands 0.05 lower. Neither is wrong. This
project implements the spec's form and records
`quick_ratio_definition` in `calculation_basis` so the difference is visible
rather than mysterious.

**Asset turnover: ending vs average balances.**

```
This project (ending assets):  426,517 / 1,849,977                      = 0.23
S&P (average assets):          426,517 / ((1,849,977 + 2,072,427) / 2)  = 0.22
```

Average balances are the more defensible choice when a company's asset base moved
11% during the year. This is a single-fiscal-year system (V1 scope), so
there is no prior-year balance to average with. `calculation_basis` reports
`turnover_basis: ENDING_BALANCE` rather than calling an ending figure an average.
Multi-year support is the V2 item that fixes it properly.

---

## Design decisions

**Missing is not zero.** `line_items.get` returns `None` for an absent item and
never coerces it to `0.0`. A quick ratio computed with inventory silently
defaulted to zero equals the current ratio: a wrong number that looks entirely
reasonable. Every engine reports what it could not compute and why; those
omissions are stored as data, not logged.

**Ratios that are undefined are withheld, not reported.** Vodafone Idea's ROE
naively computes to **+29.99%** from a loss of −312,387 divided by equity of
−1,041,668. That reads as strong performance for a company whose liabilities
exceed its assets. ROE and debt-to-equity are both withheld at non-positive
equity, with the reason attached. `test_negative_equity_withholds_roe_and_debt_to_equity`
asserts the naive value would have been positive, so the test documents the trap
it prevents.

**Negative X4 is not clamped.** The same negative equity that makes ROE
meaningless is exactly the signal Altman's X4 is designed to capture, so it flows
straight through to a negative contribution.

**Weights are validated at construction.** `Settings` refuses to build if the
four health weights do not sum to 1.0. An unnormalised weight vector silently
rescales every score, so the 0–100 range would stop meaning what the docs say.

**The health composite saturates.** Twice the benchmark scores 100 and nothing
scores higher. Without the cap, a single freak ratio (a quick ratio of 30 because
the company just raised equity) would drag the composite up and the range would
stop meaning anything.

**A dropped component renormalises rather than scoring zero.** A company that
discloses no income statement is not thereby unhealthy. The remaining weights are
renormalised to 1.0 and `renormalisation_note` records what happened.

**The balance sheet must balance.** Every ratio and every Altman component is
scaled by total assets, so one mistyped digit there moves the whole analysis by
one consistent wrong factor and nothing downstream looks odd. A 0.5% tolerance
absorbs rounding in millions-scale filings; beyond that the upload is rejected
with the residual in the message.

**Unknown line-item keys are rejected, not ignored.** A payload containing
`total_asets` would otherwise store cleanly and then silently omit every ratio
that needed it.

**Analysis tables are append-only.** Re-running a stage after correcting a filing
inserts a new row. "The number changed when we fixed the statement" is the audit
trail this kind of tool needs.

**The insight report narrates stored results, not fresh ones.** Rehydrating the
persisted rows (`services/enums_bridge.py`) rather than recomputing closes the
gap between the numbers the API returned and the numbers the prose describes.

**`GET /methodology` exists so the central claim is checkable.** Every coefficient,
cutoff, weight and formula in force is returned by the running service, including
anything overridden by environment variable. The UI's Methodology page reads it
live rather than hardcoding the values.

---

## Lessons learned

**Implementing a named model is the easy half. Knowing its domain is the half that
matters.** The 1968 Z-score is five multiplications and an addition; anyone can
write it in ten minutes. Working out that it does not apply to Infosys, that
substituting book equity into it is not the same as using Z′, and that a bank
should get no score at all took considerably longer than writing the arithmetic.
It is also the only part of this module that would survive scrutiny from someone
who actually uses these models.

**Refusing to produce a number is a feature, and it is the hardest one to build.**
Every refusal in this codebase (ROE at negative equity, no Z-score for financial
issuers, `peer_percentile` left null, an unbalanced sheet rejected) started as a
number the code would happily have returned. Each one required deciding that a
missing answer beats a confident wrong one, then finding somewhere in the response
to explain the absence so it reads as a decision rather than a gap.

**Vodafone Idea's ROE is the example that changed how I write ratios.** +29.99%
from a 312-billion-rupee loss. Nothing in the arithmetic is wrong; a negative
divided by a negative is positive. It was a reminder that a formula's output being
mathematically correct says nothing about whether it means what its name implies,
and that the guard belongs in the engine rather than in a caveat someone might
read.

**Discovering that S&P and I disagreed on the quick ratio was more useful than
agreeing would have been.** The first instinct was that something was broken. It
It was a different, and arguably better, definition. Writing down which form is
implemented and why turned a suspected bug into the most interesting paragraph in
these docs, and it is now the thing I would rather be asked about than the
Z-score itself.

**Honest data provenance is more work and worth it.** It would have been faster to
write "parsed from SEC filings" than to record that the line items were
transcribed from standardised statements, that two figures are derived, exactly
how each was derived, and that one company's EBIT is genuinely unavailable. The
`PARTIAL` confidence path exists *because* of that last admission, and it is now
one of the better-engineered parts of the system.

---

## Known limits

| Limit | Status |
|---|---|
| Single fiscal year | V1 scope. A single year cannot distinguish a stable position from a deteriorating one; V2. |
| Turnover uses ending balances | Falls out of the single-year scope. Fixed by V2 multi-year support. |
| Reference benchmark bands are placeholders | Labelled as such everywhere. Two real paths shipped: peer median, or your own sourced table. |
| `peer_percentile` always null | Deliberate. Needs a real reference population, not four companies. |
| No DCF valuation | V2. Genuinely more complex than a ratio table; rushing it would produce exactly the kind of invented number this project avoids. |
| `create_all` instead of migrations | Adequate while the schema is append-only. Alembic is the correct answer the moment a column changes shape. |
| No authentication | Single-analyst tool. Multi-tenant would need auth and row-level scoping before it went anywhere near real credit data. |
| EBIT taken as operating income | True for the filings here, not universally: operating income excludes non-operating items that some definitions of EBIT include. Recorded in `line_items.py`. |
