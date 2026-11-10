"""Credit cards: BDDK minimum payment decisions, the TCMB rate table, and statement cycles.

No authority publishes a worked card statement. The figures here are of three kinds, marked on each test:
official  = thresholds of BDDK decisions 10222 / 10970 / 11581 and the rate table TCMB published for 01.11.2026
            (reference rate 3.11 %, TCMB Communiqué 2020/16);
published = examples two banks publish on their public pages (10 days statement to due date, 20 days to
            the next statement, 1,000 TL of use). They illustrate practice, they are not law;
hand      = cases built here, with the arithmetic in the comment.
"""

import datetime as dt
from decimal import Decimal as D

import pytest

from eqlx_bankmath import card
from eqlx_bankmath.errors import InputError

# ---- minimum payment (official thresholds) -------------------------------------------------------


@pytest.mark.parametrize(
    "on, limit, ratio, decision",
    [
        ("2026-11-10", 100000, 0.20, "11581"),  # exactly at the threshold: "yüz bin Türk Lirası ve altında"
        ("2026-11-10", "100000.01", 0.40, "11581"),
        ("2026-10-01", 80000, 0.20, "11581"),  # the decision date itself
        ("2026-09-30", 80000, 0.40, "10970"),  # a day earlier the threshold was 50,000
        ("2026-09-30", 50000, 0.20, "10970"),
        ("2024-09-26", 30000, 0.20, "10970"),
        ("2024-09-25", 30000, 0.40, "10222"),  # threshold 25,000
        ("2022-06-09", 25000, 0.20, "10222"),
    ],
)
def test_minimum_payment_follows_the_decision_in_force(on, limit, ratio, decision):
    out = card.minimum_payment(12000, limit, on)
    assert out["ratio"] == ratio and decision in out["legal_basis"]
    assert out["minimum_payment"] == (2400.0 if ratio == 0.20 else 4800.0)  # 12,000 x 20 % and x 40 %
    assert out["conventions"]["effective_date"].startswith("the decision date")


def test_minimum_payment_rounding_rule_and_contract_ratio():
    assert card.minimum_payment("10305.60", 80000, "2026-11-15")["minimum_payment"] == 2061.12
    assert card.minimum_payment("14484.06", 80000, "2026-11-15")["minimum_payment"] == 2896.81  # 2,896.812
    # a bank may ask for more than the regulatory share (Regulation Article 17(5)(h)), not for less
    higher = card.minimum_payment(1000, 80000, "2026-11-15", contract_ratio="0.30")
    assert (higher["minimum_payment"], higher["below_regulatory_minimum"]) == (300.0, False)
    assert card.minimum_payment(1000, 80000, "2026-11-15", contract_ratio="0.10")["below_regulatory_minimum"] is True
    own = card.MinimumRule(dt.date(2020, 3, 30), D(10**12), D("0.20"), D("0.20"), "caller's rule")
    assert card.minimum_payment(1000, 500000, "2021-01-01", rule=own)["minimum_payment"] == 200.0
    with pytest.raises(InputError):
        card.minimum_payment(1000, 80000, "2022-06-08")  # nothing recorded before decision 10222


# ---- maximum rates (official table of 01.11.2026) ------------------------------------------------

REFERENCE = "0.0311"


@pytest.mark.parametrize(
    "kind, balance, contractual, default",
    [
        ("purchase", "29999.99", "0.0325", "0.0355"),
        ("purchase", 30000, "0.0375", "0.0405"),  # "between 30,000 and 180,000": the limits belong to the middle band
        ("purchase", 180000, "0.0375", "0.0405"),
        ("purchase", "180000.01", "0.0425", "0.0455"),
        ("corporate", None, "0.0425", "0.0455"),
        ("cash", None, "0.0425", "0.0455"),
        ("fx", None, "0.0298", "0.0328"),  # 4.25 x 70 % = 2.975, printed 2.98
        ("restructured", None, "0.0311", "0.0455"),
    ],
)
def test_tcmb_table_valid_from_2026_11_01(kind, balance, contractual, default):
    caps = card.max_rates(REFERENCE, balance, kind=kind, on="2026-11-01")
    assert (caps.contractual, caps.default) == (D(contractual), D(default))
    assert "2020/16" in caps.basis


