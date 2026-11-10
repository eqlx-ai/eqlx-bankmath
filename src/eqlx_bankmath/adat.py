"""Interest on a balance that changes from day to day (the "adat" or interest-number method).

Overdrafts, revolving lines and current accounts do not have instalments: the balance moves with
every transaction. Interest is computed from interest numbers,

    interest number (adat) = balance x days the balance stood
    interest = sum of interest numbers x annual rate / year basis        (rate as a fraction)

which is the same as charging simple interest on each day's closing balance. No law fixes the
divisor, the value-date rule or the rounding; they come from the contract and from bank practice,
so each is an explicit argument here and is echoed in the result.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .daycount import parse_date
from .errors import InputError
from .money import ZERO, Number, as_float, dec, money, rate, whole


@dataclass(frozen=True)
class Stretch:
    """A balance and the number of days it stood."""

    balance: Decimal
    days: int
    start: dt.date | None = None

    @property
    def number(self) -> Decimal:
        return self.balance * self.days


def stretches_from_movements(
    opening_balance: Number,
    movements: Sequence[tuple[dt.date | str, Number]],
    period_start: dt.date | str,
    period_end: dt.date | str,
    *,
    count_end_day: bool = False,
) -> list[Stretch]:
    """Turn dated movements into balance stretches over a period.

    ``movements`` are (value date, amount): positive amounts increase the debt, negative reduce it.
    A movement counts from its value date. The period runs from ``period_start`` up to
    ``period_end``; with ``count_end_day`` the end day itself also bears interest (some contracts
    count both the first and the last day).
    """
    start, end = parse_date(period_start, "period_start"), parse_date(period_end, "period_end")
    if end < start:
        raise InputError("the period ends before it starts")
    last_day = end + dt.timedelta(days=1) if count_end_day else end
    items = sorted((parse_date(d, "value date"), dec(a, "amount")) for d, a in movements)
    if any(d < start or d > end for d, _ in items):
        raise InputError("a movement lies outside the period")
    balance = dec(opening_balance, "opening_balance")
    out: list[Stretch] = []
    cursor = start
    for day, amount in items:
        if day > cursor:
            out.append(Stretch(balance, (day - cursor).days, cursor))
            cursor = day
        balance += amount
    if last_day > cursor:
        out.append(Stretch(balance, (last_day - cursor).days, cursor))
    return out


def interest(
    stretches: Sequence[Stretch | tuple[Number, int]],
    annual_rate: Number,
    *,
    year_basis: int = 360,
    kkdf: Number = 0,
    bsmv: Number = 0,
    debit_only: bool = True,
) -> dict[str, Any]:
    """Interest on a varying balance for one accrual period, with its levies.

    ``annual_rate`` is a fraction per year (0.60 for 60 %); for a monthly rate pass ``rate x 12``
    with ``year_basis=360``, which is the usual reading of "monthly rate x days / 30".
    With ``debit_only`` (the default) days with a zero or credit balance bear no interest.
    Interest is rounded once, on the total for the period.
    """
    r = rate(annual_rate, "annual_rate")
    basis = whole(year_basis, "year_basis", minimum=1)
    if basis not in (360, 365, 366):
        raise InputError("year_basis must be 360, 365 or 366")
    k, b = rate(kkdf, "kkdf", maximum=1), rate(bsmv, "bsmv", maximum=1)
    rows = []
    total_number = ZERO
    total_days = 0
    for s in stretches:
        st = s if isinstance(s, Stretch) else Stretch(dec(s[0], "balance"), whole(s[1], "days"))
        if st.days < 0:
            raise InputError("days must not be negative")
        counted = st.balance if (st.balance > 0 or not debit_only) else ZERO
        number = counted * st.days
        total_number += number
        total_days += st.days
        rows.append(
            {
                "from": st.start.isoformat() if st.start else None,
                "balance": as_float(st.balance),
                "days": st.days,
                "interest_number": as_float(number),
            }
        )
    amount = money(total_number * r / basis)
    kk, bs = money(amount * k), money(amount * b)
    return {
        "interest": as_float(amount),
        "kkdf": as_float(kk),
        "bsmv": as_float(bs),
        "total": as_float(amount + kk + bs),
        "interest_numbers": as_float(total_number),
        "days": total_days,
        "average_balance": as_float(money(total_number / total_days)) if total_days else 0.0,
        "stretches": rows,
        "conventions": {
            "formula": f"sum(balance x days) x annual rate / {basis}",
            "year_basis": basis,
            "rounding": "interest rounded half-up to 0.01 once per period; each levy rounded separately",
            "credit_balances": "ignored" if debit_only else "counted",
        },
    }
