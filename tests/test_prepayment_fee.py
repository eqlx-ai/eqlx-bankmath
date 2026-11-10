"""Cap on the early repayment fee for commercial loans.

Official figures: TCMB implementation instruction for Communiqué 2020/4, section 4/IV: example 1
(lira, 1.64 %), example 2 (US dollar, 2.23 %), the illustration in 4/IV/e (30 months left: 3 %) and
the rounding illustration (1.6412 becomes 1.64). Other cases apply the printed formulas by hand.
"""

from decimal import Decimal as D

import pytest

from eqlx_bankmath import installment, prepayment_fee
from eqlx_bankmath.errors import InputError


def remaining(instalment):
    # closed 15 days before the 22nd instalment: instalments 22, 23 and 24 fall due in 15, 45 and 75 days
    return [(15, instalment), (45, instalment), (75, instalment)]


def test_official_example_1_lira():
    # 100,000 TL, 2 % a month, 24 months, instalment 5,287.11 (as printed, without tax in the rate).
    assert installment.plan(100000, "0.02", 24).instalment == D("5287.11")
    # A = (1.02^12 - 1) x 5 % = 0.26824 x 5 % = 1.3412 %;  k = (15 + 45 + 75) / 3 / 30 = 1.5 months
    # B = 1.5 x 0.20 % = 0.30 %;  A + B = 1.6412 % -> 1.64 %
    out = prepayment_fee.cap("2024-07-01", monthly_rate="0.02", remaining_instalments=remaining("5287.11"))
    assert out["cap_percent"] == 1.64
    assert out["components"]["weighted_average_months"] == 1.5
    assert out["components"]["maturity_part"] == 0.003
    assert round(out["components"]["rate_part"] * 100, 4) == 1.3412
    assert round(out["unrounded_percent"], 4) == 1.6412
    assert "4/IV/f" in out["basis"]


def test_official_example_2_foreign_currency():
    # 100,000 USD, 1 % a month, 24 months, instalment 4,707.35.
    assert installment.plan(100000, "0.01", 24).instalment == D("4707.35")
    # C = 2 % + 1.5 x 0.15 % = 2.225 % -> 2.23 % (third decimal 5 rounds up)
    out = prepayment_fee.cap("2024-07-01", currency="foreign", remaining_instalments=remaining("4707.35"))
    assert out["cap_percent"] == 2.23 and round(out["unrounded_percent"], 6) == 2.225
    # instruction 4/IV/g, loans drawn from 06.01.2025: 3 % + 1.5 x 0.10 % = 3.15 %
    assert prepayment_fee.cap("2025-01-05", currency="foreign", weighted_months="1.5")["cap_percent"] == 2.23
    assert prepayment_fee.cap("2025-01-06", currency="foreign", weighted_months="1.5")["cap_percent"] == 3.15


def test_regimes_by_drawdown_date():
    cap = prepayment_fee.cap
    # before 01.03.2021 (4/IV/d): 1 % up to 24 months, 2 % beyond; one point more in foreign currency
    assert cap("2021-02-28", remaining_months=24)["cap_percent"] == 1.0
    assert cap("2021-02-28", remaining_months=25)["cap_percent"] == 2.0
    assert cap("2021-02-28", remaining_months=60)["cap_percent"] == 2.0
    assert cap("2019-06-01", remaining_months=60, currency="foreign")["cap_percent"] == 3.0
    assert cap("2021-02-28", remaining_months=12, currency="foreign")["cap_percent"] == 2.0
    # 01.03.2021 to 30.06.2024 (4/IV/e): 2 %, plus 1 % per started year beyond 24 months.
    # The instruction's own illustration: 30 months left -> 3 %.
    assert cap("2021-03-01", remaining_months=30)["cap_percent"] == 3.0
    assert cap("2024-06-30", remaining_months=24)["cap_percent"] == 2.0
    assert cap("2024-06-30", remaining_months=36)["cap_percent"] == 3.0  # exactly one year beyond
    assert cap("2024-06-30", remaining_months=37)["cap_percent"] == 4.0  # a started second year
    assert cap("2024-06-30", remaining_months=30, currency="foreign")["cap_percent"] == 4.0
    # from 01.07.2024 a variable-rate loan: 2 % whatever the term; older loans have no separate rule
    assert cap("2024-07-01", rate_type="variable")["cap_percent"] == 2.0
    old = cap("2022-01-01", rate_type="variable", remaining_months=30)
    assert old["cap_percent"] == 3.0 and "no separate rule" in old["notes"][0]
    assert cap("2024-06-30", remaining_months=30)["regime"] != cap("2024-07-01", rate_type="variable")["regime"]


def test_weighted_average_maturity_and_amounts():
    # unequal instalments: (1,000 x 30 + 3,000 x 90) / 4,000 = 75 days = 2.5 months
    assert prepayment_fee.weighted_average_months([(30, 1000), (90, 3000)]) == D("2.5")
    # a bullet due in 30 days: k = 1. With f = 53.18 %: 53.18 x 5 % + 0.20 = 2.859 -> 2.86 %
    out = prepayment_fee.cap(
        "2026-01-10",
        annual_compound_rate="0.5318",
        remaining_instalments=[(30, 1000000)],
        amount_repaid=1000000,
        quoted_fee=30000,
    )
    assert out["cap_percent"] == 2.86
    # 1,000,000 x 2.86 % = 28,600.00; a fee of 30,000 is 1,400 above it
    assert (out["maximum_fee"], out["exceeds"], out["excess"]) == (28600.0, True, 1400.0)
    # how f is read for a bullet loan is not settled by the instruction: the nominal 45 % gives 2.45 %
    nominal = prepayment_fee.cap("2026-01-10", annual_compound_rate="0.45", weighted_months=1, amount_repaid=1000000)
    assert nominal["cap_percent"] == 2.45 and nominal["maximum_fee"] == 24500.0


def test_rounding_half_up_to_two_decimals():
    # f = 20 %, k = 0.225: 1 % + 0.045 % = 1.045 % -> 1.05 %
    assert prepayment_fee.cap("2025-03-01", annual_compound_rate="0.20", weighted_months="0.225")["cap_percent"] == 1.05
    # k = 0.22: 1.044 % -> 1.04 %
    assert prepayment_fee.cap("2025-03-01", annual_compound_rate="0.20", weighted_months="0.22")["cap_percent"] == 1.04


def test_inputs_are_checked():
    cap = prepayment_fee.cap
    for kw in (
        dict(disbursed_on="2022-01-01"),  # remaining term missing
        dict(disbursed_on="2022-01-01", remaining_months=0),
        dict(disbursed_on="2025-01-01", monthly_rate="0.02"),  # k missing
        dict(disbursed_on="2025-01-01", weighted_months=2),  # f missing
        dict(disbursed_on="2025-01-01", weighted_months=2, monthly_rate="0.02", annual_compound_rate="0.3"),
        dict(disbursed_on="2025-01-01", weighted_months=2, remaining_instalments=[(30, 100)], monthly_rate="0.02"),
        dict(disbursed_on="2025-01-01", weighted_months=2, monthly_rate="0.02", quoted_fee=10),  # no amount
        dict(disbursed_on="2025-01-01", currency="gold", weighted_months=2),
        dict(disbursed_on="2025-01-01", rate_type="mixed"),
        dict(disbursed_on="01.01.2025", rate_type="variable"),
    ):
        with pytest.raises(InputError):
            cap(**kw)
    with pytest.raises(InputError):
        prepayment_fee.weighted_average_months([])
    with pytest.raises(InputError):
        prepayment_fee.weighted_average_months([(-1, 100)])
