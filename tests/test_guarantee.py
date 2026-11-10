"""Letter-of-guarantee commissions and the commercial fee caps of TCMB Communiqué 2020/4.

There is no official worked example of a guarantee commission: no rule fixes the formula. The
complete example (10,000,000 TL, three conventions) is the one worked out in the research note for
this module and reproduced by its check script; all other cases are computed by hand in the
comments. Expected values are literals, never the implementation's own expression.
"""

from decimal import Decimal as D

import pytest

from eqlx_bankmath import guarantee
from eqlx_bankmath.costrate import as_percent
from eqlx_bankmath.errors import InputError

# 10,000,000 TL, 15.01.2026 - 15.01.2027, 2.40 % a year, quarterly in advance, minimum 2,000, BSMV 5 %;
# 4,000,000 released on 15.06.2026 (end of month 5), letter returned on 02.11.2026 (month 10).
NOTE = dict(
    bsmv="0.05",
    expiry_date="2027-01-15",
    return_date="2026-11-02",
    minimum_commission=2000,
    reductions=[("2026-06-15", 4_000_000)],
)


def note(**conventions):
    return guarantee.commission_schedule(10_000_000, "0.024", "2026-01-15", **NOTE, **conventions)


def col(schedule, name):
    return [getattr(r, name) for r in schedule.rows]


def amounts(*values):
    return [D(v) for v in values]


def test_note_example_started_period_in_full_without_refund():
    s = note()
    assert [(r.start.isoformat(), r.end.isoformat()) for r in s.rows] == [
        ("2026-01-15", "2026-04-15"),
        ("2026-04-15", "2026-07-15"),
        ("2026-07-15", "2026-10-15"),
        ("2026-10-15", "2027-01-15"),
    ]
    # the release on 15.06 falls inside period 2 and the return inside period 4: neither changes them
    assert col(s, "amount") == amounts("10000000", "10000000", "6000000", "6000000")
    assert col(s, "commission") == amounts("60000.00", "60000.00", "36000.00", "36000.00")
    assert col(s, "refund") == amounts("0", "0", "0", "0")
    assert col(s, "bsmv") == amounts("3000.00", "3000.00", "1800.00", "1800.00")
    assert col(s, "minimum_applied") == [False] * 4
    assert (s.commission, s.bsmv, s.cost) == (D("192000.00"), D("9600.00"), D("201600.00"))
    # 10,000,000 x 151 days + 6,000,000 x 140 days = 2,350,000,000 over 291 days
    assert (s.life_days, s.amount_days, s.average_outstanding) == (291, D("2350000000"), D("8075601.37"))
    # 201,600 x 360 / 2,350,000,000 = 3.0883 %; without BSMV 192,000 x 360 / 2,350,000,000 = 2.9413 %
    assert as_percent(s.effective_annual_cost) == D("3.0883")
    assert as_percent(s.effective_annual_cost_excluding_bsmv) == D("2.9413")


def test_note_example_by_days_with_refund():
    s = note(started_period="pro_rata")
    assert col(s, "days") == [90, 91, 92, 92]
    assert col(s, "collected") == amounts("60000.00", "60666.67", "36800.00", "36800.00")
    # period 2: 4,000,000 x 2.40 % x 30/360 (15.06 - 15.07); period 4: 6,000,000 x 2.40 % x 74/360 (02.11 - 15.01)
    assert col(s, "refund") == amounts("0", "8000.00", "0", "29600.00")
    assert col(s, "commission") == amounts("60000.00", "52666.67", "36800.00", "7200.00")
    assert col(s, "bsmv") == amounts("3000.00", "2633.33", "1840.00", "360.00")
    assert (s.total("collected"), s.total("refund")) == (D("194266.67"), D("37600.00"))
    # plain accrual on what was outstanding: 2,350,000,000 x 2.40 % / 360 = 156,666.67
    assert (s.commission, s.bsmv, s.cost) == (D("156666.67"), D("7833.33"), D("164500.00"))
    assert as_percent(s.effective_annual_cost) == D("2.5200")  # the quoted 2.40 % plus 5 % BSMV
    assert as_percent(s.effective_annual_cost_excluding_bsmv) == D("2.4000")


