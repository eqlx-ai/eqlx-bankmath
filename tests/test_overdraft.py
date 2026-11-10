"""Retail overdraft (KMH): a month of use, the rate ceiling, the limit rule.

No authority publishes a worked overdraft month. The figures are:
official  = the ceiling TCMB published for 01.11.2026 (4.25 % per month, also valid for overdraft accounts) and
            the limit rule of BDDK decision 11365 (twice the documented average monthly income);
published = six "interest including KKDF and BSMV" amounts on a bank's public page for a rate of 4.25 %;
hand      = cases built here, with the arithmetic in the comment.
"""

import pytest

from eqlx_bankmath import overdraft
from eqlx_bankmath.errors import InputError

LEVIES = dict(kkdf="0.15", bsmv="0.15")
RATE = "0.0425"


def held(amount, days, **kw):
    """A debt of ``amount`` standing for ``days`` days from 01.11.2026."""
    return overdraft.period_interest(amount, [], "2026-11-01", f"2026-11-{days:02d}", RATE, **LEVIES, **kw)


@pytest.mark.parametrize(
    "amount, days, printed",
    [(200, 7, 2.58), (500, 7, 6.45), (1000, 7, 12.89), (2000, 14, 51.57), (5000, 7, 64.46), (100, 1, 0.18)],
)
def test_published_bank_amounts_including_levies(amount, days, printed):
    # A published bank example; it rounds interest and levies together, once.
    out = held(amount, days, rounding="total")
    assert (out["total"], out["days"]) == (printed, days)
    assert "together" in out["conventions"]["rounding"]


def test_rounding_each_line_differs_by_a_kurus_from_the_published_totals():
    # 500 x 4.25 % x 7/30 = 4.9583 -> 4.96; levies 0.744 -> 0.74 each; 4.96 + 0.74 + 0.74 = 6.44 (published 6.45).
    five = held(500, 7)
    assert (five["interest"], five["kkdf"], five["bsmv"], five["total"]) == (4.96, 0.74, 0.74, 6.44)
    # 1,000 x 4.25 % x 7/30 = 9.9167 -> 9.92; levies 1.488 -> 1.49 each; total 12.90 (published 12.89).
    assert held(1000, 7)["total"] == 12.90


def test_a_month_of_use():
    # November 2026 at 4.25 %, interest charged at month end, the last day counted:
    #   03.11 draw 5,000   -> 5,000 x 7 days = 35,000
    #   10.11 draw 3,000   -> 8,000 x 7 days = 56,000
    #   17.11 salary 6,000 -> 2,000 x 7 days = 14,000
    #   24.11 draw 4,000   -> 6,000 x 7 days = 42,000 (24.11 to 30.11 inclusive)
    # 147,000 TL-days x 4.25 % / 30 = 208.25; KKDF = BSMV = 31.2375 -> 31.24; charged 270.73.
    moves = [("2026-11-03", 5000), ("2026-11-10", 3000), ("2026-11-17", -6000), ("2026-11-24", 4000)]
    out = overdraft.period_interest(0, moves, "2026-11-01", "2026-11-30", RATE, reference_rate="0.0311", **LEVIES)
    assert (out["interest_numbers"], out["interest"], out["kkdf"], out["bsmv"], out["total"]) == (
        147000.0,
        208.25,
        31.24,
        31.24,
        270.73,
    )
    assert [(s["balance"], s["days"]) for s in out["stretches"]] == [
        (0.0, 2),
        (5000.0, 7),
        (8000.0, 7),
        (2000.0, 7),
        (6000.0, 7),
    ]
    assert (out["days"], out["closing_principal"]) == (30, 6000.0)  # the charges are not part of the interest base
    # ceiling from the reference rate: 3.11 % + 114 basis points = 4.25 %, the figure TCMB published for 01.11.2026
    assert (out["max_monthly_rate"], out["above_legal_cap"]) == (0.0425, False)
    assert out["fee"] == 0.0 and "2020/7 Article 10(6)" in out["legal_basis"]["no_fee"]
    assert any("No fee" in note for note in out["notes"])
    assert "monthly rate / 30" in out["conventions"]["formula"]
    # Stopping at the start of 30.11 drops one day of 6,000: 141,000 x 4.25 % / 30 = 199.75.
    shorter = overdraft.period_interest(0, moves, "2026-11-01", "2026-11-30", RATE, count_end_day=False)
    assert (shorter["interest"], shorter["days"]) == (199.75, 29)
    assert shorter["conventions"]["period_end"] == "the last day bears no interest"


