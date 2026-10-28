"""The multi-year sample filings, run end to end through the V2 suite.

# roadmap: v2-10-sample-filings-multi-year

The companion files in ``data/sample_filings/`` are read directly, so a filing
edited to a figure that no longer reproduces the documented result fails here -
the same guard V1 put on the single-year Altman verdicts.
"""

from __future__ import annotations

import pytest

from tests.conftest import load_filing


@pytest.fixture
def caterpillar_v2():
    return load_filing("caterpillar_v2_years")


@pytest.fixture
def infosys_v2():
    return load_filing("infosys_v2_years")


@pytest.fixture
def vodafone_idea_v2():
    return load_filing("vodafone_idea_v2_years")


@pytest.fixture
def load_multi_year(client, load_company):
    """Load a base filing then apply its companion, as the loader script does."""

    def _load(base: dict, companion: dict) -> str:
        company_id = load_company(base)
        for statement in companion["statements"]:
            response = client.post(f"/companies/{company_id}/financial-statements", json=statement)
            assert response.status_code == 201, response.text
        return company_id

    return _load


# --- The companion files do not restate the protected base files ---------------


@pytest.mark.parametrize(
    ("base_name", "companion_name"),
    [
        ("caterpillar_fy2024", "caterpillar_v2_years"),
        ("infosys_fy2024", "infosys_v2_years"),
        ("vodafone_idea_fy2024", "vodafone_idea_v2_years"),
    ],
)
def test_a_companion_never_overwrites_a_key_in_its_base_filing(base_name, companion_name):
    """The load-bearing guard on this whole item.

    The three FY2024 files are protected regression fixtures. A companion that
    silently restated one of their line items would change documented verdicts
    through the merge rather than through an edit anyone could see in a diff.
    """
    base = load_filing(base_name)
    companion = load_filing(companion_name)
    assert companion["extends"] == f"{base_name}.json"

    base_keys: dict[int, set[str]] = {}
    for statement in base["statements"]:
        year = statement.get("fiscal_year", base["company"]["fiscal_year"])
        base_keys.setdefault(year, set()).update(statement["line_items"])

    for statement in companion["statements"]:
        year = statement["fiscal_year"]
        clash = set(statement["line_items"]) & base_keys.get(year, set())
        assert not clash, f"{companion_name} restates {sorted(clash)} for FY{year}"


@pytest.mark.parametrize(
    "companion_name",
    ["caterpillar_v2_years", "infosys_v2_years", "vodafone_idea_v2_years"],
)
def test_every_prior_year_balance_sheet_balances(companion_name):
    """Assets = liabilities + equity, checked before the API ever sees the file."""
    companion = load_filing(companion_name)
    for statement in companion["statements"]:
        items = statement["line_items"]
        if "total_assets" not in items:
            continue
        assets = items["total_assets"]
        residual = abs(assets - (items["total_liabilities"] + items["shareholder_equity"]))
        assert residual <= abs(assets) * 0.005, f"{companion_name} FY{statement['fiscal_year']}"


# --- Caterpillar: the clean multi-year case -------------------------------------


def test_caterpillar_two_years_reproduce_the_documented_suite(
    client, load_multi_year, caterpillar, caterpillar_v2
):
    company_id = load_multi_year(caterpillar, caterpillar_v2)
    expected = caterpillar_v2["expected"]

    risk = client.post(f"/companies/{company_id}/compute-bankruptcy-risk", json={}).json()
    assert risk["fiscal_year"] == 2024
    assert risk["altman_z_score"] == pytest.approx(3.9203, abs=1e-4), "V1 verdict is unchanged"
    assert risk["ohlson_o_score"] == pytest.approx(-2.0767, abs=1e-4)
    assert risk["consensus_verdict"] == expected["consensus_verdict"]
    assert risk["ohlson_omitted"] == [], "every Ohlson term computes with two years on file"

    quality = client.post(f"/companies/{company_id}/compute-earnings-quality").json()
    assert quality["prior_fiscal_year"] == 2023
    assert quality["piotroski_f_score"] == expected["piotroski_f_score"]
    assert quality["manipulation_flag"] is expected["beneish_manipulation_flag"]
    assert quality["confidence"] == "COMPLETE"

    failures = {
        key for key, entry in quality["f_score_components"].items() if entry["status"] == "FAIL"
    }
    assert failures == {"leverage_falling", "turnover_rising"}, expected["note"]