def test_note_example_bsmv_not_given_back_on_refunds():
    s = note(started_period="pro_rata", refund_bsmv=False)
    # BSMV on what was collected: 3,000.00 + 3,033.33 + 1,840.00 + 1,840.00
    assert (s.commission, s.bsmv, s.cost) == (D("156666.67"), D("9713.33"), D("166380.00"))


def test_note_example_full_periods_but_return_refunded():
    s = note(refund_on_return=True)
    # last quarter 15.10 - 15.01 (92 days) charged in full: 36,000.00. Returned on 02.11 with 74 days left:
    # refund 36,000 x 74 / 92 = 28,956.52, so the 18 days the letter was outstanding stay paid for.
    assert col(s, "refund") == amounts("0", "0", "0", "28956.52")
    assert (s.commission, s.bsmv, s.cost) == (D("163043.48"), D("8152.17"), D("171195.65"))
    assert as_percent(s.effective_annual_cost) == D("2.6226")


def test_same_letter_costs_differently_under_the_conventions():
    full, mixed, by_days = note(), note(refund_on_return=True), note(started_period="pro_rata")
    assert full.cost > mixed.cost > by_days.cost
    assert full.cost - by_days.cost == D("37100.00")  # 201,600.00 - 164,500.00
    assert full.annual_rate == mixed.annual_rate == by_days.annual_rate == D("0.024")
    assert full.average_outstanding == by_days.average_outstanding
    assert full.conventions != by_days.conventions
    assert "charged in full" in full.conventions["started_period"]
    assert "by days" in by_days.conventions["started_period"]
    assert full.conventions["refund_on_return"].startswith("none")
    assert by_days.conventions["refund_on_reduction"].startswith("released amount")


def test_collection_in_arrears():
    # 1,200,000 at 3 % a year, six months: 1,200,000 x 0.03 x 3/12 = 9,000.00 a quarter, BSMV 450.00
    kw = dict(bsmv="0.05", expiry_date="2026-09-01")
    s = guarantee.commission_schedule(1_200_000, "0.03", "2026-03-01", collection="arrears", **kw)
    assert [r.collection_date.isoformat() for r in s.rows] == ["2026-06-01", "2026-09-01"]
    assert col(s, "collected") == amounts("9000.00", "9000.00")
    assert s.cost == D("18900.00")
    in_advance = guarantee.commission_schedule(1_200_000, "0.03", "2026-03-01", **kw)
    assert [r.collection_date.isoformat() for r in in_advance.rows] == ["2026-03-01", "2026-06-01"]
    assert in_advance.cost == s.cost
    assert "arrears" in s.conventions["collection"] and "advance" in in_advance.conventions["collection"]


def test_in_arrears_by_days_collects_only_the_days_used():
    # returned on 16.07.2026. Period 1 (01.03 - 01.06, 92 days): 1,200,000 x 0.03 x 92/360 = 9,200.00
    # period 2 runs 01.06 - 16.07 = 45 days: 1,200,000 x 0.03 x 45/360 = 4,500.00, collected on the return date
    s = guarantee.commission_schedule(
        1_200_000,
        "0.03",
        "2026-03-01",
        bsmv="0.05",
        expiry_date="2026-09-01",
        return_date="2026-07-16",
        collection="arrears",
        started_period="pro_rata",
    )
    assert col(s, "collected") == amounts("9200.00", "4500.00")
    assert col(s, "refund") == amounts("0", "0")  # nothing was prepaid, so nothing is paid back
    assert s.rows[1].collection_date.isoformat() == "2026-07-16"
    assert (s.commission, s.bsmv, s.cost) == (D("13700.00"), D("685.00"), D("14385.00"))  # BSMV 460 + 225