def test_days_in_credit_bear_no_interest():
    # 1,000 in the account; 4,000 drawn on 11.11 (debt 3,000); 3,500 paid in on 21.11 (500 in credit again).
    # Only 11.11 to 20.11 is overdrawn: 3,000 x 10 days x 4.25 % / 30 = 42.50. Netting the
    # credit days (-1,000 x 10 and -500 x 10) would be wrong.
    out = overdraft.period_interest(
        -1000, [("2026-11-11", 4000), ("2026-11-21", -3500)], "2026-11-01", "2026-11-30", RATE
    )
    assert (out["interest"], out["interest_numbers"], out["closing_principal"]) == (42.50, 30000.0, -500.0)
    assert (out["kkdf"], out["bsmv"]) == (0.0, 0.0)  # levies are inputs; none given, none charged


def test_rate_ceiling_check():
    # The ceiling can be passed in or derived from the reference rate; a rate above it is computed and flagged.
    assert held(1000, 30, max_monthly_rate="0.0425")["above_legal_cap"] is False
    over = overdraft.period_interest(1000, [], "2026-11-01", "2026-11-30", "0.0426", reference_rate="0.0311")
    assert (over["above_legal_cap"], over["interest"]) == (True, 42.60)  # 1,000 x 4.26 % x 30/30
    unchecked = held(1000, 30)
    assert unchecked["above_legal_cap"] is None and unchecked["rate_cap_source"].startswith("not checked")
    assert "2020/3 Article 4(2)" in unchecked["legal_basis"]["rate_cap"]


def test_limit_rule_of_decision_11365():
    # average documented income 40,000 -> the limit may be 80,000 at most
    ok = overdraft.limit_check(80000, 40000, on="2026-11-10")
    assert (ok["maximum_limit"], ok["within_rule"], ok["excess"]) == (80000.0, True, 0.0) and "11365" in ok[
        "legal_basis"
    ]
    over = overdraft.limit_check("80000.01", 40000, on="2026-01-29")  # the decision date itself
    assert (over["within_rule"], over["excess"]) == (False, 0.01)
    # outside the rule: granted before the decision, or an education payment limit (point 2)
    before = overdraft.limit_check(200000, 40000, on="2026-01-28")
    assert (before["rule_applies"], before["within_rule"]) == (False, None)
    school = overdraft.limit_check(200000, 40000, on="2026-11-10", education_payment=True)
    assert (school["rule_applies"], school["within_rule"]) == (False, None) and "exempt" in school["reason"]
    assert overdraft.limit_check(100, 0)["within_rule"] is False  # no documented income, no limit


def test_inputs_are_checked():
    for bad in (
        dict(monthly_rate=4.25),  # a percentage instead of a fraction
        dict(monthly_rate=-0.01),
        dict(kkdf="1.5"),
        dict(rounding="x"),
        dict(count_end_day="yes"),
        dict(period_end="2026-10-31"),  # ends before it starts
        dict(movements=[("2026-12-05", 100)]),  # outside the period
        dict(opening_balance="a lot"),
        dict(max_monthly_rate=5),
    ):
        args = dict(
            opening_balance=0, movements=[], period_start="2026-11-01", period_end="2026-11-30", monthly_rate=RATE
        )
        args.update(bad)
        with pytest.raises(InputError):
            overdraft.period_interest(**args)
    for bad_limit in (dict(limit=0, average_monthly_income=1), dict(limit=1, average_monthly_income=-1),
                      dict(limit=1, average_monthly_income=1, education_payment=1),
                      dict(limit=1, average_monthly_income=1, on="29.01.2026")):  # fmt: skip
        with pytest.raises(InputError):
            overdraft.limit_check(**bad_limit)