def test_max_rates_inputs_and_output():
    out = card.max_rates(REFERENCE, 12000).to_dict()
    assert out["max_contractual_monthly_rate"] == 0.0325 and out["band"] == "below 30000"
    assert "middle band" in out["conventions"]["band"]
    with pytest.raises(InputError):
        card.max_rates(REFERENCE)  # a purchase ceiling needs the statement balance
    with pytest.raises(InputError):
        card.max_rates(REFERENCE, 1000, on="2025-12-31")  # earlier spreads are not recorded
    with pytest.raises(InputError):
        card.max_rates(REFERENCE, 1000, kind="gold")
    with pytest.raises(InputError):
        card.max_rates(3.11, 1000)  # a fraction is expected, not a percentage


# ---- published bank examples ---------------------------------------------------------------------

CYCLE = ("2026-03-01", "2026-03-11", "2026-03-31")  # 10 days, then 20 days

# First published bank example: minimum ratio, paid, contractual %, default %, then the printed columns
# statement->due, default part, contractual part, total. All 18 rows of its three tables.
PUBLISHED_A = [
    ("0.20", 200, "3.50", "3.80", 9.33, None, 18.67, 28.00),
    ("0.20", 200, "4.00", "4.30", 10.67, None, 21.33, 32.00),
    ("0.20", 200, "4.50", "4.80", 12.00, None, 24.00, 36.00),
    ("0.40", 400, "3.50", "3.80", 7.00, None, 14.00, 21.00),
    ("0.40", 400, "4.00", "4.30", 8.00, None, 16.00, 24.00),
    ("0.40", 400, "4.50", "4.80", 9.00, None, 18.00, 27.00),
    ("0.20", 100, "3.50", "3.80", 10.50, 2.53, 18.67, 31.70),
    ("0.20", 100, "4.00", "4.30", 12.00, 2.87, 21.33, 36.20),
    ("0.20", 100, "4.50", "4.80", 13.50, 3.20, 24.00, 40.70),
    ("0.40", 100, "3.50", "3.80", 10.50, 7.60, 14.00, 32.10),
    ("0.40", 100, "4.00", "4.30", 12.00, 8.60, 16.00, 36.60),
    ("0.40", 100, "4.50", "4.80", 13.50, 9.60, 18.00, 41.10),
    ("0.20", 0, "3.50", "3.80", 11.67, 5.07, 18.67, 35.40),
    ("0.20", 0, "4.00", "4.30", 13.33, 5.73, 21.33, 40.40),
    ("0.20", 0, "4.50", "4.80", 15.00, 6.40, 24.00, 45.40),
    ("0.40", 0, "3.50", "3.80", 11.67, 10.13, 14.00, 35.80),
    ("0.40", 0, "4.00", "4.30", 13.33, 11.47, 16.00, 40.80),
    ("0.40", 0, "4.50", "4.80", 15.00, 12.80, 18.00, 45.80),
]


def cycle(paid, minimum, contractual, default, dates=CYCLE, **kw):
    payments = [(dates[1], paid)] if paid else []
    return card.statement_interest(1000, minimum, *dates, contractual, default, payments=payments, **kw)


def part(out, period, rate_type, balance="purchases"):
    found = [
        p["interest"]
        for p in out["parts"]
        if (p["balance"], p["period"], p["rate_type"]) == (balance, period, rate_type)
    ]
    return found[0] if found else None


@pytest.mark.parametrize("ratio, paid, rc, rd, before, default_part, rest, total", PUBLISHED_A)
def test_published_bank_example_a(ratio, paid, rc, rd, before, default_part, rest, total):
    out = cycle(paid, D(1000) * D(ratio), D(rc) / 100, D(rd) / 100)
    assert part(out, "statement_to_due", "contractual") == before
    assert part(out, "after_due", "default") == default_part
    assert part(out, "after_due", "contractual") == rest
    assert out["interest"] == total
    assert out["minimum_met"] is (default_part is None)


