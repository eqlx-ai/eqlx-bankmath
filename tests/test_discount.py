"""Discounting bills and cheques.

Published figures: the open lecture note "İskonto Hesapları" of Ankara Üniversitesi (examples 3, 4,
6 and 7; year of 360 days) and Altuğ & Ünkaya, Banka İşlemleri ve Muhasebesi, Marmara Üniversitesi
1991, p. 201 (year of 365 days). The remaining cases are worked by hand in the comments.
"""

import pytest

from eqlx_bankmath import discount
from eqlx_bankmath.errors import InputError


def test_lecture_note_external_discount():
    # Example 3: 8,000 for 120 days at 27 %: 8,000 x 120 x 0.27 / 360 = 720
    assert discount.discount(8000, "0.27", 120)["discount"] == 720.0
    # Example 4: 27,000 for 100 days at 40 %: discount 3,000, proceeds 24,000
    ex4 = discount.discount(27000, "0.40", 100)
    assert (ex4["discount"], ex4["proceeds_before_levies"], ex4["net_proceeds"]) == (3000.0, 24000.0, 24000.0)
    # Example 6: proceeds 35,200, 40 days, 20 %: face value 35,200 x 360 / (360 - 8) = 36,000
    assert discount.face_value_for_proceeds(35200, "0.20", 40) == 36000
    assert discount.discount(36000, "0.20", 40)["proceeds_before_levies"] == 35200.0


def test_lecture_note_internal_discount():
    # Example 7: proceeds 15,000, three months, 28 %: interest on the proceeds 15,000 x 3 x 0.28 / 12 = 1,050,
    # so the bill is 16,050 and its internal discount is 1,050.
    assert discount.face_value_for_proceeds(15000, "0.28", 90, method="internal") == 16050
    out = discount.discount(16050, "0.28", 90, method="internal")
    assert (out["discount"], out["proceeds_before_levies"]) == (1050.0, 15000.0)
    # with interest on the proceeds the rate really paid is the quoted rate
    assert out["simple_rate_on_net_percent"] == 28.0 and out["equivalent_rate_without_levies_percent"] == 28.0


def test_textbook_example_with_levies_on_365():
    # Altuğ & Ünkaya p. 201: 2,100,000 TL, 45 days, 50 %, year 365: 2,100,000 x 45 x 50 / 36500 = 129,452.05
    # (book: 129,452). Levies of 1991: KKDF 10 % = 12,945.21 and BSMV 5 % = 6,472.60. The scanned book
    # shows 12,942 and 6,473; the first does not equal 10 % of its own discount, so the arithmetic is tested.
    out = discount.discount(2100000, "0.50", 45, year_basis=365, kkdf="0.10", bsmv="0.05")
    assert (out["discount"], out["kkdf"], out["bsmv"]) == (129452.05, 12945.21, 6472.6)
    assert round(out["discount"]) == 129452 and round(out["bsmv"]) == 6473
    assert out["net_proceeds"] == 1951130.14  # 2,100,000 - 129,452.05 - 12,945.21 - 6,472.60


def test_bill_with_tax_and_fee_by_hand():
    # 500,000 TL, 75 days, 42 %, /360: 500,000 x 75 x 0.42 / 360 = 43,750.00
    # BSMV 5 % = 2,187.50; fee 1,250.00 + BSMV 62.50; net 500,000 - 47,250.00 = 452,750.00
    out = discount.discount(500000, "0.42", 75, bsmv="0.05", fee=1250)
    assert (out["discount"], out["bsmv"], out["fee"], out["bsmv_on_fee"]) == (43750.0, 2187.5, 1250.0, 62.5)
    assert out["net_proceeds"] == 452750.0
    # simple rate on the money received: 47,250 / 452,750 x 360 / 75 = 50.0939 %
    assert out["simple_rate_on_net_percent"] == 50.0939
    # without tax and fee: 0.42 / (1 - 75 x 0.42 / 360) = 0.42 / 0.9125 = 46.0274 %
    assert out["equivalent_rate_without_levies_percent"] == 46.0274
    # compound: (500,000 / 452,750) ^ (365 / 75) - 1
    assert out["annual_effective_rate_percent"] == pytest.approx(((500000 / 452750) ** (365 / 75) - 1) * 100, abs=5e-5)
    assert out["annual_effective_rate_percent"] == 62.1099
    assert out["conventions"]["year_basis"] == 360 and "external" in out["conventions"]["method"]