def test_minimum_that_binds():
    # 50,000 x 2.40 % x 3/12 = 300.00 a quarter, below the 2,000.00 minimum; BSMV 100.00 a quarter
    s = guarantee.commission_schedule(
        50_000, "0.024", "2026-01-15", bsmv="0.05", expiry_date="2026-07-15", minimum_commission=2000
    )
    assert col(s, "commission") == amounts("2000.00", "2000.00")
    assert col(s, "minimum_applied") == [True, True]
    assert s.cost == D("4200.00")
    # a tariff with a minimum of 2,000 a month and 5 % a year: max(50,000 x 5 % x 3/12 = 625, 3 x 2,000) = 6,000
    monthly = guarantee.commission_schedule(
        50_000, "0.05", "2026-01-15", bsmv="0.05", expiry_date="2026-04-15", minimum_commission=3 * 2000
    )
    assert col(monthly, "commission") == amounts("6000.00")
    assert note().conventions["minimum_commission"].startswith("2000 per period")


def test_minimum_limits_a_refund():
    # 1,000,000 at 3.60 %, by days: period 1 (01.01 - 01.04, 90 days) collects 1,000,000 x 0.036 x 90/360 = 9,000.00
    # returned 31.01: 60 unused days would give back 1,000,000 x 0.036 x 60/360 = 6,000.00 and leave 3,000.00,
    # below the 5,000.00 minimum, so only 4,000.00 comes back
    s = guarantee.commission_schedule(
        1_000_000,
        "0.036",
        "2026-01-01",
        bsmv="0.05",
        expiry_date="2026-07-01",
        return_date="2026-01-31",
        started_period="pro_rata",
        minimum_commission=5000,
    )
    assert len(s.rows) == 1
    assert (s.rows[0].collected, s.rows[0].refund, s.rows[0].commission) == (D("9000.00"), D("4000.00"), D("5000.00"))
    assert s.rows[0].minimum_applied is True
    assert s.cost == D("5250.00")


def test_refund_is_never_more_than_the_period_was_charged():
    # full quarter 01.07 - 01.10 (92 days): 3,600,000 x 3.60 % x 3/12 = 32,400.00 collected.
    # returned the next day: 91 unused days at /360 would be 32,760.00, more than was collected.
    # The refund is the unused share of the charge instead: 32,400 x 91/92 = 32,047.83; one day costs 352.17 + 17.61 BSMV.
    s = guarantee.commission_schedule(
        3_600_000,
        "0.036",
        "2026-07-01",
        bsmv="0.05",
        expiry_date="2027-07-01",
        return_date="2026-07-02",
        refund_on_return=True,
    )
    assert (s.rows[0].collected, s.rows[0].refund, s.cost) == (D("32400.00"), D("32047.83"), D("369.78"))


def test_rate_quoted_per_three_months():
    # 400,000 at 1.50 % per three months: 400,000 x 0.015 = 6,000.00 a quarter, BSMV 300.00; two quarters
    kw = dict(bsmv="0.05", expiry_date="2026-08-10")
    s = guarantee.commission_schedule(400_000, "0.015", "2026-02-10", rate_period_months=3, **kw)
    assert col(s, "commission") == amounts("6000.00", "6000.00")
    assert (s.annual_rate, s.cost) == (D("0.06"), D("12600.00"))
    assert s.conventions["rate"].startswith("0.015 per 3 months")
    # the same number read as a yearly rate is a quarter of that: 400,000 x 0.015 x 3/12 = 1,500.00
    yearly = guarantee.commission_schedule(400_000, "0.015", "2026-02-10", **kw)
    assert col(yearly, "commission") == amounts("1500.00", "1500.00")
    # collected monthly, the three-month rate gives 400,000 x 0.015 / 3 = 2,000.00 a month
    monthly = guarantee.commission_schedule(400_000, "0.015", "2026-02-10", rate_period_months=3, period_months=1, **kw)
    assert col(monthly, "commission") == amounts(*["2000.00"] * 6)