def test_published_totals_are_rounded_once_not_per_part():
    # Row 13: the page prints 11.67 + 5.07 + 18.67 and a total of 35.40 (= 11.6667 + 5.0667 + 18.6667).
    assert cycle(0, 200, "0.035", "0.038")["interest"] == 35.40
    assert cycle(0, 200, "0.035", "0.038", rounding="parts")["interest"] == 35.41


def test_published_bank_example_b():
    # Second published bank example: 1.98 % contractual, 2.28 % default, minimum 20 %.
    case1 = cycle(200, 200, "0.0198", "0.0228")
    assert (part(case1, "statement_to_due", "contractual"), part(case1, "after_due", "contractual")) == (5.28, 10.56)
    assert case1["interest"] == 15.84
    case3 = cycle(0, 200, "0.0198", "0.0228")
    assert [p["interest"] for p in case3["parts"]] == [6.60, 3.04, 10.56] and case3["interest"] == 20.20
    # Its case 2 (150 paid) prints 5.61 + 0.76 + 11.22 = 17.59. The 11.22 is 850 x 1.98 % x 20/30: the 50 TL
    # already charged at the default rate is charged again at the contractual rate, against the rule the same
    # document states. The printed figure is not tested. By the rule: 850 x 1.98 % x 10/30 = 5.61;
    # 50 x 2.28 % x 20/30 = 0.76; 800 x 1.98 % x 20/30 = 10.56; total 16.93.
    case2 = cycle(150, 200, "0.0198", "0.0228")
    assert [p["interest"] for p in case2["parts"]] == [5.61, 0.76, 10.56] and case2["interest"] == 16.93


# ---- a full cycle with levies (hand-computed) ----------------------------------------------------

# Limit 80,000 -> minimum 20 % of 12,000 = 2,400. Band below 30,000 at the 01.11.2026 ceilings: 3.25 % / 3.55 %.
# Statement 15.10.2026, due 25.10.2026 (10 days), next statement 15.11.2026 (21 days: October has 31).
OCT = ("2026-10-15", "2026-10-25", "2026-11-15")
LEVIES = dict(kkdf="0.15", bsmv="0.15")


def october(payments, **kw):
    args = dict(payments=payments, new_purchases=3000, **LEVIES)
    args.update(kw)
    return card.statement_interest(12000, 2400, *OCT, "0.0325", "0.0355", **args)


def test_cycle_minimum_paid():
    # 5,000 paid, 7,000 unpaid. 7,000 x 3.25 % x 10/30 = 75.8333; 7,000 x 3.25 % x 21/30 = 159.25;
    # interest 235.0833 -> 235.08; KKDF = BSMV = 35.262 -> 35.26. Next statement: 7,000 + 3,000 + 305.60.
    out = october([("2026-10-25", 5000)])
    assert (out["interest"], out["kkdf"], out["bsmv"], out["total"]) == (235.08, 35.26, 35.26, 305.60)
    assert (out["of_which_default_interest"], out["minimum_met"]) == (0.0, True)
    assert (out["principal_carried"], out["charges_carried"], out["next_statement_balance"]) == (
        7000.0,
        305.60,
        10305.60,
    )
    assert (out["days_statement_to_due"], out["due_date_gap_meets_law"]) == (10, True)


def test_cycle_below_minimum_and_the_two_readings_of_the_shortfall():
    # 1,000 paid: 11,000 unpaid, of which 1,400 is the unpaid part of the minimum.
    # 11,000 x 3.25 % x 10/30 = 119.1667; 1,400 x 3.55 % x 21/30 = 34.79; 9,600 x 3.25 % x 21/30 = 218.40;
    # interest 372.3567 -> 372.36; levies 55.854 -> 55.85 each. Next statement 11,000 + 3,000 + 484.06.
    regulation = october([("2026-10-25", 1000)])
    assert [p["interest"] for p in regulation["parts"]] == [119.17, 34.79, 218.40]
    assert (regulation["interest"], regulation["of_which_default_interest"]) == (372.36, 34.79)
    assert (regulation["kkdf"], regulation["bsmv"], regulation["next_statement_balance"]) == (55.85, 55.85, 14484.06)
    assert (regulation["unpaid_part_of_minimum"], regulation["minimum_met"]) == (1400.0, False)
    assert "Regulation Article 20(3)" in regulation["legal_basis"]["shortfall"]
    # The Law's wording puts the whole 11,000 at the default rate after the due date:
    # 11,000 x 3.55 % x 21/30 = 273.35; interest 119.1667 + 273.35 = 392.5167 -> 392.52.
    # The difference is 9,600 x 0.30 % x 21/30 = 20.16.
    law = october([("2026-10-25", 1000)], shortfall_basis="whole_balance")
    assert (law["interest"], law["of_which_default_interest"]) == (392.52, 273.35)
    assert round(law["interest"] - regulation["interest"], 2) == 20.16
    assert "Law 5464 Article 26(2)" in law["legal_basis"]["shortfall"]
    assert (regulation["conventions"]["shortfall_basis"], law["conventions"]["shortfall_basis"]) == (
        "unpaid_minimum",
        "whole_balance",
    )