def test_method_and_conventions_change_the_result():
    # internal: 500,000 x 31.5 / (360 + 31.5) = 40,229.89, which is 3,520.11 less than the external discount
    internal = discount.discount(500000, "0.42", 75, method="internal")
    assert internal["discount"] == 40229.89
    # the internal discount is exactly the interest on its own proceeds: 459,770.11 x 75 x 0.42 / 360 = 40,229.88
    assert internal["proceeds_before_levies"] == 459770.11
    # year of 365: 500,000 x 75 x 0.42 / 365 = 43,150.68 (599.32 less than on 360)
    assert discount.discount(500000, "0.42", 75, year_basis=365)["discount"] == 43150.68
    # counting both the transaction day and the maturity day: 76 days, 500,000 x 76 x 0.42 / 360 = 44,333.33
    assert discount.term_days("2026-03-02", "2026-05-16") == 75
    n = discount.term_days("2026-03-02", "2026-05-16", count_both_days=True)
    assert n == 76 and discount.discount(500000, "0.42", n)["discount"] == 44333.33
    # the year of the effective rate: (500,000 / 456,250) ^ (360 / 75) instead of ^ (365 / 75)
    y360 = discount.discount(500000, "0.42", 75, cost_year_days=360)["annual_effective_rate_percent"]
    y365 = discount.discount(500000, "0.42", 75)["annual_effective_rate_percent"]
    assert y360 == pytest.approx(((500000 / 456250) ** 4.8 - 1) * 100, abs=5e-5) and y360 < y365


def test_interest_collected_in_advance():
    # 100,000 TL for 90 days at 36 %: interest 100,000 x 90 x 0.36 / 360 = 9,000.00 taken at drawdown,
    # BSMV 450.00; received 90,550.00; repaid 100,000.00
    out = discount.interest_in_advance(100000, "0.36", 90, bsmv="0.05")
    assert (out["interest_collected_in_advance"], out["bsmv"], out["net_received"]) == (9000.0, 450.0, 90550.0)
    assert (out["repaid_at_maturity"], out["total_cost"]) == (100000.0, 9450.0)
    # 0.36 / (1 - 0.09) = 39.5604 %; with the tax 9,450 / 90,550 x 4 = 41.7449 %
    assert out["equivalent_rate_without_levies_percent"] == 39.5604
    assert out["simple_rate_on_net_percent"] == 41.7449
    assert out["annual_effective_rate_percent"] == pytest.approx(((100000 / 90550) ** (365 / 90) - 1) * 100, abs=5e-5)
    # the same numbers as discounting a bill of 100,000
    bill = discount.discount(100000, "0.36", 90, bsmv="0.05")
    assert bill["net_proceeds"] == out["net_received"]
    assert bill["annual_effective_rate_percent"] == out["annual_effective_rate_percent"]


def test_inputs_are_checked():
    for bad in (
        dict(face_value=0),
        dict(annual_rate=-1),
        dict(days=0),
        dict(days=1.5),
        dict(method="commercial"),
        dict(year_basis=364),
        dict(cost_year_days=366),
        dict(kkdf=1.5),
        dict(fee=-1),
        dict(fee=2000),  # nothing left to pay out
        dict(annual_rate=5, days=90),  # the discount exceeds the face value
    ):
        kw = dict(face_value=1000, annual_rate="0.4", days=90)
        kw.update(bad)
        with pytest.raises(InputError):
            discount.discount(**kw)
    with pytest.raises(InputError):
        discount.face_value_for_proceeds(1000, 4, 90)
    with pytest.raises(InputError):
        discount.interest_in_advance(1000, "0.4", True)
    with pytest.raises(InputError):
        discount.term_days("2026-05-16", "2026-05-16")
