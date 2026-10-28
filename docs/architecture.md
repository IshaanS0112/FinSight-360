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
                                                                    LLM API
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

---
---

# V2: multiple models, and what to do when they disagree

V1's argument was that one named academic model, applied to the population it
was actually estimated on, beats one applied to everything. V2's argument is a
step up from that: **models disagree, the disagreement is information, and a
tool that averages it away is destroying its most useful output.**

```
React "Workpaper" UI ◄──► FastAPI ──► PostgreSQL 16
                              │
   ┌──────────────┬───────────┼────────────┬──────────────┬──────────────┐
   ▼              ▼           ▼            ▼              ▼              ▼
Ratio engine  Bankruptcy   Earnings    Health score   DCF-lite      Peer
(+ DuPont,    risk suite   quality     (weighted,     (FCFF, CAPM,  benchmarking
 CCC, trend)  (Z/Z'/Z'' +  (Piotroski   percentile-    Gordon)      (z → percentile)
              Ohlson +      F + Beneish  backed)
              consensus)    M)
   └──────────────┴───────────┼────────────┴──────────────┴──────────────┘
                              ▼
              Scenario simulator (Monte Carlo over the above)
                              ▼
              Insights generator (structured context → LLM)
                              ▼
                   LLM API  +  constrained follow-up Q&A
```

Everything above the insights generator is deterministic, exact-formula code.
The Monte Carlo layer adds no score: it re-runs the same formulas thousands of
times under sampled inputs, which is the honest way to answer "how much does
this verdict depend on assumptions nobody can observe."

---

## What's real vs simulated, revisited

| Layer | Status |
|---|---|
| Ratio arithmetic, Altman Z / Z′ / Z″ | Real, unchanged from V1. Those modules were not edited. |
| DuPont, cash conversion cycle | Real. Definitional identities over reported line items. |
| **Ohlson O-Score** | Real, published logit, with **one documented substitution** — see below. |
| **Consensus verdict** | Project-defined *rule*, over two real models. The thresholds are a judgement and are declared in `config.py` and `/methodology`. |
| **Piotroski F-Score** | Real, nine published tests, with **one documented denominator deviation** — see below. |
| **Beneish M-Score** | Real, the published eight-variable model and both cited thresholds. |
| **DCF-lite** | Real but ordinary: standard textbook construction, labelled `"STANDARD TEXTBOOK CONSTRUCTION, not a proprietary method"` in `/methodology`. |
| **Peer percentile** | Real statistics, **small sample** — see the honesty section below. |
| **Monte Carlo** | Real re-runs of the modules above. The *perturbation model* is a simplification and says so, including which direction it biases. |
| Sample filings | Real. Caterpillar and Infosys now from SEC XBRL primary source across two years. |
| Health composite | Still project-defined, still labelled as such everywhere. |

**Simulated: nothing.** There is still no synthetic data generator. The scenario
simulator samples from distributions the *caller* specifies and reports the
spread; it does not invent data and it does not persist a perturbed company.

---

## Three documented deviations from published models

Every one of these is a place where a naive implementation would quietly claim
more than it has. They are listed together so a reviewer can find all of them in
one place, and each is also carried in the `calculation_basis` of every result
that depends on it and echoed by `GET /methodology`.

### 1. Ohlson's SIZE term

Ohlson's published SIZE term is:

```
SIZE = ln(total assets / GNP price-level index)
```

The deflator is a historical U.S. GNP implicit price index. It is not
practically sourceable for a general-purpose tool and has no meaning at all for
a company reporting in rupees. This project substitutes:

```
SIZE = ln(total assets)
```

which is the standard modern reproduction and what most published replications
use. The effect is a constant shift of `−0.407 × ln(deflator)` on every O-Score
for a given year, so **relative ordering is preserved and the absolute
probability is not.** This is a real departure from the 1980 paper and it is not
presented as the paper as published.

### 2. Piotroski's ROA denominator

Piotroski's paper uses income before extraordinary items over **beginning-of-year**
total assets. This project uses net income over **ending** total assets, matching
the ratio engine so the same ROA appears in two places rather than two different
ROAs appearing under one name. The difference is a denominator one year older. It
cannot change the sign of test 1, and it moves test 3 only where the two years'
asset bases differ by more than the change in return.

### 3. Vodafone Idea's EBIT, still omitted