def test_cycle_paid_in_full_bears_no_interest_and_new_purchases_wait_for_their_statement():
    for convention in ("no_interest", "daily_balance"):
        out = october([("2026-10-20", 7000), ("2026-10-25", 5000)], paid_by_due_date=convention)
        assert (out["interest"], out["total"], out["parts"]) == (0.0, 0.0, [])
        assert out["next_statement_balance"] == 3000.0  # the purchase of the running cycle, without interest


def test_payments_on_different_dates_before_the_due_date():
    # 2,000 on 18.10 and 3,000 on 25.10 are both "paid by the due date": the same 235.08 as one payment of 5,000.
    split = [("2026-10-18", 2000), ("2026-10-25", 3000)]
    assert october(split)["interest"] == 235.08
    # Charging each amount until the day it is paid: 12,000 x 3 days + 10,000 x 7 days = 106,000 TL-days;
    # 106,000 x 3.25 % / 30 = 114.8333; plus 159.25 after the due date = 274.0833 -> 274.08.
    daily = october(split, paid_by_due_date="daily_balance")
    assert (daily["interest"], part(daily, "statement_to_due", "contractual")) == (274.08, 114.83)
    assert [r["days"] for r in daily["daily_balances"]] == [3, 7, 21]


def test_payment_after_the_due_date():
    # 1,000 by the due date, then 1,400 on 01.11 (7 days after the due date, 14 days before the next statement).
    late = [("2026-10-25", 1000), ("2026-11-01", 1400)]
    # It settles the unpaid part of the minimum first: default 1,400 x 3.55 % x 7/30 = 11.5967;
    # contractual 9,600 x 3.25 % x 21/30 = 218.40; before the due date 119.1667; total 349.1633 -> 349.16.
    first = october(late)
    assert [p["interest"] for p in first["parts"]] == [119.17, 11.60, 218.40]
    assert (first["interest"], first["paid_after_due_date"], first["principal_carried"]) == (349.16, 1400.0, 9600.0)
    # Set against the rest instead, 1,400 stays in default for all 21 days: 34.79; the contractual part is
    # (9,600 x 7 + 8,200 x 14) x 3.25 % / 30 = 182,000 x 3.25 % / 30 = 197.1667; total 351.1233 -> 351.12.
    rest = october(late, late_payments="rest_first")
    assert [p["interest"] for p in rest["parts"]] == [119.17, 34.79, 197.17] and rest["interest"] == 351.12
    # A payment a day after the due date does not count towards the minimum test.
    assert october([("2026-10-26", 12000)])["minimum_met"] is False


def test_day_count_and_start_date_conventions_are_echoed():
    paid = [("2026-10-25", 5000)]
    # Interest only from the due date: 7,000 x 3.25 % x 21/30 = 159.25.
    from_due = october(paid, interest_from="due_date")
    assert (from_due["interest"], from_due["conventions"]["interest_from"]) == (159.25, "due_date")
    # Every month 30 days: 25.10 -> 15.11 is 20 days. 75.8333 + 7,000 x 3.25 % x 20/30 (151.6667) = 227.50.
    thirty = october(paid, day_count="30/30")
    assert (thirty["interest"], thirty["conventions"]["day_count"]) == (227.50, "30/30")
    default = october(paid)["conventions"]
    assert (default["day_count"], default["interest_from"], default["paid_by_due_date"]) == (
        "actual/30",
        "statement_date",
        "no_interest",
    )