def test_caterpillar_gains_a_dupont_a_cycle_and_a_valuation(
    client, load_multi_year, caterpillar, caterpillar_v2
):
    company_id = load_multi_year(caterpillar, caterpillar_v2)
    ratios = client.post(f"/companies/{company_id}/compute-ratios").json()

    assert ratios["dupont"]["five_step"]["reconciles"] is True
    assert ratios["cash_conversion_cycle"]["basis"] == "AVERAGE_BALANCE"
    assert ratios["trend"]["years"] == [2023, 2024]

    valuation = client.post(
        f"/companies/{company_id}/compute-valuation", json={"revenue_growth": 0.03}
    ).json()
    assert valuation["confidence"] == "COMPLETE"
    assert valuation["implied_share_price"] is not None
    assert 0 < valuation["calculation_basis"]["terminal_value_share_of_ev"] < 1


# --- Infosys: the documented basis difference -----------------------------------


def test_infosys_two_years_run_but_cannot_be_valued(client, load_multi_year, infosys, infosys_v2):
    """Capital expenditure is not tagged, so FCFF has no capex term.

    The endpoint names the missing input rather than valuing the company with
    capital expenditure treated as zero.
    """
    company_id = load_multi_year(infosys, infosys_v2)

    risk = client.post(f"/companies/{company_id}/compute-bankruptcy-risk", json={}).json()
    assert risk["model"] == "Z_DOUBLE_PRIME"
    assert risk["zone"] == "SAFE"
    assert risk["ohlson_probability"] < 0.30
    assert risk["consensus_verdict"] == "LOW_RISK"

    quality = client.post(f"/companies/{company_id}/compute-earnings-quality").json()
    assert quality["beneish_m_score"] is not None
    assert quality["manipulation_flag"] is False

    valuation = client.post(f"/companies/{company_id}/compute-valuation").json()
    assert valuation["confidence"] == "UNUSABLE"
    missing = {entry["input"] for entry in valuation["calculation_basis"]["omitted"]}
    assert "capital_expenditure" in missing


def test_the_infosys_cost_of_sales_basis_note_is_in_the_file(infosys_v2):
    """A 121 reclassification between two sources, stated rather than buried.

    It is the only figure in the three companion files that spans two bases, and
    the note quantifies what it does to Beneish GMI.
    """
    note = infosys_v2["basis_notes"]["cost_of_sales"]
    assert "13,096" in note and "12,975" in note
    assert "does not move the verdict" in note
    assert "Caterpillar" in note, "the clean case is named for contrast"


# --- Vodafone Idea: distress, and a model that refuses --------------------------


def test_vodafone_idea_reaches_high_risk_with_both_year_on_year_terms(
    client, load_multi_year, vodafone_idea, vodafone_idea_v2
):
    company_id = load_multi_year(vodafone_idea, vodafone_idea_v2)
    risk = client.post(f"/companies/{company_id}/compute-bankruptcy-risk", json={}).json()

    assert risk["zone"] == "DISTRESS"
    assert risk["consensus_verdict"] == vodafone_idea_v2["expected"]["consensus_verdict"]
    # Two consecutive loss years: INTWO fires, and CHIN is now computable.
    assert risk["ohlson_components"]["intwo"]["value"] == 1.0
    assert "chin" in risk["ohlson_components"]
    assert risk["ohlson_probability"] > 0.5


def test_vodafone_idea_m_score_is_withheld_for_want_of_a_debt_split(
    client, load_multi_year, vodafone_idea, vodafone_idea_v2
):
    """The refusal policy demonstrated on real data rather than a constructed case.

    The source publishes total debt but no current/non-current split, so LVGI
    cannot be formed and the eight-variable model is refused entirely.
    """
    company_id = load_multi_year(vodafone_idea, vodafone_idea_v2)
    quality = client.post(f"/companies/{company_id}/compute-earnings-quality").json()

    assert quality["beneish_m_score"] is None
    assert quality["manipulation_flag"] is None
    beneish = {entry["component"] for entry in quality["omitted"] if entry["model"] == "beneish"}
    assert "lvgi" in beneish
    assert quality["piotroski_f_score"] is not None, "Piotroski still reports what it can"
    assert quality["f_score_band"] is None, "no band without all nine tests"


def test_the_vodafone_idea_ebit_omission_is_a_recorded_choice(vodafone_idea_v2):
    """The figure is now published. Leaving it out is a decision, so it is written down."""
    note = vodafone_idea_v2["basis_notes"]["ebit"]
    assert "-62,278" in note and "-56,304" in note
    assert "deliberate" in note
    assert "protected test" in note