The source now publishes operating income for both years (−62,278 for FY2023,
−56,304 for FY2024) when it did not at V1 transcription time. It is still left
out, because the FY2024 file is the project's worked example of a
`PARTIAL`-but-decisive Altman score and is covered by a protected test. The
figures are recorded in the companion file's `basis_notes` so the omission is a
documented decision rather than a gap.

---

## Two opposite refusal policies, and why

The most interesting design decision in V2 is that Beneish and Altman handle a
missing input in **opposite** ways, on purpose.

**Altman reports a partial sum.** Its terms are ratios scaled by total assets,
mostly small, and dropping one removes a contribution a reader can reason about.
Vodafone Idea scores −5.96 on four of five terms against a distress cutoff of
1.10; no plausible X3 closes a seven-point gap, and the result says `PARTIAL` and
lists what is missing.

**Beneish reports nothing at all.** Its terms are ratio-of-ratios that sit near
1.0 by construction — a company whose receivables did not move has DSRI = 1.0,
contributing 0.920 to M. Dropping that term does not remove a small
contribution; it removes 0.920 from a score compared against a threshold of
−1.78, a fifth of the way across the entire decision range. And the common
workaround is worse: substituting the neutral value 1.0 asserts that nothing
changed year over year, which is precisely the claim the model exists to test.

**Piotroski sits between them.** A partial score is reported as the sum of the
tests that could be evaluated, but `f_score_band` stays null, because the
8-9 / 5-7 / 0-4 reading is calibrated on all nine tests. Scoring 3-out-of-3
against a nine-point band would report a strong company as weak.

---

## The consensus verdict

```
Altman zone SAFE      AND Ohlson probability < 0.30  →  LOW_RISK
Altman zone DISTRESS  AND Ohlson probability > 0.50  →  HIGH_RISK
either model produced no opinion at all              →  INDETERMINATE
everything else                                      →  MIXED_SIGNAL
```

Three things about this rule are deliberate:

**The bands are asymmetric.** Calling something low risk needs Ohlson comfortably
below its own cutoff; calling it high risk only needs Ohlson past it. Wrongly
clearing a distressed borrower costs more than wrongly flagging a healthy one.

**`INDETERMINATE` is distinct from `MIXED_SIGNAL`.** A bank gets no Altman zone at
all, so calling the surviving model a "consensus" would be one model wearing the
word. Ohlson refuses financial-sector issuers too, for the same reason Altman
does: TLTA carries the largest positive coefficient in the model, and for a bank
a TLTA near 1 is the business model rather than a terminal signal.

**`MIXED_SIGNAL` is an output.** A 1968 discriminant function fitted on 66
manufacturers and a 1980 logit fitted on 2,163 industrial firms reading the same
balance sheet differently is information. Which to believe depends on how much
the company resembles each estimation sample, and that is a judgement for the
reader, not a number to average.

### A partial logit cannot be read directionally

One consequence of Ohlson being a logit rather than a linear score: when a term
is omitted, "the score is a partial sum" does not tell a reader which way the
probability moved, because the logistic transform is non-linear. So where the
missing term is **binary** — `OENEG` or `INTWO` — the result carries
`probability_bounds`, the probability at each of the term's two possible values.
That is strictly more information than an omission notice.

---

## The DCF, and the three places it refuses

V1 declined to build a DCF and the reasoning was right: rushing one produces
exactly the invented number this project exists to avoid. What changed is that
the ratio and risk layers underneath are now solid enough to carry one.

The rule the module is built around is that **no assumption is ever a hidden
constant.** Every input either comes from a reported line item or appears by name
in `assumptions`, is stored with the result, and is returned by the API.

Three refusals, each of which a naive implementation reports as a number:

1. **Terminal growth within 1% of WACC.** Gordon divides by `WACC − g`. As the gap
   closes the value diverges to infinity, and past it the value turns *negative*
   while still looking like a price per share. Refused, with the reason.
2. **Negative base-year EBIT.** Computed and returned but flagged `UNUSABLE`: every
   projected FCFF inherits the sign and the terminal value is a negative
   perpetuity, so the output is an arithmetic consequence of one assumption
   rather than a valuation.
3. **No share count.** Enterprise and equity value stand; the per-share figure is
   withheld rather than divided by a share count guessed from elsewhere.