def test_posted_charges_bear_no_interest():
    # 12,000 on the statement, of which 2,000 is interest and levies of earlier cycles. Nothing paid, minimum 2,400.
    # 10,000 x 3.25 % x 10/30 = 108.3333; 2,400 x 3.55 % x 21/30 = 59.64; 7,600 x 3.25 % x 21/30 = 172.90 -> 340.87.
    nothing = october([], charges=2000)
    assert nothing["interest"] == 340.87
    # 2,000 paid on the due date goes to the charges first; 400 of the minimum stays unpaid.
    # 108.3333 + 400 x 3.55 % x 21/30 (9.94) + 9,600 x 3.25 % x 21/30 (218.40) = 336.6733 -> 336.67.
    paid = october([("2026-10-25", 2000)], charges=2000)
    assert (paid["interest"], paid["principal_carried"]) == (336.67, 10000.0)
    assert paid["charges_carried"] == round(336.67 + 2 * 50.50, 2)  # levies 336.67 x 15 % = 50.5005 -> 50.50


# ---- cash advances (hand-computed) ---------------------------------------------------------------

CASH = dict(cash_contractual_rate="0.0425", cash_default_rate="0.0455")


def test_cash_advance_bears_interest_from_the_transaction_date():
    # 5,000 drawn on 01.10.2026 at 4.25 %. Up to the statement of 15.10: 14 days,
    # 5,000 x 4.25 % x 14/30 = 99.1667 -> 99.17; levies 14.8755 -> 14.88 each.
    first = card.statement_interest(0, 0, "2026-09-15", "2026-09-25", "2026-10-15", "0.0325", "0.0355",
                                    cash_advances=[("2026-10-01", 5000)], **CASH, **LEVIES)  # fmt: skip
    assert (first["interest"], first["kkdf"], first["bsmv"]) == (99.17, 14.88, 14.88)
    assert first["principal_carried"] == 5000.0
    # The statement of 15.10 shows 5,000 + 99.17 + 14.88 + 14.88 = 5,128.93, paid in full on the due date.
    # Unlike a purchase the advance still bears interest for the 10 days to the payment:
    # 5,000 x 4.25 % x 10/30 = 70.8333 -> 70.83; levies 10.6245 -> 10.62 each.
    second = card.statement_interest("5128.93", "1025.79", *OCT, "0.0325", "0.0355", cash_balance=5000,
                                     charges="128.93", payments=[("2026-10-25", "5128.93")], **CASH, **LEVIES)  # fmt: skip
    assert (second["interest"], second["kkdf"], second["bsmv"], second["principal_carried"]) == (
        70.83,
        10.62,
        10.62,
        0.0,
    )
    assert part(second, "statement_to_due", "contractual", "cash") == 70.83
    with pytest.raises(InputError):  # a cash balance needs its own rate
        card.statement_interest(5000, 1000, *OCT, "0.0325", "0.0355", cash_balance=5000)


def test_payment_order_between_cash_and_purchases():
    # Statement 7,000 = 5,000 cash advance + 2,000 purchases; minimum 1,400; 3,000 paid on 20.10.
    args = (7000, 1400, *OCT, "0.0325", "0.0355")
    pay = [("2026-10-20", 3000)]
    # Cash first (default): the advance stands at 5,000 for 5 days, then 2,000 for 26 days = 77,000 TL-days,
    # x 4.25 % / 30 = 109.0833; purchases 2,000 unpaid for 31 days x 3.25 % / 30 = 67.1667; total 176.25.
    cash_first = card.statement_interest(*args, payments=pay, cash_balance=5000, **CASH)
    assert cash_first["interest"] == 176.25 and cash_first["conventions"]["payment_order"] == [
        "charges",
        "cash",
        "purchases",
    ]
    # Purchases first: purchases are cleared (no interest); the advance is 5,000 for 5 days, 4,000 for 26 days
    # = 129,000 TL-days x 4.25 % / 30 = 182.75.
    other = card.statement_interest(*args, payments=pay, cash_balance=5000, payment_order=("charges", "purchases", "cash"), **CASH)  # fmt: skip
    assert other["interest"] == 182.75


