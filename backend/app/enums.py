"""Domain enumerations.

``str, Enum`` rather than ``StrEnum`` so the backend runs on Python 3.10 as well
as 3.11+. Values are always accessed via ``.value`` when serialising.
"""

from enum import Enum


class StatementType(str, Enum):
    INCOME_STATEMENT = "INCOME_STATEMENT"
    BALANCE_SHEET = "BALANCE_SHEET"
    CASH_FLOW = "CASH_FLOW"


class RatioCategory(str, Enum):
    LIQUIDITY = "LIQUIDITY"
    PROFITABILITY = "PROFITABILITY"
    LEVERAGE = "LEVERAGE"
    EFFICIENCY = "EFFICIENCY"


class AltmanModel(str, Enum):
    """The three published Altman discriminant models.

    The spec for this project named only ``Z_1968``. Shipping only that model
    would mean applying a function estimated on *publicly traded manufacturers*
    to IT-services and telecom companies, which is a misapplication Altman
    himself corrected in later papers. All three are implemented; the selection
    rule and its consequences live in ``services/altman_zscore.py``.
    """

    Z_1968 = "Z_1968"          # Altman (1968), public manufacturers
    Z_PRIME = "Z_PRIME"        # Altman (1983), private manufacturers
    Z_DOUBLE_PRIME = "Z_DOUBLE_PRIME"  # Altman (1995/2005), non-manufacturers & emerging markets


class Zone(str, Enum):
    SAFE = "SAFE"
    GREY = "GREY"
    DISTRESS = "DISTRESS"
    NOT_APPLICABLE = "NOT_APPLICABLE"   # financial-sector issuer; see altman_zscore.py


class SectorClass(str, Enum):
    """Coarse sector class, because it changes which Z model is valid.

    Deliberately not a full industry taxonomy. It has exactly the three values
    the model-selection rule needs, and one of them is a refusal.
    """

    PUBLIC_MANUFACTURER = "PUBLIC_MANUFACTURER"
    PRIVATE_MANUFACTURER = "PRIVATE_MANUFACTURER"
    NON_MANUFACTURER = "NON_MANUFACTURER"
    FINANCIAL = "FINANCIAL"


class ResultConfidence(str, Enum):
    """Whether every input the formula wants was actually supplied."""

    COMPLETE = "COMPLETE"    # all components computed from reported line items
    PARTIAL = "PARTIAL"      # one or more components omitted; see omitted_components
    UNUSABLE = "UNUSABLE"    # too little data to report a score at all


class BenchmarkBasis(str, Enum):
    PEER_SET = "PEER_SET"               # median of the peer companies loaded
    REFERENCE_TABLE = "REFERENCE_TABLE" # configured reference band
    UNAVAILABLE = "UNAVAILABLE"         # metric skipped, no comparison point


class NarrativeSource(str, Enum):
    LLM = "llm"
    TEMPLATE_FALLBACK = "template_fallback"
