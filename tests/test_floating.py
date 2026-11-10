"""Variable-rate loans.

Published figure: Borsa İstanbul, settlement price of the overnight reference rate (TLREF) futures,
worked example for 31.08-28.09.2018: product of the daily returns 1.018229476, price 22.18.
No worked example of a TLREF-indexed loan or of a repricing instalment loan has been published; those
cases are computed by hand in the comments.
"""

import math
from decimal import Decimal as D

import pytest

from eqlx_bankmath import floating, installment
from eqlx_bankmath.errors import InputError

# (TLREF, calendar days it applies) as printed in the Borsa İstanbul example; Fridays carry 3 days,
# and Friday 31.08.2018 carries 2 because the period ends before a third.
TLREF_2018_09 = [
    ("0.19250", 2),
    ("0.19250", 1),
    ("0.19250", 1),
    ("0.19250", 1),
    ("0.19250", 1),
    ("0.19250", 3),
    ("0.19250", 1),
    ("0.19250", 1),
    ("0.19250", 1),
    ("0.19250", 1),
    ("0.24000", 3),
    ("0.24000", 1),
    ("0.24000", 1),
    ("0.24000", 1),
    ("0.23360", 1),
    ("0.24480", 3),
    ("0.24250", 1),
    ("0.23480", 1),
    ("0.23750", 1),
    ("0.24610", 1),
    ("0.24210", 3),
]


def test_borsa_istanbul_published_example():
    out = floating.compound_reference(TLREF_2018_09)
    assert out["days"] == 30 and out["business_days"] == 21
    assert out["factor"] == 1.018229476  # printed: 1,018229476
    assert out["annual_rate_percent"] == 22.18  # printed: 22,18
    assert floating.compound_factor(TLREF_2018_09).quantize(D("0.000000001")) == D("1.018229476")
    # the daily returns printed in the example
    assert floating.compound_factor([("0.19250", 2)]).quantize(D("0.000000001")) == D("1.001054795")
    assert floating.compound_factor([("0.23360", 1)]) == D("1.00064")
    assert floating.compound_factor([("0.24210", 3)]).quantize(D("0.000000001")) == D("1.001989863")


def test_compounding_by_hand():
    # two days at 36.5 %: (1 + 0.365 / 365) ^ 2 = 1.001 ^ 2 = 1.002001; annual (0.002001) x 365 / 2 = 36.51825 %
    out = floating.compound_reference([("0.365", 1), ("0.365", 1)])
    assert floating.compound_factor([("0.365", 1), ("0.365", 1)]) == D("1.002001")
    assert out["annual_rate"] == pytest.approx(0.3651825, abs=1e-12)
    # one observation for two days does not compound between them: 1 + 0.365 x 2 / 365 = 1.002
    assert floating.compound_factor([("0.365", 2)]) == D("1.002")
    # on a 360-day year the same rate gives 1 + 0.36 / 360 = 1.001 per day
    assert floating.compound_factor([("0.36", 1)], year_basis=360) == D("1.001")


def test_spread_conventions_by_hand():
    # 1,000,000; two days at 36.5 %; spread 3.65 points (0.0001 a day on 365).
    #   spread added to the compounded rate: 0.002001 + 0.0365 x 2 / 365 = 0.002201      -> 2,201.00
    #   spread inside the compounding:       1.0011 ^ 2 - 1 = 0.00220121               -> 2,201.21
    #   simple average plus spread:          (0.365 + 0.0365) x 2 / 365 = 0.0022        -> 2,200.00
    obs = [("0.365", 1), ("0.365", 1)]
    plus = floating.period_interest(1000000, obs, "0.0365", bsmv="0.05")
    assert (plus["interest"], plus["bsmv"], plus["total"]) == (2201.0, 110.05, 2311.05)
    assert floating.period_interest(1000000, obs, "0.0365", method="compounded_with_spread")["interest"] == 2201.21
    assert floating.period_interest(1000000, obs, "0.0365", method="simple_average_plus_spread")["interest"] == 2200.0
    assert plus["annual_rate"] == pytest.approx(0.002201 * 365 / 2, abs=1e-12)
    assert "spread added" in plus["conventions"]["method"]


