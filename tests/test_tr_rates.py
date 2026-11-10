import datetime as dt
from decimal import Decimal as D

import pytest

from eqlx_bankmath.errors import InputError
from eqlx_bankmath.tr import rates


def test_consumer_bsmv_by_disbursement_date():
    # 5 % until 10.06.2022, 10 % from 11.06.2022 (Decision 5729), 15 % from 07.07.2023 (Decision 7345)
    for day, expected in (
        ("2022-06-10", "0.05"),
        ("2022-06-11", "0.10"),
        ("2023-07-06", "0.10"),
        ("2023-07-07", "0.15"),
        ("2026-11-10", "0.15"),
    ):
        got = rates.levies("consumer", dt.date.fromisoformat(day))
        assert got["bsmv"] == D(expected), day
        assert got["kkdf"] == D("0.15")
    assert "7345" in rates.levies("consumer", dt.date(2026, 11, 10))["bsmv_basis"]


def test_housing_and_commercial():
    home = rates.levies("housing_first_home", dt.date(2026, 11, 10))
    assert (home["kkdf"], home["bsmv"]) == (0, 0)
    tl = rates.levies("commercial_tl", dt.date(2026, 11, 10))
    fx = rates.levies("commercial_fx", dt.date(2026, 11, 10))
    assert (tl["kkdf"], tl["bsmv"], fx["kkdf"], fx["bsmv"]) == (0, D("0.05"), D("0.01"), D("0.05"))


def test_dates_outside_the_table_and_unknown_products():
    with pytest.raises(InputError, match="before 2025-07-19"):
        rates.levies("commercial_tl", dt.date(2024, 1, 1))  # earlier decrees are not recorded
    with pytest.raises(InputError, match="unknown product"):
        rates.levies("leasing", dt.date(2026, 1, 1))  # type: ignore[arg-type]
    assert rates.levies("consumer", dt.date(2026, 11, 10))["table_checked_on"] == "2026-11-10"
    assert rates.CONSUMER_ALLOCATION_FEE_CAP.value == D("0.005") and rates.DEFAULT_RATE_MULTIPLIER_CAP.value == D("1.3")
