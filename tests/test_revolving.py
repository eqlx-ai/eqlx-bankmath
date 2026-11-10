"""Revolving lines, spot loans and fee caps for commercial customers.

Sources of the figures: TCMB Communiqué 2020/4 and its implementation instruction (fee caps);
Altuğ & Ünkaya, Banka İşlemleri ve Muhasebesi, Marmara Üniversitesi 1991, p. 174 (interest numbers);
a public bank page (spot loan, 100,000 TL for 30 days at 15 %). Everything else is computed by hand
in the comments. No worked example of a quarterly-capitalised current account has been published.
"""

import datetime as dt
from decimal import Decimal as D

import pytest

from eqlx_bankmath import revolving
from eqlx_bankmath.errors import InputError
from eqlx_bankmath.tr import rates

# A firm's overdraft from 1 July to 30 September 2026; the rate falls from 48 % to 44 % on 24 August.
MOVES = [
    ("2026-07-01", 400000),
    ("2026-07-20", 250000),
    ("2026-08-14", -300000),
    ("2026-09-10", 500000),
    ("2026-09-25", -200000),
]
RATES = [("2026-07-01", "0.48"), ("2026-08-24", "0.44")]


def quarter(**kw):
    return revolving.line(0, MOVES, "2026-07-01", "2026-09-30", RATES, bsmv="0.05", **kw)


def test_period_ends_quarterly_monthly_and_given():
    q = revolving.period_ends("2026-02-10", "2027-01-15")
    assert [d.isoformat() for d in q] == ["2026-03-31", "2026-06-30", "2026-09-30", "2026-12-31", "2027-01-15"]
    m = revolving.period_ends("2028-01-20", "2028-03-31", "monthly")
    assert [d.isoformat() for d in m] == ["2028-01-31", "2028-02-29", "2028-03-31"]  # leap year
    given = revolving.period_ends("2026-01-01", "2026-03-01", ["2026-02-10", dt.date(2026, 1, 15)])
    assert [d.isoformat() for d in given] == ["2026-01-15", "2026-02-10", "2026-03-01"]


def test_quarter_with_rate_change_by_hand():
    # End day not counted, 91 days:
    #   400,000 x 19 (01.07-20.07) =  7,600,000   at 48 %
    #   650,000 x 25 (20.07-14.08) = 16,250,000   at 48 %
    #   350,000 x 10 (14.08-24.08) =  3,500,000   at 48 %   -> 27,350,000
    #   350,000 x 17 (24.08-10.09) =  5,950,000   at 44 %
    #   850,000 x 15 (10.09-25.09) = 12,750,000   at 44 %
    #   650,000 x  5 (25.09-30.09) =  3,250,000   at 44 %   -> 21,950,000
    # interest = (27,350,000 x 0.48 + 21,950,000 x 0.44) / 360 = 22,786,000 / 360 = 63,294.44
    # BSMV 5 % = 3,164.72
    out = quarter(count_end_day=False, unpaid_interest="paid")
    (p,) = out["periods"]
    assert p["days"] == 91
    assert p["interest_numbers_by_rate"] == [
        {"annual_rate": 0.48, "interest_numbers": 27350000.0},
        {"annual_rate": 0.44, "interest_numbers": 21950000.0},
    ]
    assert (p["interest"], p["bsmv"], p["kkdf"], p["charge"]) == (63294.44, 3164.72, 0.0, 66459.16)
    # average debit balance = 49,300,000 / 91 = 541,758.24
    assert p["average_debit_balance"] == 541758.24
    assert out["closing_balance"] == 650000.0 and out["paid_separately"] == 66459.16
    assert out["conventions"]["year_basis"] == 360


def test_day_basis_and_end_day_change_the_charge():
    # Counting 30.09 adds 650,000 x 1 at 44 %: numbers 22,600,000.
    #   92 days / 360: (13,128,000 + 9,944,000) / 360 = 64,088.89, BSMV 3,204.44
    #   91 days / 365: 22,786,000 / 365 = 62,427.40, BSMV 3,121.37
    #   92 days / 365: 23,072,000 / 365 = 63,210.96, BSMV 3,160.55
    results = {
        (end_day, basis): quarter(count_end_day=end_day, year_basis=basis, unpaid_interest="paid")["total_charge"]
        for end_day in (False, True)
        for basis in (360, 365)
    }
    assert results == {(False, 360): 66459.16, (False, 365): 65548.77, (True, 360): 67293.33, (True, 365): 66371.51}
    # the same account, four answers: the widest gap is 1,744.56 TL
    assert round(max(results.values()) - min(results.values()), 2) == 1744.56