def test_spread_convention_on_the_published_month():
    # 1,000,000 TL at TLREF + 3 points over the published period (30 days).
    # A: 1,000,000 x (0.018229476 + 0.03 x 30 / 365 = 0.002465753) = 20,695.23
    a = floating.period_interest(1000000, TLREF_2018_09, "0.03")
    assert a["interest"] == 20695.23
    assert a["interest"] == pytest.approx(1000000 * (0.018229476 + 0.03 * 30 / 365), abs=0.01)
    # B: the spread compounds too, 44.99 TL more
    b = floating.period_interest(1000000, TLREF_2018_09, "0.03", method="compounded_with_spread")
    assert b["interest"] == 20740.22
    # C: no compounding, act/360. Sum of rate x days = 0.1925 x 13 + 0.24 x 6 + 0.2336 + 0.2448 x 3 + 0.2425
    #    + 0.2348 + 0.2375 + 0.2461 + 0.2421 x 3 = 6.5977; (6.5977 + 0.03 x 30) / 360 = 0.02082694 -> 20,826.94
    c360 = floating.period_interest(1000000, TLREF_2018_09, "0.03", method="simple_average_plus_spread", year_basis=360)
    assert c360["interest"] == 20826.94
    # the same without compounding on 365: 7.4977 / 365 = 0.02054164 -> 20,541.64
    c365 = floating.period_interest(1000000, TLREF_2018_09, "0.03", method="simple_average_plus_spread")
    assert c365["interest"] == 20541.64
    assert c365["interest"] < a["interest"] < b["interest"]


def test_repricing_two_instalments_by_hand():
    # 1,000 over 2 months, 10 % then 20 % from the second instalment, no levies.
    #   instalment 1: 1,000 x 0.1 / (1 - 1.1^-2) = 576.19; interest 100.00, principal 476.19, balance 523.81
    #   instalment 2 at 20 %: interest 104.76, payment 628.57
    out = floating.repricing_schedule(1000, 2, [(1, "0.10"), (2, "0.20")])
    assert [(r["payment"], r["interest"], r["principal"], r["balance"]) for r in out["rows"]] == [
        (576.19, 100.0, 476.19, 523.81),
        (628.57, 104.76, 523.81, 0.0),
    ]
    assert out["total_interest"] == 204.76 and out["total_repayment"] == 1204.76


def test_repricing_recomputes_the_instalment():
    # 600,000 TL, 12 months, 3.00 % a month, BSMV 5 %; 3.40 % from the seventh instalment.
    # gross rates 3.15 % and 3.57 %; closed forms checked in floating point below.
    out = floating.repricing_schedule(600000, 12, [(1, "0.03"), (7, "0.034")], bsmv="0.05", start="2026-01-31")
    first, second = out["segments"]
    a1 = 600000 * 0.0315 / (1 - 1.0315**-12)
    assert first["instalment"] == pytest.approx(a1, abs=0.005) and first["instalment"] == 60818.25
    # balance after six level instalments: P g^6 - A (g^6 - 1) / i, up to the kuruş rounding of six rows
    balance = 600000 * 1.0315**6 - 60818.25 * (1.0315**6 - 1) / 0.0315
    assert first["closing_balance"] == pytest.approx(balance, abs=0.05) and first["closing_balance"] == 327832.34
    a2 = 327832.34 * 0.0357 / (1 - 1.0357**-6)
    assert second["instalment"] == pytest.approx(a2, abs=0.005) and second["instalment"] == 61665.25
    assert (second["from_instalment"], second["to_instalment"], second["opening_balance"]) == (7, 12, 327832.34)
    rows = out["rows"]
    assert [r["number"] for r in rows] == list(range(1, 13))
    assert rows[0]["date"] == "2026-02-28" and rows[1]["date"] == "2026-03-31" and rows[-1]["date"] == "2027-01-31"
    assert math.fsum(r["principal"] for r in rows) == pytest.approx(600000, abs=1e-6) and rows[-1]["balance"] == 0.0
    # the first six rows are the fixed-rate plan; without repricing the loan would have cost less
    fixed = installment.plan(600000, "0.03", 12, bsmv="0.05")
    assert [r["payment"] for r in rows[:6]] == [float(r.payment) for r in fixed.rows[:6]]
    assert out["total_repayment"] > float(fixed.total("payment"))
    # first interest after repricing: 327,832.34 x 3.4 % = 11,146.30, BSMV 557.32
    assert (rows[6]["interest"], rows[6]["bsmv"]) == (11146.3, 557.32)


