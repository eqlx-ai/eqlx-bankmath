"""The cost rate solver against examples printed in EU law, and its own properties.

Directive 98/7/EC inserted an Annex III with worked examples into Directive 87/102/EEC and required
that "the methods of resolution applicable give a result equal to that of the examples" (OJ L 101,
1.4.1998, pp. 20-23). A = calendar basis (days / 365), B = standard year.
"""

from decimal import Decimal as D

import pytest

from eqlx_bankmath import costrate
from eqlx_bankmath.errors import InputError


@pytest.mark.parametrize(
    ("name", "advance", "payments", "printed"),
    [
        ("A-1", 1000, [(D(546) / 365, 1200)], "0.1296204"),
        ("A-2", 950, [(D(546) / 365, 1200)], "0.169026"),
        ("A-3", 1000, [(1, 600), (2, 600)], "0.1306623"),
        ("A-4", 1000, [(D(90) / 365, 272), (D(181) / 365, 272), (1, 544)], "0.13226"),
        ("B-1", 1000, [("1.5", 1200)], "0.129243"),
        ("B-2", 950, [("1.5", 1200)], "0.168526"),
        ("B-3", 1000, [(1, 600), (2, 600)], "0.13066"),
        ("B-4", 1000, [("0.25", 272), ("0.5", 272), (1, 544)], "0.13185"),
    ],
)
def test_directive_98_7_annex_iii(name, advance, payments, printed):
    x = costrate.annual_cost_rate([(0, advance)], payments)
    places = len(printed.split(".")[1])
    assert abs(x - D(printed)) <= D(1).scaleb(-places), name


def test_single_payment_has_a_closed_form():
    # 1,000 now, 1,200 in 18 months: X = 1.2 ^ (1 / 1.5) - 1
    x = costrate.annual_cost_rate([(0, 1000)], [("1.5", 1200)])
    assert abs(float(x) - (1.2 ** (1 / 1.5) - 1)) < 1e-12


def test_monthly_flows_give_the_compounded_monthly_rate():
    # twelve payments of an exact 1 % annuity: X = 1.01 ^ 12 - 1
    pay = D(10000) * D("0.01") / (1 - D("1.01") ** -12)
    x = costrate.annual_cost_rate([(0, 10000)], [(D(k) / 12, pay) for k in range(1, 13)])
    assert abs(x - costrate.from_periodic("0.01")) < D("1e-20")
    assert costrate.as_percent(costrate.from_periodic("0.01")) == D("12.6825")
    assert costrate.as_percent(costrate.from_periodic("0.0399")) == D("59.9186")


def test_a_fee_raises_the_rate_and_no_interest_gives_zero():
    base = [(D(k) / 12, 100) for k in range(1, 13)]
    assert costrate.annual_cost_rate([(0, 1200)], base) == 0
    assert costrate.annual_cost_rate([(0, 1200)], [(0, 12), *base]) > 0
    below = costrate.annual_cost_rate([(0, 1200)], [(1, 1100)])  # less is repaid than was lent
    assert abs(below - D("-1") / 12) < D("1e-20")


def test_several_drawdowns():
    # 500 now and 500 after six months, 1,100 after a year: 500 (1+X) + 500 (1+X)^0.5 = 1100
    x = costrate.annual_cost_rate([(0, 500), ("0.5", 500)], [(1, 1100)])
    lhs = 500 * (1 + x) + 500 * (1 + x).sqrt()
    assert abs(lhs - 1100) < D("1e-15")


def test_rounding_to_four_decimals_is_half_up():
    assert costrate.as_percent(D("0.16487208")) == D("16.4872")
    assert costrate.as_percent(D("0.1648725")) == D("16.4873")
    assert costrate.as_percent(D("0.1"), 1) == D("10.0")


def test_bad_flows_are_rejected():
    for adv, pay in (
        ([], [(1, 1)]),
        ([(0, 1)], []),
        ([(0, -1)], [(1, 1)]),
        ([(1, 100)], [(2, 100)]),
        ([(0, 1)], [(-1, 1)]),
    ):
        with pytest.raises(InputError):
            costrate.annual_cost_rate(adv, pay)
    with pytest.raises(InputError):
        costrate.annual_cost_rate([(0, 1000)], [(1, "0.0000001")])