def test_published_interest_numbers_example():
    # Altuğ & Ünkaya 1991, p. 174: rate 20 %, year of 365 days. Balances 1,500,000 for 7 days,
    # 2,250,000 for 4, 1,750,000 for 23 and 2,000,000 for 33: interest numbers 125,750,000 (the book
    # prints them divided by 100: 1,257,500) and interest 68,904.
    out = revolving.line(
        0,
        [("1989-03-03", 1500000), ("1989-03-10", 750000), ("1989-03-14", -500000), ("1989-04-06", 250000)],
        "1989-03-03",
        "1989-05-09",
        "0.20",
        year_basis=365,
        accrual=[],
        count_end_day=False,
    )
    (p,) = out["periods"]
    assert p["days"] == 67 and p["interest_numbers"] == 125750000.0
    assert p["interest"] == 68904.11 and round(p["interest"]) == 68904


def test_unpaid_quarter_interest_paid_or_capitalised():
    # 1,000,000 constant, 45 %, /360, BSMV 5 %. Third quarter 92 days:
    #   1,000,000 x 92 x 0.45 / 360 = 115,000.00; BSMV 5,750.00
    # Fourth quarter (92 days) if the charge was paid: again 115,000.00.
    # If it was debited to the account: 1,120,750 x 92 x 0.45 / 360 = 128,886.25; BSMV 6,444.31.
    paid = revolving.line(1000000, [], "2026-07-01", "2026-12-31", "0.45", bsmv="0.05", unpaid_interest="paid")
    assert [(p["days"], p["interest"]) for p in paid["periods"]] == [(92, 115000.0), (92, 115000.0)]
    assert paid["closing_balance"] == 1000000.0 and paid["total_capitalised"] == 0.0
    cap = revolving.line(1000000, [], "2026-07-01", "2026-12-31", "0.45", bsmv="0.05")
    assert [(p["interest"], p["bsmv"]) for p in cap["periods"]] == [(115000.0, 5750.0), (128886.25, 6444.31)]
    assert cap["periods"][0]["closing_balance"] == 1120750.0
    assert cap["closing_balance"] == 1256080.56  # 1,120,750 + 128,886.25 + 6,444.31
    assert cap["warnings"] == []  # quarterly is the three-month minimum of TTK Article 8(2)
    # only the interest is added when the levies are paid separately: 1,115,000 x 92 x 0.45 / 360 = 128,225.00
    net = revolving.line(1000000, [], "2026-07-01", "2026-12-31", "0.45", bsmv="0.05", capitalise_levies=False)
    assert net["periods"][1]["interest"] == 128225.0 and net["paid_separately"] == 5750.0 + 6411.25


def test_capitalisation_warnings():
    monthly = revolving.line(100000, [], "2026-07-01", "2026-10-31", "0.36", accrual="monthly")
    # capitalised on 31.07, 31.08, 30.09 and 31.10; all but the first come less than three months after the one before
    assert len(monthly["warnings"]) == 3 and "TTK Article 8(2)" in monthly["warnings"][0]
    consumer = revolving.line(100000, [], "2026-07-01", "2026-12-31", "0.36", merchant=False)
    assert len(consumer["warnings"]) == 1 and "not a merchant" in consumer["warnings"][0]
    assert (
        revolving.line(100000, [], "2026-07-01", "2026-10-31", "0.36", accrual="monthly", unpaid_interest="paid")[
            "warnings"
        ]
        == []
    )


def test_every_day_counted_once_across_periods_and_credit_days_free():
    # 01.01-30.06.2027 is 181 days when the last day counts, 180 when it does not.
    for end_day, days in ((True, 181), (False, 180)):
        out = revolving.line(
            1000, [], "2027-01-01", "2027-06-30", "0.36", count_end_day=end_day, unpaid_interest="paid"
        )
        assert sum(p["days"] for p in out["periods"]) == days
    # A movement on an accrual date belongs to one period only. Balance 1,000 until 31.03, then 3,000.
    #   31.03 counted in the first quarter: 1,000 x 89 + 3,000 x 1 = 92,000; second: 3,000 x 30 = 90,000
    a = revolving.line(1000, [("2027-03-31", 2000)], "2027-01-01", "2027-04-30", "0.36", unpaid_interest="paid")
    assert [p["interest_numbers"] for p in a["periods"]] == [92000.0, 90000.0]
    #   31.03 opens the second period: 1,000 x 89 = 89,000; then 3,000 x 30 = 90,000 (30.04 not counted)
    b = revolving.line(
        1000, [("2027-03-31", 2000)], "2027-01-01", "2027-04-30", "0.36", unpaid_interest="paid", count_end_day=False
    )
    assert [p["interest_numbers"] for p in b["periods"]] == [89000.0, 90000.0]
    # 10 days in debit at 1,000, then 20 days in credit at 500: interest 1,000 x 10 x 0.36 / 360 = 10.00
    c = revolving.line(
        1000, [("2027-01-11", -1500)], "2027-01-01", "2027-01-31", "0.36", count_end_day=False, unpaid_interest="paid"
    )
    assert c["total_interest"] == 10.0 and c["periods"][0]["credit_interest_numbers"] == 10000.0