def test_monthly_periods_bid_bond():
    # 90,000 at 4.80 % a year, monthly, 10.03.2026 - 25.05.2026: periods 10.03-10.04, 10.04-10.05, 10.05-25.05
    kw = dict(bsmv="0.05", expiry_date="2026-05-25", period_months=1)
    full = guarantee.commission_schedule(90_000, "0.048", "2026-03-10", **kw)
    # 90,000 x 0.048 / 12 = 360.00 for each started month, the 15-day one too; BSMV 18.00 each
    assert col(full, "commission") == amounts("360.00", "360.00", "360.00")
    assert full.rows[-1].end.isoformat() == "2026-05-25"
    assert full.cost == D("1134.00")
    by_days = guarantee.commission_schedule(90_000, "0.048", "2026-03-10", started_period="pro_rata", **kw)
    # 90,000 x 0.048 / 360 = 12.00 a day: 31, 30 and 15 days
    assert col(by_days, "days") == [31, 30, 15]
    assert col(by_days, "commission") == amounts("372.00", "360.00", "180.00")
    assert col(by_days, "bsmv") == amounts("18.60", "18.00", "9.00")
    assert by_days.cost == D("957.60")


def test_letter_returned_inside_the_first_period():
    # 2,000,000 at 3 % a year, issued 20.01.2026, returned 19.02.2026 (30 days)
    kw = dict(bsmv="0.05", expiry_date="2027-01-20", return_date="2026-02-19")
    full = guarantee.commission_schedule(2_000_000, "0.03", "2026-01-20", **kw)
    # the whole first quarter: 2,000,000 x 0.03 x 3/12 = 15,000.00 + BSMV 750.00, for 30 days of cover
    assert len(full.rows) == 1
    assert full.cost == D("15750.00")
    assert (full.life_days, full.average_outstanding) == (30, D("2000000.00"))
    # 15,750 / 2,000,000 / (30/360) = 9.45 % a year against a quoted 3 %
    assert as_percent(full.effective_annual_cost) == D("9.4500")
    by_days = guarantee.commission_schedule(2_000_000, "0.03", "2026-01-20", started_period="pro_rata", **kw)
    # collected for 90 days (20.01 - 20.04): 15,000.00; 60 unused days back: 2,000,000 x 0.03 x 60/360 = 10,000.00
    assert (by_days.rows[0].collected, by_days.rows[0].refund) == (D("15000.00"), D("10000.00"))
    assert by_days.cost == D("5250.00")
    assert as_percent(by_days.effective_annual_cost) == D("3.1500")


SEVERAL = [("2026-03-01", 3_000_000), ("2026-04-01", 2_000_000), ("2026-05-01", 1_000_000), ("2026-06-01", 1_000_000)]


def test_several_reductions_full_periods():
    # 9,000,000 at 2 % a year, 01.01.2026 - 01.01.2027. Outstanding at the quarter starts:
    # 01.01: 9,000,000; 01.04: 4,000,000 (the release dated 01.04 counts); 01.07 and 01.10: 2,000,000
    s = guarantee.commission_schedule(
        9_000_000, "0.02", "2026-01-01", bsmv="0.05", expiry_date="2027-01-01", reductions=SEVERAL
    )
    assert col(s, "amount") == amounts("9000000", "4000000", "2000000", "2000000")
    # a quarter costs 0.5 % of the amount
    assert col(s, "commission") == amounts("45000.00", "20000.00", "10000.00", "10000.00")
    assert (s.commission, s.bsmv, s.cost) == (D("85000.00"), D("4250.00"), D("89250.00"))


def test_several_reductions_by_days_actual_365():
    s = guarantee.commission_schedule(
        9_000_000,
        "0.02",
        "2026-01-01",
        bsmv="0.05",
        expiry_date="2027-01-01",
        reductions=SEVERAL,
        started_period="pro_rata",
        day_count="actual/365",
    )
    # Q1 90 days: 9,000,000 x 0.02 x 90/365 = 44,383.56; release 01.03, 31 days left: 3,000,000 x 0.02 x 31/365 = 5,095.89
    # Q2 91 days: 4,000,000 x 0.02 x 91/365 = 19,945.21; releases 01.05 (61 days left) 3,342.47 and 01.06 (30 days) 1,643.84
    # Q3, Q4 92 days: 2,000,000 x 0.02 x 92/365 = 10,082.19; the release on 01.04 is a period start: no refund
    assert col(s, "collected") == amounts("44383.56", "19945.21", "10082.19", "10082.19")
    assert col(s, "refund") == amounts("5095.89", "4986.31", "0", "0")
    assert col(s, "bsmv") == amounts("1964.38", "747.95", "504.11", "504.11")
    assert (s.commission, s.bsmv, s.cost) == (D("74410.95"), D("3720.55"), D("78131.50"))
    # amount-days: 9M x 59 + 6M x 31 + 4M x 30 + 3M x 31 + 2M x 214 = 1,358,000,000 over 365 days
    assert (s.life_days, s.amount_days, s.average_outstanding) == (365, D("1358000000"), D("3720547.95"))
    # accrual 1,358,000,000 x 0.02 / 365 = 74,410.96: the schedule is within the rounding of its six pieces
    assert abs(s.commission - D("74410.96")) <= D("0.03")
    assert as_percent(s.effective_annual_cost_excluding_bsmv) == D("2.0000")


