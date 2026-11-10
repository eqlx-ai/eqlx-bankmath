"""The annual cost rate: one yearly percentage for everything a borrower pays.

Turkish law calls it the effective annual interest rate (efektif yıllık faiz oranı) for consumer
loans and the annual cost rate (yıllık maliyet oranı) for housing loans; the EU calls it the APR.
All define it by the same equation: the rate X at which the amounts the lender pays out and the
amounts the borrower pays back have the same present value,

    sum of C_k (1 + X) ^ -t_k   =   sum of D_l (1 + X) ^ -s_l

with times in years from the first drawdown. In the Turkish regulations a year has 360 days and 12
equal months of 30 days, and the result is shown with at least four decimals, rounded half-up
(Tüketici Kredisi Sözleşmeleri Yönetmeliği Ek-1; Konut Finansmanı Sözleşmeleri Yönetmeliği Ek-1).
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal, localcontext

from .errors import InputError
from .money import ONE, PRECISION, Number, dec, money

Flow = tuple[Number, Number]
"""(time in years from the first drawdown, amount)."""


def present_value(flows: Sequence[tuple[Decimal, Decimal]], x: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = PRECISION
        base = ONE + x
        return sum((amount * base ** (-t) for t, amount in flows), Decimal(0))


def annual_cost_rate(advances: Sequence[Flow], payments: Sequence[Flow]) -> Decimal:
    """Solve the equation above for X (a fraction: 0.164872 for 16.4872 %).

    ``advances`` are what the lender pays out, ``payments`` everything the borrower pays, fees and
    taxes included. Both as (years from the first drawdown, amount), amounts positive.

    The root is found by bisection in exact decimal arithmetic. With all drawdowns at or before the
    first payment the present value of the payments falls as X rises, so there is one root. If
    drawdowns continue after payments have started the equation can have several; the smallest
    non-negative root is returned if there is one, and this case is better checked by hand.
    """
    adv = [(dec(t, "time"), dec(a, "amount")) for t, a in advances]
    pay = [(dec(t, "time"), dec(a, "amount")) for t, a in payments]
    if not adv or not pay:
        raise InputError("at least one advance and one payment are needed")
    if any(a <= 0 for _, a in adv) or any(a < 0 for _, a in pay):
        raise InputError("amounts must be positive")
    if any(t < 0 for t, _ in adv) or any(t < 0 for t, _ in pay):
        raise InputError("times are counted from the first drawdown and cannot be negative")
    if min(t for t, _ in adv) != 0:
        raise InputError("the first drawdown is at time 0")

    def gap(x: Decimal) -> Decimal:
        return present_value(pay, x) - present_value(adv, x)

    at_zero = gap(Decimal(0))
    if at_zero == 0:
        return Decimal(0)
    lo, hi = Decimal("-0.99"), Decimal(1)
    if at_zero > 0:
        lo = Decimal(0)
    elif gap(lo) < 0:
        raise InputError("the payments are too small for any rate above -99 %")
    else:
        hi = Decimal(0)
    if lo == 0:
        while gap(hi) > 0:
            lo, hi = hi, hi * 4
            if hi > Decimal(10) ** 9:
                raise InputError("no annual cost rate below 10^11 % balances these cash flows")
    with localcontext() as ctx:
        ctx.prec = PRECISION
        for _ in range(140):
            mid = (lo + hi) / 2
            if gap(mid) > 0:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2


def as_percent(x: Decimal, places: int = 4) -> Decimal:
    """The rate as a percentage with ``places`` decimals, rounded half-up (16.4872)."""
    return money(x * 100, places)


def from_periodic(periodic_rate: Number, periods_per_year: int = 12) -> Decimal:
    """Effective annual rate of a rate that compounds every period: (1 + i) ^ k - 1."""
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return (ONE + dec(periodic_rate, "periodic_rate")) ** periods_per_year - ONE
