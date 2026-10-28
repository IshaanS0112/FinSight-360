"""Application configuration.

Every coefficient, cutoff, and weight used anywhere in the analysis lives here
and is echoed by ``GET /methodology``. Nothing in the ratio engine, the Altman
models, or the health score reads a magic number that is not declared in this
file, and the resolved parameter set is written into the ``calculation_basis``
of every stored result.

That matters more here than in a typical CRUD service. The claim this project
makes is that the numbers are *computed*, not generated. A reader can only check
that claim if the parameters that turned line items into a score are visible
without reading the source.
"""

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Infrastructure -----------------------------------------------------
    database_url: str = "postgresql+psycopg2://finsight:finsight@localhost:5432/finsight360"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # --- LLM ----------------------------------------------------------------
    anthropic_api_key: str = ""
    anthropic_model: str = ""
    # Thinking cannot be disabled on current models and counts toward
    # max_tokens, so the ceiling is generous. Effort is the depth control.
    llm_effort: str = "medium"
    llm_timeout_seconds: float = 120.0
    llm_max_tokens: int = 16000

    # --- Altman Z (1968): public manufacturers ------------------------------
    # Edward I. Altman, "Financial Ratios, Discriminant Analysis and the
    # Prediction of Corporate Bankruptcy", Journal of Finance 23(4), 1968.
    z1968_c1: float = 1.2  # working capital / total assets
    z1968_c2: float = 1.4  # retained earnings / total assets
    z1968_c3: float = 3.3  # EBIT / total assets
    z1968_c4: float = 0.6  # market value of equity / total liabilities
    z1968_c5: float = 1.0  # sales / total assets
    z1968_safe_above: float = 2.99
    z1968_distress_below: float = 1.81

    # --- Altman Z' (1983): private manufacturers ----------------------------
    # X4 switches from market value to BOOK value of equity, and every
    # coefficient is re-estimated. Using the 1968 coefficients with book equity
    # is a common and wrong shortcut.
    zprime_c1: float = 0.717
    zprime_c2: float = 0.847
    zprime_c3: float = 3.107
    zprime_c4: float = 0.420
    zprime_c5: float = 0.998
    zprime_safe_above: float = 2.90
    zprime_distress_below: float = 1.23

    # --- Altman Z'' : non-manufacturers and emerging markets ----------------
    # Sales/assets (X5) is dropped entirely, because asset turnover varies so
    # much across service industries that it adds noise rather than signal.
    zdprime_c1: float = 6.56
    zdprime_c2: float = 3.26
    zdprime_c3: float = 6.72
    zdprime_c4: float = 1.05
    zdprime_safe_above: float = 2.60
    zdprime_distress_below: float = 1.10
    # Altman's emerging-market variant adds a +3.25 constant so the score is
    # calibrated to a US-equivalent bond rating. It shifts every score by the
    # same amount and moves companies across the cutoffs, so it is opt-in per
    # request and recorded in the result rather than silently applied.
    zdprime_emerging_market_constant: float = 3.25

    # A score this close to a cutoff is not meaningfully on either side of it.
    # Reported as borderline instead of as a confident zone.
    zone_borderline_margin: float = 0.15

    # --- Ohlson O-Score (1980), model one -----------------------------------
    # Journal of Accounting Research 18(1). A logit, so the output is a
    # probability rather than an index.
    ohlson_intercept: float = -1.32
    ohlson_size: float = -0.407  # ln(total assets); see the SIZE substitution note
    ohlson_tlta: float = 6.03  # total liabilities / total assets
    ohlson_wcta: float = -1.43  # working capital / total assets
    ohlson_clca: float = 0.0757  # current liabilities / current assets
    ohlson_oeneg: float = -1.72  # 1 if total liabilities exceed total assets
    ohlson_nita: float = -2.37  # net income / total assets
    ohlson_futl: float = -1.83  # funds from operations / total liabilities
    ohlson_intwo: float = 0.285  # 1 if net income negative in both of the last two years
    ohlson_chin: float = -0.521  # scaled change in net income
    # O > 0 is equivalent to probability > 0.5, which is Ohlson's own cutoff.
    ohlson_distress_probability: float = 0.5

    # --- Consensus verdict --------------------------------------------------
    # Asymmetric on purpose: clearing a distressed borrower costs more than
    # flagging a healthy one.
    consensus_low_risk_probability: float = 0.30
    consensus_high_risk_probability: float = 0.50

    # --- Beneish M-Score (1999) --------------------------------------------
    # Messod D. Beneish, "The Detection of Earnings Manipulation", Financial
    # Analysts Journal 55(5), 1999. Eight-variable model.
    beneish_intercept: float = -4.84
    beneish_dsri: float = 0.920
    beneish_gmi: float = 0.528
    beneish_aqi: float = 0.404
    beneish_sgi: float = 0.892
    beneish_depi: float = 0.115
    beneish_sgai: float = -0.172
    beneish_tata: float = 4.679
    beneish_lvgi: float = -0.327
    # Both are reported; neither is promoted to "the" threshold.
    beneish_threshold: float = -1.78
    beneish_strict_threshold: float = -2.22

    # --- Financial health score --------------------------------------------
    # Weights must sum to 1.0; enforced below.
    health_w_profitability: float = 0.35
    health_w_liquidity: float = 0.25
    health_w_leverage: float = 0.20
    health_w_efficiency: float = 0.20

    # Each component is scored by how far the company sits from its benchmark,
    # mapped onto 0-100 with 50 = exactly at benchmark. A company at 2x the
    # benchmark scores 50 + 50*min(1, 1.0/full_credit_ratio).
    #
    # full_credit_ratio = 1.0 means "twice the benchmark earns 100". Without a
    # cap, one freak ratio (a quick ratio of 30 because the company just raised
    # equity) would drag the whole composite upward and the score would stop
    # meaning anything.
    health_full_credit_ratio: float = 1.0
    health_min_metrics_per_component: int = 1

    # --- DCF defaults -------------------------------------------------------
    # Defaults, not constants: every one is overridable per request and echoed
    # back in the stored assumptions.
    dcf_projection_years: int = 5
    dcf_risk_free_rate: float = 0.045  # ~10-year sovereign yield; set it to your own
    dcf_equity_risk_premium: float = 0.055  # Rm - Rf
    # Beta is an input, never a measurement: no price history is held.
    dcf_default_beta: float = 1.0
    dcf_tax_rate: float = 0.25
    dcf_terminal_growth: float = 0.025  # below long-run nominal GDP growth, on purpose
    # Gordon divides by (WACC - g); refused once the gap closes below this.
    dcf_min_wacc_terminal_spread: float = 0.01

    # --- Scenario simulator -------------------------------------------------
    scenario_default_trials: int = 5000
    scenario_max_trials: int = 20000
    scenario_default_seed: int = 20240101

    # --- Market data (V3) ---------------------------------------------------
    # Every market statistic uses data up to the fiscal year end only: a FY2024
    # analysis never sees a FY2025 price.
    market_min_observations: int = 24
    # Approximate average 3-month US Treasury bill yield over 2019-2024, for
    # historical Sharpe and Sortino ratios. Set your own.
    market_risk_free_rate: float = 0.024
    market_var_confidence: float = 0.95
    market_benchmark_ticker: str = "SPY"
    market_beta_window_months: int = 60

    # --- Merton distance-to-default (V3) -----------------------------------
    # 36 monthly returns because monthly sampling gives fewer points than the
    # year of daily prices most implementations use.
    merton_volatility_months: int = 36
    merton_min_volatility_months: int = 12
    merton_horizon_years: float = 1.0
    # Approximate one-year government yields, by listing currency.
    merton_risk_free_rates: dict[str, float] = {"USD": 0.045, "INR": 0.070}
    # Bands for comparing the market PD against the accounting consensus.
    merton_low_pd: float = 0.005
    merton_high_pd: float = 0.05

    # --- Portfolio Lab (V3) -------------------------------------------------
    portfolio_min_observations: int = 36
    portfolio_frontier_points: int = 25
    portfolio_random_portfolios: int = 2000
    portfolio_ema_span_months: int = 24
    portfolio_seed: int = 20241231

    # --- Research agents (V3) ----------------------------------------------
    # A number in agent prose must match a number in its context within this
    # relative tolerance, or the sentence carrying it is removed.
    research_number_tolerance: float = 0.01
    research_parallel_workers: int = 4

    # --- Benchmarks ---------------------------------------------------------
    # Peer-derived benchmarks need enough peers to mean anything. Below this
    # count the engine falls back to the reference table and records which
    # basis it used.
    benchmark_min_peers: int = 3
    # Path to a JSON table of your own sourced reference bands. Empty means use
    # the built-in ILLUSTRATIVE placeholders; see services/benchmarks.py.
    reference_benchmarks_path: str = ""

    # --- Data quality -------------------------------------------------------
    # Assets - (liabilities + equity) must be within this fraction of assets or
    # the upload is rejected. A balance sheet that does not balance means a
    # transcription error, and every ratio built on it would be confidently
    # wrong. 0.5% absorbs rounding in millions-scale filings.
    balance_sheet_tolerance_pct: float = 0.5

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def health_weights(self) -> dict[str, float]:
        return {
            "profitability": self.health_w_profitability,
            "liquidity": self.health_w_liquidity,
            "leverage": self.health_w_leverage,
            "efficiency": self.health_w_efficiency,
        }

    def altman_coefficients(self) -> dict[str, dict[str, float]]:
        return {
            "Z_1968": {
                "x1": self.z1968_c1,
                "x2": self.z1968_c2,
                "x3": self.z1968_c3,
                "x4": self.z1968_c4,
                "x5": self.z1968_c5,
            },
            "Z_PRIME": {
                "x1": self.zprime_c1,
                "x2": self.zprime_c2,
                "x3": self.zprime_c3,
                "x4": self.zprime_c4,
                "x5": self.zprime_c5,
            },
            "Z_DOUBLE_PRIME": {
                "x1": self.zdprime_c1,
                "x2": self.zdprime_c2,
                "x3": self.zdprime_c3,
                "x4": self.zdprime_c4,
            },
        }

    def ohlson_coefficients(self) -> dict[str, float]:
        return {
            "intercept": self.ohlson_intercept,
            "size": self.ohlson_size,
            "tlta": self.ohlson_tlta,
            "wcta": self.ohlson_wcta,
            "clca": self.ohlson_clca,
            "oeneg": self.ohlson_oeneg,
            "nita": self.ohlson_nita,
            "futl": self.ohlson_futl,
            "intwo": self.ohlson_intwo,
            "chin": self.ohlson_chin,
        }

    def beneish_coefficients(self) -> dict[str, float]:
        return {
            "intercept": self.beneish_intercept,
            "dsri": self.beneish_dsri,
            "gmi": self.beneish_gmi,
            "aqi": self.beneish_aqi,
            "sgi": self.beneish_sgi,
            "depi": self.beneish_depi,
            "sgai": self.beneish_sgai,
            "tata": self.beneish_tata,
            "lvgi": self.beneish_lvgi,
        }

    def altman_cutoffs(self) -> dict[str, dict[str, float]]:
        return {
            "Z_1968": {
                "safe_above": self.z1968_safe_above,
                "distress_below": self.z1968_distress_below,
            },
            "Z_PRIME": {
                "safe_above": self.zprime_safe_above,
                "distress_below": self.zprime_distress_below,
            },
            "Z_DOUBLE_PRIME": {
                "safe_above": self.zdprime_safe_above,
                "distress_below": self.zdprime_distress_below,
            },
        }

    @model_validator(mode="after")
    def _check_invariants(self) -> "Settings":
        weight_sum = (
            self.health_w_profitability
            + self.health_w_liquidity
            + self.health_w_leverage
            + self.health_w_efficiency
        )
        if abs(weight_sum - 1.0) > 1e-6:
            raise ValueError(
                f"Health score weights must sum to 1.0, got {weight_sum:.4f}. An "
                "unnormalised weight vector silently rescales every score, so the "
                "0-100 range would stop meaning what the docs say it means."
            )

        for name, safe, distress in (
            ("Z_1968", self.z1968_safe_above, self.z1968_distress_below),
            ("Z_PRIME", self.zprime_safe_above, self.zprime_distress_below),
            ("Z_DOUBLE_PRIME", self.zdprime_safe_above, self.zdprime_distress_below),
        ):
            if distress >= safe:
                raise ValueError(f"{name}: distress cutoff must sit below the safe cutoff")

        if not 0 < self.consensus_low_risk_probability <= self.consensus_high_risk_probability < 1:
            raise ValueError(
                "consensus_low_risk_probability must be positive, no greater than "
                "consensus_high_risk_probability, and both below 1. Inverting them "
                "would make LOW_RISK and HIGH_RISK overlap, and every company would "
                "resolve to whichever branch happened to be tested first."
            )
        if self.beneish_strict_threshold >= self.beneish_threshold:
            raise ValueError(
                "beneish_strict_threshold must sit below beneish_threshold; it is the "
                "more conservative of the two cutoffs, not the looser one."
            )
        if not 0 < self.dcf_projection_years <= 20:
            raise ValueError(
                "dcf_projection_years must be between 1 and 20. Beyond twenty years the "
                "explicit forecast is a terminal value wearing a schedule."
            )
        if self.dcf_min_wacc_terminal_spread <= 0:
            raise ValueError(
                "dcf_min_wacc_terminal_spread must be positive; it is what stops the "
                "Gordon denominator from reaching zero."
            )
        if not 0 <= self.dcf_tax_rate < 1:
            raise ValueError("dcf_tax_rate must be a fraction in [0, 1)")
        if not 0 < self.scenario_default_trials <= self.scenario_max_trials:
            raise ValueError("scenario_default_trials must be positive and within the maximum")
        if not 0 < self.market_var_confidence < 1:
            raise ValueError("market_var_confidence must be a probability in (0, 1)")
        if not 0 < self.merton_low_pd < self.merton_high_pd < 1:
            raise ValueError("merton_low_pd must sit below merton_high_pd, both in (0, 1)")
        if self.merton_min_volatility_months < 6:
            raise ValueError("merton_min_volatility_months below 6 is not a volatility estimate")
        if self.health_full_credit_ratio <= 0:
            raise ValueError("health_full_credit_ratio must be positive")
        if not 0 < self.balance_sheet_tolerance_pct < 100:
            raise ValueError("balance_sheet_tolerance_pct must be between 0 and 100")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