def test_repricing_by_date_matches_instalment_number():
    by_number = floating.repricing_schedule(600000, 12, [(1, "0.03"), (7, "0.034")], bsmv="0.05", start="2026-01-31")
    # the seventh instalment period begins on the sixth due date, 31.07.2026
    by_date = floating.repricing_schedule(
        600000, 12, [("2026-01-31", "0.03"), ("2026-07-31", "0.034")], bsmv="0.05", start="2026-01-31"
    )
    assert by_date == by_number
    # a rate set one day later only reaches the period that begins on 31.08: instalment 8
    later = floating.repricing_schedule(
        600000, 12, [("2026-01-31", "0.03"), ("2026-08-01", "0.034")], bsmv="0.05", start="2026-01-31"
    )
    assert later["segments"][1]["from_instalment"] == 8


def test_adjustment_method_changes_the_schedule():
    # 1,200 over 3 months at 10 %: instalment 1,200 x 0.1 / (1 - 1.1^-3) = 482.54
    #   row 1: interest 120.00, principal 362.54, balance 837.46
    #   row 2 of the original plan: interest 83.75, principal 398.79, balance 438.67
    # Rate 20 % from the second instalment.
    #   recompute: 837.46 x 0.2 / (1 - 1.2^-2) = 548.16; interest 167.49, principal 380.67, balance 456.79;
    #              last: interest 91.36, payment 548.15
    #   keep principal: 398.79 + 167.49 = 566.28, balance 438.67; last: 438.67 + 87.73 = 526.40
    rates = [(1, "0.10"), (2, "0.20")]
    new = floating.repricing_schedule(1200, 3, rates)
    assert [(r["payment"], r["interest"], r["principal"]) for r in new["rows"]] == [
        (482.54, 120.0, 362.54),
        (548.16, 167.49, 380.67),
        (548.15, 91.36, 456.79),
    ]
    kept = floating.repricing_schedule(1200, 3, rates, adjustment="keep_principal")
    assert [(r["payment"], r["interest"], r["principal"]) for r in kept["rows"]] == [
        (482.54, 120.0, 362.54),
        (566.28, 167.49, 398.79),
        (526.4, 87.73, 438.67),
    ]
    assert kept["total_repayment"] == 1575.22 and new["total_repayment"] == 1578.85
    assert "contractual" in new["conventions"]["legal_basis"]
    assert new["conventions"]["adjustment"] != kept["conventions"]["adjustment"]


def test_single_rate_equals_the_fixed_plan():
    fixed = installment.plan(50000, "0.01", 36, kkdf="0.15", bsmv="0.05")
    out = floating.repricing_schedule(50000, 36, [(1, "0.01")], kkdf="0.15", bsmv="0.05")
    assert out["rows"] == [r.to_dict() for r in fixed.rows]
    # TKSY Annex 2 prints this plan: instalment 1,718.61, total 61,870.07
    assert out["segments"][0]["instalment"] == 1718.61 and out["total_repayment"] == 61870.07


def test_inputs_are_checked():
    with pytest.raises(InputError):
        floating.compound_reference([])
    with pytest.raises(InputError):
        floating.compound_reference([("0.2", 0)])
    with pytest.raises(InputError):
        floating.compound_reference([(-0.2, 1)])
    with pytest.raises(InputError):
        floating.compound_factor([("0.2", 1)], year_basis=364)
    with pytest.raises(InputError):
        floating.period_interest(1000, [("0.2", 1)], "0.03", method="average")
    with pytest.raises(InputError):
        floating.period_interest(0, [("0.2", 1)])
    for bad in (
        dict(rates=[]),
        dict(rates=[(2, "0.03")]),  # no rate for the first instalment
        dict(rates=[(1, "0.03"), (13, "0.04")]),
        dict(rates=[(1, "0.03"), (1, "0.04")]),
        dict(rates=[(1, "0.03"), ("2026-07-31", "0.04")]),  # a date without a drawdown date
        dict(rates=[(1, 3)]),  # 300 % a month is not a monthly rate
        dict(adjustment="extend_term"),
        dict(n=0),
        dict(principal=-5),
    ):
        kw = dict(principal=1000, n=12, rates=[(1, "0.03")])
        kw.update(bad)
        with pytest.raises(InputError):
            floating.repricing_schedule(**kw)
