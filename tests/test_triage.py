"""Tests for the Tier-2 triage checks.

Triage emits disqualifying FACTS and a go/no-go. It must never emit a price,
a buy zone or a verdict — an unaudited number gets used and looks like rigour.
"""
import importlib.util
import os

import pytest

_ROOT = os.path.join(os.path.dirname(__file__), "..")
_SPEC = importlib.util.spec_from_file_location(
    "triage", os.path.join(_ROOT, "scripts", "triage.py"))
triage = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(triage)


# --- check 1: owner yield against the hurdle, not forward P/E ---------------

def test_flags_an_owner_yield_below_the_hurdle():
    # IQV: 3.8% against an 8-10% local cost of equity
    flag = triage.owner_yield_check(3.8, hurdle_low=8.0)
    assert flag.failed is True
    assert "3.8" in flag.detail and "8.0" in flag.detail


def test_passes_an_owner_yield_above_the_hurdle():
    assert triage.owner_yield_check(10.6, hurdle_low=8.0).failed is False


def test_reports_a_missing_owner_yield_rather_than_passing_it():
    flag = triage.owner_yield_check(None, hurdle_low=8.0)
    assert flag.failed is True
    assert "not available" in flag.detail.lower()


# --- check 2: purchase accounting inflating "adjusted" earnings -------------

def test_flags_amortisation_large_against_net_income():
    # IQV: ~$984M of intangible amortisation against $1.38B of net income
    flag = triage.amortisation_check(984e6, 1.38e9)
    assert flag.failed is True
    assert "71" in flag.detail  # 71% of net income


def test_does_not_flag_immaterial_amortisation():
    # OTIS: $62M against $1.52B
    assert triage.amortisation_check(62e6, 1.52e9).failed is False


# --- check 3: a one-off sitting inside the trailing window ------------------

def test_flags_ttm_net_income_spiking_above_the_prior_year():
    # NXPI: TTM $2.98B against FY2025 $2.02B — the $627M MEMS gain
    flag = triage.ttm_spike_check(2.98e9, 2.02e9)
    assert flag.failed is True
    assert "1.4" in flag.detail or "48" in flag.detail


def test_does_not_flag_ordinary_year_on_year_growth():
    assert triage.ttm_spike_check(1.52e9, 1.38e9).failed is False


# --- check 4: revenue growing while earnings do not ------------------------

def test_flags_revenue_growth_without_earnings_growth():
    # IQV: revenue $15.0B -> $16.3B, net income $1.36B -> $1.36B
    flag = triage.stagnation_check([15.0e9, 15.4e9, 16.3e9],
                                   [1.36e9, 1.373e9, 1.360e9])
    assert flag.failed is True
    assert "revenue" in flag.detail.lower()


def test_does_not_flag_when_earnings_track_revenue():
    assert triage.stagnation_check([10e9, 11e9, 12e9],
                                   [1.0e9, 1.1e9, 1.2e9]).failed is False


def test_does_not_flag_when_revenue_is_flat_too():
    # OTIS: flat revenue and flat earnings is a different problem, not this one
    assert triage.stagnation_check([14.2e9, 14.3e9, 14.4e9],
                                   [1.41e9, 1.65e9, 1.38e9]).failed is False


# --- check 5: leverage ------------------------------------------------------

def test_flags_net_leverage_above_the_threshold():
    # IQV: net debt $13.74B against adjusted EBITDA $3.79B
    flag = triage.leverage_check(13.74e9, 3.79e9)
    assert flag.failed is True
    assert "3.6" in flag.detail


def test_does_not_flag_a_net_cash_business():
    # GTT.PA: net cash
    assert triage.leverage_check(-0.35e9, 0.5e9).failed is False


# --- the decision ----------------------------------------------------------

def test_a_clean_name_proceeds():
    d = triage.decide([triage.Flag("owner yield", False, ""),
                       triage.Flag("leverage", False, "")])
    assert d.proceed is True


def test_a_flagged_name_needs_a_stated_reason_rather_than_auto_rejection():
    d = triage.decide([triage.Flag("owner yield", True, "3.8% below 8.0%")])
    assert d.proceed is False
    assert "reason" in d.summary.lower()
    assert "reject" not in d.summary.lower(), "triage advises, it does not reject"