`compute-valuation` returns **200 with `confidence: UNUSABLE`** for the first of
these rather than a 422, because an analyst dragging a slider past WACC should
see *why* the number vanished, not an error code.

**Beta is an input, not a measurement.** It defaults to 1.0. Computing a real beta
needs a price history this tool does not hold, and running that regression on
data it does not have would be the one genuinely fabricated number in the
project.

**The terminal value's share of enterprise value is reported as a diagnostic.**
Above roughly 75%, a DCF is a perpetuity assumption with a five-year schedule
attached to it, and that is the first thing a reviewer should see. Caterpillar's
comes out at 75.8%.

---

## The peer percentile, and what it is not

V1 left `peer_percentile` null and the README said why: a percentile over four
companies presented as an industry position is a claim the dataset cannot
support. V2 gives the field a method. It does **not** give it a bigger sample, so
most of the new code is about not overclaiming.

```
company_z  = (company_ratio − peer_mean) / peer_stdev      [sample stdev, n−1]
percentile = Φ(company_z) × 100
```

Four guards, three of which the specification did not ask for:

- **Direction is normalised.** Debt-to-equity is the one lower-is-better ratio in
  the set, so its z is negated. Without that a conservatively financed company
  ranks in the bottom decile on leverage and a radar chart reads it as a weakness.
- **The empirical rank is returned beside every percentile** — "3rd of 6" — and
  named in the interpretation limit as the figure to read *first*. It assumes
  nothing about the shape of the distribution; Φ(z) assumes normality, which five
  companies cannot establish.
- **`|z| > 2` sets an `extrapolated` flag.** Caterpillar's ROE against machinery
  peers is four standard deviations out, where Φ returns essentially the 100th
  percentile: a real number and a meaningless one.
- **Zero peer variance yields no z-score** rather than an infinite one, and the
  rank is still computed.

`health_score.py` was not edited. The composite, its weights and its
normalisation are exactly V1's; the pipeline computes the percentile beside it
and stores it, with the interpretation limit travelling in `calculation_basis`
rather than sitting in a README next to a number on a dashboard.

---

## The scenario simulator, and the bug that proves the point

The simulator adds no model. It re-runs the same Altman, Ohlson, health-score and
DCF code with perturbed inputs — 5,000 trials in about 0.3 seconds, so it fits
inside a request.

**The perturbation model, stated in full**, because a simulator that hides what it
perturbs is a random number generator with good manners:

```
revenue      ×= (1 + sampled revenue_growth)
EBIT         =  revenue × (base operating margin + sampled margin_shift)
net income   += ΔEBIT
retained earnings, shareholders' equity  += Δnet income
wacc_shift   applies to the DCF discount rate only

total assets, total liabilities and working capital are HELD FIXED
```

That last line is a real simplification with a **direction**: in a bad year a
company's asset base and current liabilities move too, so the reported Altman and
Ohlson distributions are *tighter* than reality. The result says so rather than
implying a full balance-sheet simulation.

**The seed is stored, not logged.** A distribution that cannot be regenerated
exactly is an anecdote. Percentiles are empirical order statistics of the trials
actually run; nothing is fitted to the output, because fitting a normal to a
non-linear model's output would reintroduce the exact assumption the simulation
exists to avoid.

**`distress_probability` is a sensitivity measure, not a probability of default.**
It is the share of trials landing in the Altman distress zone under the specified
shocks, and it says nothing about their real-world likelihood.

### The bug

An early draft passed `industry=None` into the health score for each trial, so
every trial benchmarked against the generic reference row while the point
estimate used the industry row. The simulated median landed several points away
from the number it was supposed to be stressing, **and nothing in the output
looked wrong** — the distribution was smooth, plausible and centred on the wrong
value. It was caught by comparing the simulated median against the point estimate
on real filings, and there is now a test that asserts the median brackets it.
That property is what makes this a stress test *of* the model rather than a
stress test of a similar model, and it is worth a test of its own.

---

## Validation across two fiscal years

Every figure below is reproduced by tests that read `data/sample_filings/*.json`
directly, so a filing edited to a value that no longer produces the documented
result fails CI.

