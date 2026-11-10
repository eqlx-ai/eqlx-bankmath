"""Instalment plans against arithmetic done by hand, and their invariants."""

import random
from decimal import Decimal as D

import pytest

from eqlx_bankmath import costrate, installment
from eqlx_bankmath.errors import InputError
from eqlx_bankmath.money import dec, money


def test_levies_are_charged_on_interest_not_on_each_other():
    # 100,000 at 5 % a month with KKDF 15 % and BSMV 15 %: first month interest 5,000, levies 750 each
    p = installment.plan(100000, "0.05", 12, kkdf="0.15", bsmv="0.15")
    first = p.rows[0]
    assert (first.interest, first.kkdf, first.bsmv) == (D("5000.00"), D("750.00"), D("750.00"))
    assert p.gross_rate == D("0.065")
    assert p.instalment == D("12256.82")  # 100000 x 0.065 / (1 - 1.065^-12) = 12256.8166...


def test_every_plan_adds_up():
    rng = random.Random(7)
    for _ in range(200):
        principal = D(rng.randrange(1_000_00, 5_000_000_00)) / 100
        rate = D(rng.randrange(0, 800)) / 10000
        n = rng.randrange(1, 121)
        method = rng.choice(["annuity", "equal_principal", "bullet"])
        grace = rng.randrange(0, min(n, 4)) if method != "bullet" else 0
        p = installment.plan(principal, rate, n, kkdf="0.15", bsmv="0.15", method=method, interest_only_periods=grace)
        assert p.total("principal") == principal and p.rows[-1].balance == 0
        balance = principal
        for r in p.rows:
            assert r.payment == r.principal + r.interest + r.kkdf + r.bsmv
            assert r.interest == money(balance * rate) and r.kkdf == money(r.interest * D("0.15"))
            balance -= r.principal
            assert r.balance == balance and r.principal >= 0
        assert p.total_repayment == p.total("payment") and p.total_cost == p.total("payment") - principal


def test_equal_principal_by_hand():
    # 1,200 over 4 months at 2 %, no levies: principal 300 a month; interest 24, 18, 12, 6
    p = installment.plan(1200, "0.02", 4, method="equal_principal")
    assert [r.payment for r in p.rows] == [D("324.00"), D("318.00"), D("312.00"), D("306.00")]
    assert [r.balance for r in p.rows] == [D(900), D(600), D(300), D(0)]


def test_bullet_and_interest_only_periods():
    b = installment.plan(1000, "0.03", 3, method="bullet", bsmv="0.05")
    assert [r.payment for r in b.rows] == [D("31.50"), D("31.50"), D("1031.50")]
    g = installment.plan(10000, "0.01", 14, interest_only_periods=2, kkdf="0.15", bsmv="0.05")
    assert [r.payment for r in g.rows[:2]] == [D("120.00"), D("120.00")] and g.rows[1].balance == D(10000)
    # after the two interest-only months it is the twelve-month plan of the regulation's first example
    assert g.instalment == D("899.75") and g.rows[-1].payment == D("899.81")


def test_balloon():
    # 10,000 at 1 % for 12 months leaving 4,000 for the end: (10000 - 4000 x 1.01^-12) x 0.01 / (1 - 1.01^-12)
    p = installment.plan(10000, "0.01", 12, balloon=4000)
    assert p.instalment == D("573.09")
    assert p.rows[-1].principal > 4000 and p.rows[-1].balance == 0
    assert abs(p.rows[-2].balance - (4000 + D("573.09") - D("45.73"))) < D("0.5")


def test_zero_rate_and_one_instalment():
    z = installment.plan(1200, 0, 12)
    assert [r.payment for r in z.rows] == [D("100.00")] * 12 and z.annual_cost_rate() == 0
    one = installment.plan(1000, "0.02", 1, kkdf="0.15", bsmv="0.15")
    assert one.rows[0].payment == D("1026.00")