def test_the_decision_never_contains_a_price_or_a_verdict():
    d = triage.decide([triage.Flag("owner yield", True, "3.8% below 8.0%"),
                       triage.Flag("leverage", True, "3.6x")])
    text = (d.summary + " ".join(d.reasons)).lower()
    for banned in ("buy zone", "fair value", "target price", "$", "verdict",
                   "buy", "sell", "wait", "pass"):
        assert banned not in text, f"triage must not emit '{banned}'"


# --- parsing the physics block, and only that block ------------------------

DOSSIER = """
    REVENUE TREND: $4.9B -> $5.0B -> $5.3B

        --- FINANCIAL PHYSICS (BCO) ---
        | YEAR |  ROIC   | MARGIN  | NET INCOME | FREE CASH FLOW | OWNER EARN* |
        |------|---------|---------|------------|----------------|-------------|
        | TTM  |   14.2% |    3.3% | $  0.18B | $  0.39B | $  0.24B |
| 2025 |   14.9% |    3.8% | $  0.20B | $  0.44B | $  0.35B |
| 2024 |   13.0% |    3.3% | $  0.16B | $  0.20B | $  0.13B |

        --- VALUATION ANCHORS (TTM) ---
        3. OWNER YIELD: 5.3%

    --- FORENSIC BLOCK (SEC XBRL) ---
| YEAR | SBC | SBC/Rev% | ACCTS REC | SHARES (M) | DEBT | R&D | GOODWILL |
| 2023 | $0.03B | n/a | $0.78B | 44M | $0.00B | $0.00B | $1.5B |
| 2022 | $0.05B | n/a | $0.86B | 46M | $0.00B | $0.00B | $1.5B |
"""


def test_reads_net_income_only_from_the_physics_block():
    """The forensic block has the same row shape and would otherwise win.

    BCO's accounts-receivable column ($0.78B) was being read as 2023 net
    income, turning a 0.9x TTM ratio into a spurious 0.23x.
    """
    parsed = triage.parse_physics(DOSSIER)
    assert parsed["ttm"] == pytest.approx(0.18e9)
    assert parsed["prior"] == pytest.approx(0.20e9)
    assert parsed["series"] == [pytest.approx(0.16e9), pytest.approx(0.20e9)]


def test_reads_owner_yield_and_revenue_series():
    parsed = triage.parse_physics(DOSSIER)
    assert parsed["owner_yield"] == pytest.approx(5.3)
    assert parsed["revenue"] == [pytest.approx(4.9e9), pytest.approx(5.0e9),
                                 pytest.approx(5.3e9)]


def test_returns_empties_rather_than_raising_on_an_unparseable_dossier():
    parsed = triage.parse_physics("nothing useful here")
    assert parsed["ttm"] is None and parsed["series"] == []


# --- growth math is invalid on a negative or zero base ---------------------
# VIC skews deep-value and turnarounds, so loss-making bases are the norm for
# this funnel, not an edge case.

def test_does_not_flag_a_turnaround_from_loss_to_profit():
    """-$1B -> +$1B is the best possible outcome and was reported as -200%."""
    flag = triage.stagnation_check([10e9, 12e9], [-1e9, 1e9])
    assert flag.failed is False
    assert "not computable" in flag.detail.lower()


def test_does_not_flag_a_company_halving_its_losses():
    flag = triage.stagnation_check([10e9, 12e9], [-1e9, -0.5e9])
    assert flag.failed is False


def test_does_not_crash_when_revenue_starts_at_zero():
    flag = triage.stagnation_check([0.0, 12e9], [1e9, 1.1e9])
    assert flag.failed is False
    assert "not computable" in flag.detail.lower()


def test_still_flags_the_genuine_case_it_was_built_for():
    # IQV must keep flagging after the guards are added
    assert triage.stagnation_check([15.0e9, 15.4e9, 16.3e9],
                                   [1.36e9, 1.373e9, 1.360e9]).failed is True


def test_ttm_spike_is_not_computable_when_ttm_is_negative():
    flag = triage.ttm_spike_check(-1e9, 1e9)
    assert flag.failed is False
    assert "not computable" in flag.detail.lower()


def test_distinguishes_a_missing_ttm_row_from_a_negative_base():
    """Foreign dossiers print 'Last Fiscal Year' and carry no TTM row.

    Reporting that as 'a non-positive earnings base' sends the reader looking
    for a loss that does not exist.
    """
    flag = triage.ttm_spike_check(None, 0.41e9)
    assert flag.failed is False
    assert "no ttm" in flag.detail.lower()
    assert "non-positive" not in flag.detail.lower()