| Company | Altman | Ohlson | Consensus | F-Score | M-Score |
|---|---|---|---|---|---|
| Caterpillar Inc. | Z = **3.9203** SAFE | O = −2.0767, **11.1%** | **LOW_RISK** | **7/9** MIXED | **−2.571**, no flag |
| Infosys Ltd | Z″ = **8.6494** SAFE | O = −5.2299, **0.5%** | **LOW_RISK** | **4/9** WEAK | **−2.3744**, no flag |
| Vodafone Idea Ltd | Z″ = **−5.9633** DISTRESS | O = 1.9061, **87.1%** | **HIGH_RISK** | **4 of 7** evaluated | **withheld** |

**The most interesting row is Infosys.** Both bankruptcy models put it at the safe
extreme — an O-Score probability of 0.5% is about as low as that model goes,
because the company carries no conventional debt at all — and its F-Score is the
joint-weakest in the set: return on assets fell, operating cash flow slipped
below net income, shares were issued, gross margin fell and asset turnover fell.

Those are not contradictory readings. Altman and Ohlson ask whether the company
will fail. Piotroski asks whether it is getting better or worse. A company can be
in no danger whatsoever and deteriorating on every axis Piotroski measures, and
running only the distress models would have shown none of it. That is the whole
argument for the earnings-quality layer, and it happens to be demonstrated by the
healthiest company in the sample set rather than by a constructed example.

**Vodafone Idea's cash conversion cycle of −183.6 days** is the other figure worth
a second look. A negative cycle normally reads as a strength: the company is
financed by its own supply chain. Here it is 202 days of payables against 19 days
of receivables on a company with negative net worth, which is the arithmetic
signature of not paying suppliers. The number is identical either way; only the
balance sheet around it tells you which reading applies. The engine computes it
and declines to interpret it.

---

## Schema note

`create_all` still builds the schema on a fresh database, and that is now past
the point where it is adequate: the V2 migration changes `financial_statements`
to carry a `NOT NULL fiscal_year`, which `create_all` will not do to a table that
already exists. `docs/schema.sql` carries the explicit `ALTER` statements an
existing deployment needs. **Alembic is the correct answer and is the top of the
backlog.**

One naming note: the V2 specification calls the health-score percentile column
`industry_percentile`. V1 shipped it as `financial_health_scores.peer_percentile`
and that name is kept, because renaming a live column to match a document is
churn. Same field, and V2 finally populates it.


## V3: market data, Portfolio Lab and the research memo

```
 data/market_data/prices_monthly.json ──► securities, market_prices
                                              │
              ┌───────────────────────────────┼─────────────────────────────┐
              ▼                               ▼                             ▼
   market_risk (per company)        portfolio_runs (cross-company)   research_memos (per company)
   Merton DD, naive DD, beta,       six optimisers, frontier,        grounding → 4 specialists →
   VaR, drawdown, market view       component VaR, allocation        curator → disagreements → editor
```

**New tables only.** V3 adds `securities`, `market_prices`, `company_listings`,
`market_risk`, `portfolio_runs` and `research_memos`, and no column to an existing
table, so `create_all` upgrades a V2 database without a migration.

**No look-ahead.** Every market statistic for a company is computed on prices dated
on or before its fiscal year end, taken from `company_listings.fiscal_year_end_month`.

**Merton.** Asset value and asset volatility are solved from the two Merton (1974)
equations with SciPy's `root`, residuals scaled by equity value. The default point
is short-term debt plus half of long-term debt (KMV), falling back to total debt when
the filing has no split. The Bharath and Shumway (2008) closed form is reported beside
it, because the two diverge most when the trailing stock return is extreme.

**Market view.** The market-implied probability of default is banded (low below 0.5%,
high above 5%) and compared with the accounting consensus: `CONFIRMS`,
`CONTRADICTS`, `PARTIAL` or `UNAVAILABLE`.

**Portfolio Lab.** Expected returns and covariance are estimated once, then every
optimiser runs on the same estimates, so differences between methods are the methods.
Long-only weights come from SLSQP; HRP follows López de Prado (2016). A credit overlay
reads the stored consensus verdict of any company linked to a ticker. Mixed currencies,
short histories and caps that cannot reach 100% are refused, not computed.

**Research memo.** Each specialist sees only its own slice of the stored context. The
curator keeps a sentence only if every figure in it matches a figure in that slice
(within 1% or the sentence's own rounding). Disagreements are found by code, and the
editor sees only curated sections. With no model configured, every node runs on a
deterministic template and the trace says so.