def test_unpaid_minimum_on_a_cash_balance_takes_the_cash_default_rate():
    # 7,000 = 5,000 cash + 2,000 purchases, minimum 40 % = 2,800, nothing paid. The unpaid minimum is taken
    # from the cash balance (first in the payment order).
    # cash before due 5,000 x 4.25 % x 10/30 = 70.8333; default 2,800 x 4.55 % x 21/30 = 89.18;
    # cash contractual 2,200 x 4.25 % x 21/30 = 65.45; purchases 2,000 x 3.25 % x 31/30 = 67.1667; total 292.63.
    out = card.statement_interest(7000, 2800, *OCT, "0.0325", "0.0355", cash_balance=5000, **CASH)
    assert (out["interest"], out["of_which_default_interest"]) == (292.63, 89.18)
    assert part(out, "after_due", "default", "cash") == 89.18 and part(out, "after_due", "default") is None


def test_cash_advance_fee_cap():
    # TCMB Communiqué 2020/7 Article 10(6): at most 1 % of the advance; nothing on an instalment cash advance.
    ok = card.cash_advance_fee_check(5000, 50)
    assert (ok["maximum_fee"], ok["within_cap"], ok["excess"]) == (50.0, True, 0.0) and "10(6)" in ok["legal_basis"]
    over = card.cash_advance_fee_check(5000, "50.01")
    assert (over["within_cap"], over["excess"]) == (False, 0.01)
    assert card.cash_advance_fee_check("333.33", "3.34")["within_cap"] is False  # 1 % is 3.3333: 3.33 at most
    assert card.cash_advance_fee_check("333.33", "3.33")["within_cap"] is True
    instalment = card.cash_advance_fee_check(5000, 1, instalment=True)
    assert (instalment["maximum_fee"], instalment["within_cap"]) == (0.0, False)
    assert card.cash_advance_fee_check(5000, 0, instalment=True)["within_cap"] is True


# ---- input validation ----------------------------------------------------------------------------


def test_statement_inputs_are_checked():
    good = dict(statement_balance=1000, minimum=200, statement_date="2026-03-01", due_date="2026-03-11",
                next_statement_date="2026-03-31", contractual_rate="0.035", default_rate="0.038")  # fmt: skip
    assert card.statement_interest(**good)["interest"] == 35.40
    for bad in (
        dict(statement_balance=-1),
        dict(minimum=1001),  # more than the balance
        dict(contractual_rate=3.5),  # a percentage instead of a fraction
        dict(default_rate=True),
        dict(due_date="2026-02-28"),  # before the statement date
        dict(next_statement_date="2026-03-10"),  # before the due date
        dict(statement_date="11.03.2026"),
        dict(payments=[("2026-04-01", 100)]),  # outside the cycle
        dict(payments=[("2026-03-05", -100)]),
        dict(payments=[("2026-03-05",)]),
        dict(cash_balance=600, charges=500, cash_contractual_rate="0.04"),  # parts exceed the balance
        dict(cash_advances=[("2026-03-05", 100)]),  # no cash rate
        dict(kkdf="1.5"),
        dict(shortfall_basis="law"),
        dict(interest_from="purchase_date"),
        dict(day_count="actual/365"),
        dict(paid_by_due_date="x"),
        dict(late_payments="x"),
        dict(rounding="x"),
        dict(payment_order=("cash", "purchases")),
    ):
        with pytest.raises(InputError):
            card.statement_interest(**{**good, **bad})
    short = card.statement_interest(**{**good, "due_date": "2026-03-10"})  # 9 days: computed, but flagged
    assert (short["days_statement_to_due"], short["due_date_gap_meets_law"]) == (9, False)
    for bad_fee in (dict(advance=0, fee=1), dict(advance=100, fee=-1), dict(advance=100, fee=1, instalment="yes")):
        with pytest.raises(InputError):
            card.cash_advance_fee_check(**bad_fee)