def test_open_ended_letter_runs_until_it_is_returned():
    # no expiry; 600,000 at 4 % a year, issued 05.01.2026, returned 20.08.2026: three quarters have started
    s = guarantee.commission_schedule(600_000, "0.04", "2026-01-05", bsmv="0.05", return_date="2026-08-20")
    # 600,000 x 0.04 x 3/12 = 6,000.00 a quarter
    assert col(s, "commission") == amounts("6000.00", "6000.00", "6000.00")
    assert (s.end_date.isoformat(), s.rows[-1].end.isoformat()) == ("2026-08-20", "2026-10-05")


def test_published_single_period_examples():
    # practitioner article: 3,500,000 at 0.1 % a year for 180 days by days/360 = 1,750.00, with BSMV 1,837.50
    s = guarantee.commission_schedule(
        3_500_000,
        "0.001",
        "2026-01-01",
        bsmv="0.05",
        expiry_date="2026-06-30",
        period_months=6,
        started_period="pro_rata",
    )
    assert (s.rows[0].days, s.commission, s.cost) == (180, D("1750.00"), D("1837.50"))
    # comparison site: 750,000 at 4 % a year, 7,500 a quarter, BSMV 375, 7,875 paid
    q = guarantee.commission_schedule(750_000, "0.04", "2026-01-01", bsmv="0.05", expiry_date="2026-04-01")
    assert (q.commission, q.bsmv, q.cost) == (D("7500.00"), D("375.00"), D("7875.00"))


def test_bsmv_is_an_input_and_json_output_is_plain():
    exempt = guarantee.commission_schedule(750_000, "0.04", "2026-01-01", bsmv=0, expiry_date="2026-04-01")
    assert exempt.cost == D("7500.00")
    out = note().to_dict()
    assert out["totals"] == {
        "collected": 192000.0,
        "refund": 0.0,
        "commission": 192000.0,
        "bsmv": 9600.0,
        "cost": 201600.0,
    }
    assert out["effective_annual_cost_percent"] == 3.0883
    assert out["average_outstanding"] == 8075601.37
    assert out["periods"][2]["amount"] == 6000000.0 and out["periods"][2]["total"] == 37800.0
    assert set(out["conventions"]) >= {
        "legal_basis",
        "rate",
        "period_months",
        "collection",
        "started_period",
        "day_count",
        "minimum_commission",
        "refund_on_reduction",
        "refund_on_return",
        "bsmv",
        "rounding",
        "effective_annual_cost",
    }


@pytest.mark.parametrize(
    "change",
    [
        dict(amount=0),
        dict(commission_rate="-0.01"),
        dict(commission_rate=2.4),  # a percentage where a fraction is expected
        dict(bsmv=True),
        dict(bsmv="1.5"),
        dict(expiry_date="2026-01-15"),
        dict(expiry_date=None, return_date=None),
        dict(return_date="2027-02-01"),  # after expiry
        dict(return_date="2026-01-15"),
        dict(period_months=0),
        dict(rate_period_months=0),
        dict(collection="monthly"),
        dict(started_period="half"),
        dict(day_count="actual/actual"),
        dict(minimum_commission=-1),
        dict(reductions=[("2026-01-15", 1_000_000)]),  # on the issue date
        dict(reductions=[("2026-11-02", 1_000_000)]),  # on the return date
        dict(reductions=[("2026-06-15", 10_000_000)]),  # releases everything
        dict(reductions=[("2026-06-15", -5)]),
        dict(reductions=[("15.06.2026", 1_000_000)]),
        dict(started_period="pro_rata", refund_on_return=False),
        dict(started_period="pro_rata", refund_on_reduction=False),
        dict(refund_on_return="yes"),
    ],
)
def test_input_validation(change):
    args = dict(amount=10_000_000, commission_rate="0.024", issue_date="2026-01-15", **NOTE)
    args.update(change)
    with pytest.raises(InputError):
        guarantee.commission_schedule(**args)


