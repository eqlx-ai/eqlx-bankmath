"""Worked examples printed in the annexes of the Turkish consumer credit and housing finance regulations.

TKSY = Tüketici Kredisi Sözleşmeleri Yönetmeliği (Official Gazette 22.05.2015, no. 29363), Ek 1-5.
KFSY = Konut Finansmanı Sözleşmeleri Yönetmeliği (Official Gazette 28.05.2015, no. 29369), Ek 1.
The annexes date from 2015 and use KKDF 15 % and BSMV 5 % for consumer loans.
"""

from decimal import Decimal as D

import pytest

from eqlx_bankmath import costrate, installment
from eqlx_bankmath.errors import InputError

CONSUMER_2015 = dict(kkdf="0.15", bsmv="0.05")


def row(r):
    return (r.payment, r.interest, r.kkdf, r.bsmv, r.principal, r.balance)


def test_tksy_ek1_twelve_month_plan_to_the_kurus():
    p = installment.plan(10000, "0.01", 12, fee=50, start="2015-05-04", **CONSUMER_2015)
    assert p.gross_rate == D("0.012")
    printed = [
        ("899.75", "100.00", "15.00", "5.00", "779.75", "9220.25"),
        ("899.75", "92.20", "13.83", "4.61", "789.11", "8431.14"),
        ("899.75", "84.31", "12.65", "4.22", "798.57", "7632.57"),
        ("899.75", "76.33", "11.45", "3.82", "808.15", "6824.42"),
        ("899.75", "68.24", "10.24", "3.41", "817.86", "6006.56"),
        ("899.75", "60.07", "9.01", "3.00", "827.67", "5178.89"),
        ("899.75", "51.79", "7.77", "2.59", "837.60", "4341.29"),
        ("899.75", "43.41", "6.51", "2.17", "847.66", "3493.63"),
        ("899.75", "34.94", "5.24", "1.75", "857.82", "2635.81"),
        ("899.75", "26.36", "3.95", "1.32", "868.12", "1767.69"),
        ("899.75", "17.68", "2.65", "0.88", "878.54", "889.15"),
        ("899.81", "8.89", "1.33", "0.44", "889.15", "0.00"),
    ]
    assert [row(r) for r in p.rows] == [tuple(D(x) for x in line) for line in printed]
    assert (p.total("payment"), p.total("interest"), p.total("kkdf"), p.total("bsmv")) == (
        D("10797.06"),
        D("664.22"),
        D("99.63"),
        D("33.21"),
    )
    assert p.rows[0].date.isoformat() == "2015-06-04" and p.rows[-1].date.isoformat() == "2016-05-04"


def test_tksy_ek1_annual_rate():
    # The annex prints X = 16.48698695 % and "16.4870 %". Solving its own equation for its own cash
    # flows gives 16.4872 %; with the printed X the two sides differ by one kuruş. The schedule is
    # matched exactly above; the rate is matched to the precision the printed figure really has.
    p = installment.plan(10000, "0.01", 12, fee=50, **CONSUMER_2015)
    x = p.annual_cost_rate()
    assert costrate.as_percent(x) == D("16.4872")
    assert abs(x * 100 - D("16.48698695")) < D("0.0005")
    flows = [(D(0), D(50)), *installment.flows(p)]
    assert abs(costrate.present_value(flows, D("0.1648698695")) - 10000) < D("0.02")
    assert abs(costrate.present_value(flows, x) - 10000) < D("0.000001")


def test_kfsy_ek1_housing_plan_and_rate():
    p = installment.plan(10000, "0.01", 12, fee=50)
    assert [r.payment for r in p.rows] == [D("888.49")] * 11 + [D("888.47")]
    assert [r.interest for r in p.rows[:3]] == [D("100.00"), D("92.12"), D("84.15")]
    assert (p.total("payment"), p.total("interest"), p.total("kkdf")) == (D("10661.86"), D("661.86"), D("0.00"))
    # printed: 13.7504347849644 %, which is the rate of twelve unrounded instalments
    assert abs(p.annual_cost_rate() * 100 - D("13.7504347849644")) < D("0.0005")
    unrounded = installment.annuity_payment(D(10000), D("0.01"), 12)
    exact = costrate.annual_cost_rate([(0, 10000)], [(0, 50)] + [(D(k) / 12, unrounded) for k in range(1, 13)])
    assert abs(exact * 100 - D("13.7504347849644")) < D("0.00001")


@pytest.fixture
def ek2():
    return installment.plan(50000, "0.01", 36, start="2015-01-03", **CONSUMER_2015)


