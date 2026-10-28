# Market data

Month-end prices for eleven securities, 2019-01 to 2024-12 (72 observations
each). This is what the V3 market engines run on: equity volatility for the
Merton model, regression beta for the DCF, risk metrics, and the Portfolio Lab.

| Ticker | Company | Listing | Role |
|---|---|---|---|
| `CAT` | Caterpillar Inc. | NYSE, USD | credit name (sample filing) |
| `INFY` | Infosys Ltd (ADR, 1 ADR = 1 share) | NYSE, USD | credit name (sample filing) |
| `IDEA.NS` | Vodafone Idea Ltd | NSE, INR | credit name (sample filing) |
| `DE`, `AGCO`, `PCAR` | Deere, AGCO, PACCAR | NYSE / NASDAQ, USD | machinery peers |
| `ACN`, `CTSH`, `WIT`, `EPAM` | Accenture, Cognizant, Wipro, EPAM | NYSE / NASDAQ, USD | IT-services peers |
| `SPY` | SPDR S&P 500 ETF | NYSE Arca, USD | benchmark |

## Provenance

Retrieved 2026-10-20 from the Yahoo Finance chart API at monthly interval.
Regenerate with:

```bash
python backend/scripts/fetch_market_data.py
```

Two price fields, used for different things on purpose:

- **`adj_close`** — adjusted for splits *and* dividends. Every return, volatility,
  beta and covariance uses this, because a dividend is part of the return.
- **`close`** — adjusted for splits only. Market capitalisation uses this, because
  a market cap is shares outstanding times the price that actually traded.

Nothing in the application fetches prices at request time. This is a fixed,
dated file, so the tests run offline and every number can be reproduced.

## Cross-checks against the sample filings

| | From this file | From the filing | Gap |
|---|---|---|---|
| Caterpillar market cap, FYE 2024-12 | 362.76 × 477.9m shares = **173,363** | V1 `market_value_equity` **177,528** (PE × net income) | −2.3% |
| Infosys market cap, FYE 2024-03 | 17.93 × 4,139.95m shares = **74,229** | not in the filing | — |
| Vodafone Idea shares implied, FYE 2024-03 | 664,088 ÷ 13.20 = **50,310m** | ~50,120m reported after the 2023 conversion | 0.4% |

Caterpillar's V1 figure was derived from a published PE ratio because a
year-end market cap is not a standardised line item. The actual month-end close
lands 2.3% lower. The V1 file is a protected fixture and is not restated; the
Merton model uses the market-data figure and records both.

## Limits, stated

- **Monthly, not daily.** Merton implementations usually estimate equity
  volatility from a year of daily prices. Monthly sampling gives fewer
  observations, so the volatility window is 36 months rather than 12.
- **Survivorship.** The peers were chosen in 2026 and all still trade. A
  portfolio optimised on this universe has not seen a company fail.
- **Vodafone Idea is in INR.** It is used for its own Merton model only. The
  Portfolio Lab refuses a mixed-currency universe rather than silently adding
  rupee returns to dollar returns.