def test_odd_first_period():
    # first instalment after 45 days: interest 10000 x 1 % x 45/30 = 150
    p = installment.plan(10000, "0.01", 12, first_period_days=45, start="2026-01-10")
    assert p.rows[0].interest == D("150.00")
    assert p.instalment == money(installment.annuity_payment(D(10000), D("0.01"), 12) * D("1.01") ** D("0.5"))
    # first due date 45 days after drawdown, then the same day of every month
    assert [r.date.isoformat() for r in p.rows[:3]] == ["2026-02-24", "2026-03-24", "2026-04-24"]
    # the longer first period costs more in total but about the same per year
    regular = installment.plan(10000, "0.01", 12)
    assert p.total_cost > regular.total_cost
    assert abs(p.annual_cost_rate() - regular.annual_cost_rate()) < D("0.001")


def test_annual_cost_rate_against_the_plain_annual_rate():
    # today's levies turn 3.99 % a month (59.92 % a year) into a much higher cost
    p = installment.plan(100000, "0.0399", 24, kkdf="0.15", bsmv="0.15", fee=500)
    assert p.instalment == D("7379.48") and p.total_repayment == D("177607.76")
    d = p.to_dict(rows=False)
    assert d["annual_rate_from_monthly_rate_percent"] == 59.9186
    assert d["annual_cost_rate_percent"] == pytest.approx(84.55, abs=0.01)
    no_fee = installment.plan(100000, "0.0399", 24, kkdf="0.15", bsmv="0.15")
    assert abs(no_fee.annual_cost_rate() - costrate.from_periodic(D("0.0399") * D("1.3"))) < D("0.0001")
    assert "rows" not in d and len(p.to_dict()["rows"]) == 24


def test_largest_loan_for_an_instalment_respects_rounding():
    kw = dict(kkdf="0.15", bsmv="0.15")
    best = installment.largest_principal(5000, "0.05", 12, **kw)
    # 40,793.66 has a rounded instalment of 5,000.00 but a last instalment of 5,000.05: not within budget
    assert max(r.payment for r in installment.plan(D("40793.66"), "0.05", 12, **kw).rows) > 5000
    assert best == D("40793.62")
    assert max(r.payment for r in installment.plan(best, "0.05", 12, **kw).rows) <= 5000
    assert max(r.payment for r in installment.plan(best + D("0.01"), "0.05", 12, **kw).rows) > 5000


def test_implied_rate_and_shortest_term():
    kw = dict(kkdf="0.15", bsmv="0.05")
    exact = installment.annuity_payment(D(10000), D("0.012"), 12)
    assert abs(installment.implied_monthly_rate(10000, exact, 12, **kw) - D("0.01")) < D("1e-15")
    assert installment.shortest_term(10000, 900, "0.01", **kw) == 12
    assert installment.shortest_term(10000, 899, "0.01", **kw) == 13
    with pytest.raises(InputError):
        installment.shortest_term(10000, 100, "0.02", **kw)
    with pytest.raises(InputError):
        installment.implied_monthly_rate(10000, 100, 12)


def test_payoff_saving_and_prepayment_limits():
    p = installment.plan(50000, "0.01", 36, kkdf="0.15", bsmv="0.05")
    out = installment.payoff(p, 10)
    assert out["payoff"] == 38190.09 and out["saving"] == pytest.approx(
        float(sum(r.payment for r in p.rows[10:])) - 38190.09
    )
    assert installment.payoff(p, 0)["payoff"] == 50000.0 and installment.payoff(p, 36)["payoff"] == 0.0
    with pytest.raises(InputError):
        installment.payoff(p, 37)
    with pytest.raises(InputError, match="whole debt"):
        installment.prepay(p, 10, 40000)
    with pytest.raises(InputError, match="interest accrued"):
        installment.prepay(p, 9, 100, days_since_last_due=21)
    with pytest.raises(InputError):
        installment.prepay(p, 9, 10000, days_since_last_due=30)
    smaller = installment.prepay(p, 10, 5000)
    assert smaller.n == 26 and smaller.instalment < p.instalment and smaller.principal == D("33190.09")


def test_floats_do_not_bring_binary_noise():
    a = installment.plan(100000.0, 0.0399, 24, kkdf=0.15, bsmv=0.15)
    b = installment.plan("100000", "0.0399", 24, kkdf="0.15", bsmv="0.15")
    assert [r.payment for r in a.rows] == [r.payment for r in b.rows]
    assert dec(0.1) + dec(0.2) == D("0.3")
