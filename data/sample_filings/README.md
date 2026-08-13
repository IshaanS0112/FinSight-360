# Sample filings

Three real public companies, each chosen for a specific reason.

| File | Company | FY | Sector class | Model | Why it is here |
|---|---|---|---|---|---|
| `caterpillar_fy2024.json` | Caterpillar Inc. (NYSE: CAT) | 2024 | `PUBLIC_MANUFACTURER` | Altman Z (1968) | A large, profitable public **manufacturer** — the exact population the 1968 model was estimated on. Known-healthy control. |
| `infosys_fy2024.json` | Infosys Ltd (NSE: INFY) | 2024 | `NON_MANUFACTURER` | Altman Z'' | Debt-free Indian IT services. Known-healthy control for the Z'' variant, and the reason the Z'' variant exists — the 1968 model does not apply to a services firm. |
| `vodafone_idea_fy2024.json` | Vodafone Idea Ltd (NSE: IDEA) | 2024 | `NON_MANUFACTURER` | Altman Z'' | Indian telecom with **negative shareholders' equity** (−₹1,041,668m) and liabilities exceeding assets. Known-distressed case. |

## Provenance, stated honestly

These line items were **transcribed from published standardised financial
statements** on [stockanalysis.com](https://stockanalysis.com/), which sources
them from S&P Global Market Intelligence and Fiscal.ai. They were **not** parsed
out of the PDFs by this project. Each file records its `source` and each derived
figure records how it was derived.

Two figures are derived rather than transcribed, and both are flagged in the JSON:

- **Caterpillar `market_value_equity` = 177,528** — computed as the published
  FY2024 PE ratio (16.45) × net income to common (10,792). Altman Z (1968) needs
  market value of equity **at the fiscal year end**, not today's market cap, and
  a year-end market cap is not published as a line item.
- **Vodafone Idea `revenue` = 426,517** (₹42,651.7 crore) — cross-checks against
  two independently published S&P ratios for the same fiscal year: PS 1.56 ×
  market cap 664,088 = 425,697, and EV 3,064,358 ÷ EV/Sales 7.20 = 425,605. Both
  land within 0.25%.

### One primary-source cross-check

Caterpillar's FY2024 total assets of **87,764** ($m) was verified directly
against the SEC's XBRL company-facts API — the authoritative extraction from the
10-K itself:

```
GET https://data.sec.gov/api/xbrl/companyconcept/CIK0000018230/us-gaap/Assets.json
  → {"end":"2024-12-31","val":87764000000,"form":"10-K","fy":2024,...}
```

`backend/scripts/fetch_sec_filing.py` is the documented path to primary source
for any US filer, and reproduces that check.

### What is deliberately missing

`vodafone_idea_fy2024.json` has **no `ebit`**. Operating income for the year is
not published as a standardised line item in the source used, and it is not
derivable from the figures available without also knowing depreciation and
amortisation. Rather than invent it, the file omits it — and the engine reports
`confidence: PARTIAL`, lists `x3` in `omitted_components`, and still returns a
decisive `DISTRESS` verdict from the four remaining terms. That behaviour is
covered by a test.