def test_spot_published_example():
    # Public bank page: 100,000 TL, 30 days, 15 %: 100,000 x 30 x 15 / 36000 = 1,250 TL.
    # The page shows no tax; with BSMV 5 % (62.50) the borrower pays 101,312.50 at maturity.
    s = revolving.spot(100000, "0.15", 30, bsmv="0.05")
    assert (s["interest"], s["bsmv"], s["paid_at_maturity"]) == (1250.0, 62.5, 101312.5)
    # the same loan on a 365-day year: 100,000 x 30 x 0.15 / 365 = 1,232.88
    assert revolving.spot(100000, "0.15", 30, year_basis=365)["interest"] == 1232.88


def test_spot_with_fee_and_effective_cost():
    # 1,000,000 TL, 90 days, 45 %: interest 112,500.00; BSMV 5,625.00
    # fee 2,750.00 + BSMV 137.50 at drawdown: received 997,112.50; paid at day 90: 1,118,125.00
    s = revolving.spot(1000000, "0.45", 90, bsmv="0.05", fee=2750)
    assert (s["interest"], s["bsmv"], s["fee"], s["bsmv_on_fee"]) == (112500.0, 5625.0, 2750.0, 137.5)
    assert (s["net_received"], s["paid_at_maturity"], s["total_cost"]) == (997112.5, 1118125.0, 121012.5)
    # simple: 121,012.50 / 997,112.50 x 360 / 90 = 48.5452 %
    assert s["simple_annual_cost_percent"] == 48.5452
    # compound, closed form for one payment: (1,118,125 / 997,112.5) ^ (365 / 90) - 1
    assert s["annual_effective_cost_percent"] == pytest.approx(((1118125 / 997112.5) ** (365 / 90) - 1) * 100, abs=5e-5)
    assert s["annual_effective_cost_percent"] == 59.1287
    y360 = revolving.spot(1000000, "0.45", 90, bsmv="0.05", fee=2750, cost_year_days=360)
    assert y360["annual_effective_cost_percent"] == pytest.approx(((1118125 / 997112.5) ** 4 - 1) * 100, abs=5e-5)
    assert y360["annual_effective_cost_percent"] == 58.1193  # one point lower only because the year is shorter
    # 100,000 blocked without interest: 897,112.50 received, 1,018,125.00 paid net of the release
    blocked = revolving.spot(1000000, "0.45", 90, bsmv="0.05", fee=2750, blocked=100000)
    assert blocked["net_received"] == 897112.5
    assert blocked["annual_effective_cost_percent"] == pytest.approx(
        ((1018125 / 897112.5) ** (365 / 90) - 1) * 100, abs=5e-5
    )


def test_spot_periodic_interest():
    # 180 days with interest every 90 days: two payments of 112,500 + 5,625, principal with the second
    s = revolving.spot(1000000, "0.45", 180, bsmv="0.05", interest_days=[90, 90])
    assert [(r["day"], r["payment"]) for r in s["payments"]] == [(90, 118125.0), (180, 1118125.0)]
    assert s["interest"] == 225000.0 and s["total_repayment"] == 1236250.0
    # each 90 days cost 11.8125 % of the money in use, so the compound annual cost is 1.118125 ^ (365 / 90) - 1
    assert s["annual_effective_cost_percent"] == pytest.approx((1.118125 ** (365 / 90) - 1) * 100, abs=5e-5)
    # paying interest earlier costs more than paying the same total at maturity
    assert (
        s["annual_effective_cost_percent"]
        > revolving.spot(1000000, "0.45", 180, bsmv="0.05")["annual_effective_cost_percent"]
    )