def test_tksy_ek2_thirty_six_month_plan(ek2):
    checked = {  # rows compared with the scanned annex
        1: ("1718.61", "500.00", "75.00", "25.00", "1118.61", "48881.39"),
        2: ("1718.61", "488.81", "73.32", "24.44", "1132.04", "47749.35"),
        6: ("1718.61", "442.71", "66.41", "22.14", "1187.35", "43083.73"),
        7: ("1718.61", "430.84", "64.63", "21.54", "1201.60", "41882.13"),
        9: ("1718.61", "406.66", "61.00", "20.33", "1230.62", "39435.48"),
        10: ("1718.61", "394.35", "59.15", "19.72", "1245.39", "38190.09"),
        12: ("1718.61", "369.30", "55.40", "18.47", "1275.44", "35654.33"),
        20: ("1718.61", "262.87", "39.43", "13.14", "1403.17", "24884.02"),
        26: ("1718.61", "176.12", "26.42", "8.81", "1507.26", "16104.30"),
        31: ("1718.61", "98.92", "14.84", "4.95", "1599.90", "8292.26"),
        35: ("1718.61", "33.76", "5.06", "1.69", "1678.10", "1698.34"),
        36: ("1718.72", "16.98", "2.55", "0.85", "1698.34", "0.00"),
    }
    for k, line in checked.items():
        assert row(ek2.rows[k - 1]) == tuple(D(x) for x in line), k
    assert (
        ek2.total("payment"),
        ek2.total("interest"),
        ek2.total("kkdf"),
        ek2.total("bsmv"),
        ek2.total("principal"),
    ) == (
        D("61870.07"),
        D("9891.67"),
        D("1483.79"),
        D("494.61"),
        D("50000.00"),
    )


def test_tksy_ek2_full_early_repayment(ek2):
    # Example 1: on the 7th due date the borrower pays the 7th instalment and the remaining principal: 43,600.74
    on_date = installment.payoff(ek2, 7)
    assert D(str(on_date["payoff"])) + ek2.rows[6].payment == D("43600.74")
    # Example 2: 21 days after the 6th due date. Interest 301.59, BSMV 15.08.
    between = installment.payoff(ek2, 6, 21)
    assert (between["interest"], between["bsmv"]) == (301.59, 15.08)
    # The annex prints KKDF 45.23 and a total of 43,445.63, but 301.59 x 15 % = 45.2385, which rounds
    # half-up to 45.24 like every other figure in the annexes. The printed figure is one kuruş short.
    assert between["kkdf"] == 45.24 and between["payoff"] == 43445.64


def test_tksy_ek4_partial_prepayment(ek2):
    # Example 1: 10,000 paid on the 10th due date; 8,281.39 beyond the instalment reduces the principal.
    after = installment.prepay(ek2, 10, D(10000) - ek2.rows[9].payment)
    assert after.principal == D("29908.70") and after.n == 26 and after.instalment == D("1345.94")
    # Example 2: 10,000 paid on 24.10.2015, 21 days after the 9th due date and 10 days before the 10th.
    between = installment.prepay(ek2, 9, 10000, days_since_last_due=21, days_to_next_due=10)
    assert between.principal == D("29766.74") and between.n == 26 and between.instalment == D("1344.88")


def test_tksy_ek5_late_instalment(ek2):
    # The 10th instalment is paid 10 days late; it contains 1,245.39 of principal; default rate 1.3 %.
    late = installment.late_interest(ek2.rows[9].principal, "0.01", 10, **CONSUMER_2015)
    assert (late["default_monthly_rate"], late["interest"], late["kkdf"], late["bsmv"], late["total"]) == (
        0.013,
        5.40,
        0.81,
        0.27,
        6.48,
    )
    assert D(str(late["total"])) + ek2.rows[9].payment == D("1725.09")
    assert installment.late_interest(1000, "0.01", 10, multiplier="1.5")["above_legal_cap"] is True


def test_housing_compensation_limits():
    # Law 6502 Article 37: 1 % up to 36 months of remaining term, 2 % beyond, never above the interest saved
    assert installment.housing_prepayment_compensation(100000, 36)["maximum_compensation"] == 1000.0
    assert installment.housing_prepayment_compensation(100000, 37)["maximum_compensation"] == 2000.0
    assert installment.housing_prepayment_compensation(100000, 60, interest_saved=750)["maximum_compensation"] == 750.0


def test_inputs_are_checked():
    for bad in (dict(principal=0), dict(monthly_rate=-0.01), dict(n=0), dict(n=2.5), dict(kkdf=1.5), dict(method="x")):
        kw = dict(principal=1000, monthly_rate="0.01", n=12)
        kw.update(bad)
        with pytest.raises(InputError):
            installment.plan(**kw)
    with pytest.raises(InputError):
        installment.plan(1000, "0.01", 12, interest_only_periods=12)
    with pytest.raises(InputError):
        installment.plan(1000, "0.01", 12, balloon=1000)
    with pytest.raises(InputError):
        installment.plan(1000, True, 12)  # a boolean is not a rate
