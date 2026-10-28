# Sample filings

Three real public companies, each chosen for a specific reason.

| File | Company | FY | Sector class | Model | Why it is here |
|---|---|---|---|---|---|
| `caterpillar_fy2024.json` | Caterpillar Inc. (NYSE: CAT) | 2024 | `PUBLIC_MANUFACTURER` | Altman Z (1968) | A large, profitable public **manufacturer**, the exact population the 1968 model was estimated on. Known-healthy control. |
| `infosys_fy2024.json` | Infosys Ltd (NSE: INFY) | 2024 | `NON_MANUFACTURER` | Altman Z'' | Debt-free Indian IT services. Known-healthy control for the Z'' variant, and the reason the Z'' variant exists, the 1968 model does not apply to a services firm. |
| `vodafone_idea_fy2024.json` | Vodafone Idea Ltd (NSE: IDEA) | 2024 | `NON_MANUFACTURER` | Altman Z'' | Indian telecom with **negative shareholders' equity** (−₹1,041,668m) and liabilities exceeding assets. Known-distressed case. |

## Provenance, stated honestly

These line items were **transcribed from published standardised financial
statements** on [stockanalysis.com](https://stockanalysis.com/), which sources
them from S&P Global Market Intelligence and Fiscal.ai. They were **not** parsed
out of the PDFs by this project. Each file records its `source` and each derived
figure records how it was derived.

Two figures are derived rather than transcribed, and both are flagged in the JSON:

- **Caterpillar `market_value_equity` = 177,528**, computed as the published
  FY2024 PE ratio (16.45) × net income to common (10,792). Altman Z (1968) needs
  market value of equity **at the fiscal year end**, not today's market cap, and
  a year-end market cap is not published as a line item.
- **Vodafone Idea `revenue` = 426,517** (₹42,651.7 crore), cross-checks against
  two independently published S&P ratios for the same fiscal year: PS 1.56 ×
  market cap 664,088 = 425,697, and EV 3,064,358 ÷ EV/Sales 7.20 = 425,605. Both
  land within 0.25%.

### One primary-source cross-check

Caterpillar's FY2024 total assets of **87,764** ($m) was verified directly
against the SEC's XBRL company-facts API, the authoritative extraction from the
10-K itself:

```
GET https://data.sec.gov/api/xbrl/companyconcept/CIK0000018230/us-gaap/Assets.json
  → {"end":"2024-12-31","val":87764000000,"form":"10-K","fy":2024,...}
```

`backend/scripts/fetch_sec_filing.py` is the documented path to primary source
for any US filer, and reproduces that check.

### What is missing

`vodafone_idea_fy2024.json` has **no `ebit`**. Operating income for the year is
not published as a standardised line item in the source used, and it is not
derivable from the figures available without also knowing depreciation and
amortisation. Rather than invent it, the file omits it, and the engine reports
`confidence: PARTIAL`, lists `x3` in `omitted_components`, and still returns a
decisive `DISTRESS` verdict from the four remaining terms. That behaviour is
covered by a test.

---

# V2: the second fiscal year

Piotroski, Beneish and two of Ohlson's nine terms all compare year *t* against
year *t−1*. V2 adds a companion file per company carrying FY2023 plus the FY2024
line items the new models need:

| Companion file | Adds | Source |
|---|---|---|
| `caterpillar_v2_years.json` | FY2023 in full, FY2024 supplements | **SEC XBRL company-facts, CIK 0000018230, form 10-K** — primary source |
| `infosys_v2_years.json` | FY2023 in full, FY2024 supplements | **SEC XBRL company-facts, CIK 0001067491, form 20-F (IFRS)** — primary source |
| `vodafone_idea_v2_years.json` | FY2023 in full, FY2024 supplements | stockanalysis.com (S&P Global) — same source as V1; Vodafone Idea is not an SEC filer |

**A companion never restates its base file.** The three FY2024 files are
regression fixtures for verdicts documented in the README and reproduced in CI.
Every key in a companion is either a new key for FY2024 or a figure for FY2023,
and `test_multi_year_filings.py::test_a_companion_never_overwrites_a_key_in_its_base_filing`
asserts that per company, per fiscal year. A restatement smuggled in through the
merge would change a documented verdict without appearing in any diff a reviewer
would look at.

## The cross-check that makes the FY2023 figures credible

Caterpillar's and Infosys's FY2024 line items were transcribed from *standardised
third-party statements* in V1. Pulling FY2023 from the SEC's XBRL API means the
two years come from different sources — so the first thing to check is whether
the API reproduces the V1 year.

For Caterpillar it reproduces it exactly, on seven independently tagged figures:

```
Revenues                                              64,809  = V1 revenue
CostOfRevenue                                         40,199  = V1 cogs
OperatingIncomeLoss                                   13,072  = V1 ebit
NetIncomeLossAvailableToCommonStockholdersBasic       10,792  = V1 net_income
RetainedEarningsAccumulatedDeficit                    59,352  = V1 retained_earnings
StockholdersEquityIncludingPortionAttributable...     19,494  = V1 shareholder_equity
NetCashProvidedByUsedInOperatingActivities            12,035  = V1 operating_cash_flow

and two reconciliations:
  total_debt 38,409 = ShortTermBorrowings 4,393 + current maturities 6,665 + LTD 27,351
  capex      3,215  = PP&E 1,988 + equipment leased to others 1,227
```

Caterpillar is therefore the clean multi-year case, and the one to read first.

For Infosys, eight figures tie exactly and **two do not**, both documented in the
file's `basis_notes`:

- **Cost of sales.** V1 records FY2024 cogs 13,096 / gross profit 5,466 from a
  standardised source; Infosys's own IFRS tagging reports 12,975 / 5,587 — a 121
  reclassification, almost certainly of depreciation. FY2023 uses the as-filed
  basis and FY2024 is not restated, so the year-on-year gross-margin comparison
  spans two bases and carries about 0.65 percentage points of noise. That flows
  into Piotroski test 8 and Beneish GMI, changing GMI by roughly 2% — worth
  about 0.012 on an M-Score measured against a threshold of −1.78. It does not
  move the verdict. It is still a real imperfection, and it is written down
  rather than left for someone to find.
- **EBIT.** 3,835 in V1 against 3,834 as tagged: a one-unit rounding difference.

## Three deliberate omissions

Each is a figure that could have been guessed and was not:

- **Caterpillar FY2023 `interest_expense`.** Caterpillar tags no interest-expense
  concept anywhere in its XBRL facts. `InterestPaidNet` (1,435) is *cash paid*,
  not accrued expense. Substituting one for the other would have made interest
  coverage computable for both years; instead FY2023 omits it and the trend has
  nothing to compare.
- **Infosys `capital_expenditure`, both years.** Infosys does not tag a purchase
  of PP&E line, and its investing section is dominated by treasury movements.
  Backing capex out of the PP&E roll-forward would silently fold acquisitions and
  disposals into it. The consequence is explicit and tested: **no DCF can be run
  for Infosys**, and the endpoint names the missing input rather than valuing the
  company with capital expenditure treated as zero.
- **Vodafone Idea `long_term_debt`, both years.** The source publishes total debt
  with no current/non-current split. Long-term debt is a direct input to
  Piotroski test 5 and Beneish LVGI, so **the M-Score is withheld entirely** —
  the eight-variable model refusing rather than approximating, demonstrated on
  real data instead of a constructed case.

One more worth naming: Vodafone Idea's FY2024 **EBIT is now published** by the
source (−56,304, and −62,278 for FY2023) when it was not at V1 transcription
time. It is still omitted, because the V1 file is the worked example of a
`PARTIAL`-but-decisive Altman score and is covered by a protected test. Leaving it
out is a decision, so the figures are recorded in the companion file's
`basis_notes` rather than left as an apparent gap.

## What the three companies produce with two years on file

```
Caterpillar Inc. (FY2023 → FY2024)
  Altman Z (1968) = 3.9203  SAFE        Ohlson O = -2.0767  P(distress) = 11.1%
  consensus = LOW_RISK                  F-Score = 7/9 MIXED   M-Score = -2.571, no flag
  DuPont 5-step: 0.807 × 1.023 × 0.2017 × 0.7384 × 4.5021 = ROE 55.36%
  Cash conversion cycle = 133.2 days     health 63.81
  Monte Carlo (5,000): SAFE in 100% of trials, health p5/p50/p95 = 57.9 / 64.1 / 67.8

Infosys Limited (FY2023 → FY2024)
  Altman Z″ = 8.6494  SAFE               Ohlson O = -5.2299  P(distress) = 0.5%
  consensus = LOW_RISK                   F-Score = 4/9 WEAK    M-Score = -2.3744, no flag
  Cash conversion cycle = 54.1 days      health 65.11
  Monte Carlo (5,000): SAFE in 100% of trials, health p5/p50/p95 = 58.4 / 65.5 / 71.5

Vodafone Idea Limited (FY2023 → FY2024)
  Altman Z″ = -5.9633  DISTRESS (PARTIAL) Ohlson O = 1.9061  P(distress) = 87.1%
  consensus = HIGH_RISK                   F-Score = 4 of 7 evaluated, no band
  M-Score withheld (no long-term debt split)
  Cash conversion cycle = -183.6 days     health 28.31
  Monte Carlo (5,000): DISTRESS in 100% of trials
```

**The most interesting result in the set is Infosys.** Both bankruptcy models put
it at the safe end of everything — an O-Score probability of 0.5% is about as low
as that model goes, because the company carries no conventional debt at all. And
its F-Score is 4 out of 9, the joint-weakest in the set: return on assets fell,
operating cash flow slipped below net income, shares were issued, gross margin
fell and asset turnover fell. Those are not contradictory readings. Altman and
Ohlson ask whether the company will fail; Piotroski asks whether it is getting
better or worse. A company can be in no danger whatsoever and deteriorating on
every axis Piotroski measures, and running only the distress models would have
shown none of it.

Vodafone Idea's cash conversion cycle of **−183.6 days** is the other figure worth
a second look. A negative cycle normally reads as a strength — the company is
financed by its own supply chain. Here it is 202 days of payables against 19 days
of receivables on a company with negative net worth, which is the arithmetic
signature of not paying suppliers. The number is the same either way; only the
balance sheet around it tells you which reading applies. The engine computes it
and declines to interpret it.
