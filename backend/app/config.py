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
    anthropic_model: str = "claude-sonnet-4-5"
    llm_timeout_seconds: float = 30.0
    llm_max_tokens: int = 1600

    # --- Altman Z (1968): public manufacturers ------------------------------
    # Edward I. Altman, "Financial Ratios, Discriminant Analysis and the
    # Prediction of Corporate Bankruptcy", Journal of Finance 23(4), 1968.
    z1968_c1: float = 1.2    # working capital / total assets
    z1968_c2: float = 1.4    # retained earnings / total assets
    z1968_c3: float = 3.3    # EBIT / total assets
    z1968_c4: float = 0.6    # market value of equity / total liabilities
    z1968_c5: float = 1.0    # sales / total assets
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
                "x1": self.z1968_c1, "x2": self.z1968_c2, "x3": self.z1968_c3,
                "x4": self.z1968_c4, "x5": self.z1968_c5,
            },
            "Z_PRIME": {
                "x1": self.zprime_c1, "x2": self.zprime_c2, "x3": self.zprime_c3,
                "x4": self.zprime_c4, "x5": self.zprime_c5,
            },
            "Z_DOUBLE_PRIME": {
                "x1": self.zdprime_c1, "x2": self.zdprime_c2, "x3": self.zdprime_c3,
                "x4": self.zdprime_c4,
            },
        }

    def altman_cutoffs(self) -> dict[str, dict[str, float]]:
        return {
            "Z_1968": {"safe_above": self.z1968_safe_above, "distress_below": self.z1968_distress_below},
            "Z_PRIME": {"safe_above": self.zprime_safe_above, "distress_below": self.zprime_distress_below},
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

        if self.health_full_credit_ratio <= 0:
            raise ValueError("health_full_credit_ratio must be positive")
        if not 0 < self.balance_sheet_tolerance_pct < 100:
            raise ValueError("balance_sheet_tolerance_pct must be between 0 and 100")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