def test_bsmv_has_no_default():
    with pytest.raises(TypeError):
        guarantee.commission_schedule(1000, "0.02", "2026-01-01", expiry_date="2026-04-01")


def test_allocation_fee_cap():
    # 0.20 % a year: 20,000,000 x 0.002 = 40,000.00; nine months 30,000.00; +5,000,000 for six months 5,000.00
    assert guarantee.allocation_fee_cap(20_000_000, 0, 12, "2026-03-01").maximum == D("40000.00")
    assert guarantee.allocation_fee_cap(20_000_000, 0, 9, "2026-03-01").maximum == D("30000.00")
    assert guarantee.allocation_fee_cap(0, 5_000_000, 6, "2026-03-01").maximum == D("5000.00")
    # the limit for letters of guarantee counts: 12,000,000 cash + 8,000,000 non-cash is the same 20,000,000
    c = guarantee.allocation_fee_cap(12_000_000, 8_000_000, 12, "2026-03-01", quoted_fee=45_000)
    assert (c.base, c.cap_rate, c.maximum) == (D("20000000"), D("0.0020"), D("40000.00"))
    assert (c.exceeds, c.excess) == (True, D("5000.00"))
    assert "Article 9(1)" in c.basis and "2025/24" in c.basis and c.since.isoformat() == "2025-11-01"
    at_cap = guarantee.allocation_fee_cap(12_000_000, 8_000_000, 12, "2026-03-01", quoted_fee="40000.00")
    assert (at_cap.exceeds, at_cap.excess) == (False, D("0"))
    assert guarantee.allocation_fee_cap(1_000_000, 0, 12, "2025-11-01").exceeds is None
    out = c.to_dict()
    assert (out["maximum"], out["quoted"], out["exceeds"], out["since"]) == (40000.0, 45000.0, True, "2025-11-01")
    assert "BSMV" in out["conventions"]["bsmv"]


def test_collateral_cost_cap():
    # appraisal invoice 12,000.00 plus 15 % = 13,800.00
    c = guarantee.collateral_cost_cap(12_000, "2026-06-01", quoted_fee=15_000)
    assert (c.maximum, c.exceeds, c.excess) == (D("13800.00"), True, D("1200.00"))
    assert "Article 10(1)" in c.basis
    assert guarantee.collateral_cost_cap(12_000, "2026-06-01", quoted_fee="13800.00").exceeds is False
    assert guarantee.collateral_cost_cap(12_000, "2026-06-01", quoted_fee="13800.01").exceeds is True
    # 3,333.33 x 1.15 = 3,833.3295 -> 3,833.33
    assert guarantee.collateral_cost_cap("3333.33", "2026-06-01").maximum == D("3833.33")


def test_caps_refuse_dates_and_inputs_they_do_not_cover():
    with pytest.raises(InputError):  # before the 0.20 % wording took effect; the earlier cap was different
        guarantee.allocation_fee_cap(20_000_000, 0, 12, "2025-10-31")
    with pytest.raises(InputError):
        guarantee.collateral_cost_cap(12_000, "2024-01-01")
    with pytest.raises(InputError):
        guarantee.allocation_fee_cap(0, 0, 12, "2026-03-01")
    with pytest.raises(InputError):
        guarantee.allocation_fee_cap(1_000_000, 0, 0, "2026-03-01")
    with pytest.raises(InputError):
        guarantee.allocation_fee_cap(1_000_000, 0, 12, "2026-03-01", quoted_fee=-1)
    with pytest.raises(InputError):
        guarantee.collateral_cost_cap(0, "2026-06-01")