def test_allocation_fee_cap():
    # Communiqué 2020/4 Article 9(1): 0.20 % of the limit per year, pro rata by months.
    # 5,000,000 x 0.20 % = 10,000.00 for 12 months; 5,000.00 for 6 months.
    assert rates.COMMERCIAL_ALLOCATION_FEE_CAP.value == D("0.002")
    year = revolving.allocation_fee_cap(5000000)
    assert year["allowed_maximum"] == 10000.0 and "exceeds" not in year
    half = revolving.allocation_fee_cap(5000000, 6, quoted_fee=6000)
    assert (half["allowed_maximum"], half["exceeds"], half["excess"]) == (5000.0, True, 1000.0)
    assert revolving.allocation_fee_cap(5000000, 6, quoted_fee=5000)["exceeds"] is False
    assert "2020/4" in half["basis"]


def test_utilisation_fee_cap():
    # Article 9(2), instruction 4/II/b-d: 1.10 % of the amount drawn; under a year pro rata, year 360.
    # 1,000,000 for 90 days: 1.10 % x 90 / 360 = 0.275 % = 2,750.00
    assert rates.COMMERCIAL_UTILISATION_FEE_CAP.value == D("0.011")
    spot = revolving.utilisation_fee_cap(1000000, 90, quoted_fee=3000)
    assert (spot["allowed_maximum"], spot["exceeds"], spot["excess"]) == (2750.0, True, 250.0)
    assert spot["cap_rate_for_term"] == 0.00275
    # a year or longer: the full 1.10 %, never more
    assert revolving.utilisation_fee_cap(1000000, 360)["allowed_maximum"] == 11000.0
    assert revolving.utilisation_fee_cap(1000000, 730)["allowed_maximum"] == 11000.0
    # revolving: on the average balance of the period; a quarter is 90 days.
    # 541,758.24 x 1.10 % x 90 / 360 = 1,489.84; over two years the cap grows pro rata: 22,000.00
    assert revolving.utilisation_fee_cap("541758.24", 90, revolving=True)["allowed_maximum"] == 1489.84
    assert revolving.utilisation_fee_cap(1000000, 720, revolving=True)["allowed_maximum"] == 22000.0
    # Article 9(3): no cap on loans that are not in lira
    fx = revolving.utilisation_fee_cap(1000000, 90, turkish_lira=False, quoted_fee=50000)
    assert fx["allowed_maximum"] is None and fx["exceeds"] is False


def test_fee_cap_follows_the_account_average():
    out = quarter(count_end_day=False, unpaid_interest="paid")
    cap = revolving.utilisation_fee_cap(D(str(out["periods"][0]["average_debit_balance"])), 90, revolving=True)
    assert cap["allowed_maximum"] == 1489.84


def test_inputs_are_checked():
    bad_lines = [
        dict(movements=[("2026-10-01", 5)]),  # outside the period
        dict(rates=[("2026-07-02", "0.4")]),  # no rate on the first day
        dict(rates=[("2026-07-01", "0.4"), ("2026-07-01", "0.5")]),
        dict(rates=[]),
        dict(rates=-0.1),
        dict(year_basis=364),
        dict(accrual="weekly"),
        dict(accrual=["2027-01-01"]),
        dict(unpaid_interest="forgiven"),
        dict(bsmv=2),
        dict(end="2026-06-30"),
    ]
    for bad in bad_lines:
        kw = dict(opening_balance=0, movements=MOVES, start="2026-07-01", end="2026-09-30", rates="0.4")
        kw.update(bad)
        with pytest.raises(InputError):
            revolving.line(**kw)
    for bad in (
        dict(principal=0),
        dict(days=0),
        dict(days=2.5),
        dict(annual_rate=True),
        dict(interest_days=[30, 30]),
        dict(year_basis=30),
        dict(cost_year_days=366),
        dict(blocked=1000),
    ):
        kw = dict(principal=1000, annual_rate="0.4", days=90)
        kw.update(bad)
        with pytest.raises(InputError):
            revolving.spot(**kw)
    with pytest.raises(InputError):
        revolving.allocation_fee_cap(0)
    with pytest.raises(InputError):
        revolving.allocation_fee_cap(1000, 0)
    with pytest.raises(InputError):
        revolving.allocation_fee_cap(1000, on="2020-05-01")  # the table has no cap for that date
    with pytest.raises(InputError):
        revolving.utilisation_fee_cap(1000, 90, quoted_fee=-1)
