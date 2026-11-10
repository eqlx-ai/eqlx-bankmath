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
MAX_FLOWS = 5000


def present_value(flows: Sequence[tuple[Decimal, Decimal]], x: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = PRECISION
        base = ONE + x
        return sum((amount * base ** (-t) for t, amount in flows), Decimal(0))


def annual_cost_rate(advances: Sequence[Flow], payments: Sequence[Flow]) -> Decimal:
    """Solve the equation above for X (a fraction: 0.164872 for 16.4872 %).

    ``advances`` are what the lender pays out, ``payments`` everything the borrower pays, fees and
    taxes included. Both as (years from the first drawdown, amount), amounts positive; the first
    drawdown is at time 0 and nothing is paid before it.

    When every drawdown comes before the first payment the equation has exactly one root and it is
    returned. With drawdowns that continue after payments have started it usually still has one;
    if the cash flows do not bracket a single rate the function says so instead of picking one.
    The root is located in floating point and then polished in exact decimal arithmetic until the
    two sides agree to far better than a kuruş.
    """
    adv = [(dec(t, "time"), dec(a, "amount")) for t, a in advances]
    pay = [(dec(t, "time"), dec(a, "amount")) for t, a in payments]
    if not adv or not pay:
        raise InputError("at least one advance and one payment are needed")
    if len(adv) + len(pay) > MAX_FLOWS:
        raise InputError(f"at most {MAX_FLOWS} cash flows are supported")
    if any(a <= 0 for _, a in adv) or any(a < 0 for _, a in pay):
        raise InputError("amounts must be positive")
    if any(t < 0 for t, _ in adv) or any(t < 0 for t, _ in pay):
        raise InputError("times are counted from the first drawdown and cannot be negative")
    if any(t > 200 for t, _ in adv) or any(t > 200 for t, _ in pay):
        raise InputError("times are in years; values above 200 are not supported")
    if min(t for t, _ in adv) != 0:
        raise InputError("the first drawdown is at time 0")

    def gap(x: Decimal) -> Decimal:
        return present_value(pay, x) - present_value(adv, x)

    at_zero = gap(Decimal(0))
    if at_zero == 0:
        return Decimal(0)
    fa = [(float(t), float(a)) for t, a in adv]
    fp = [(float(t), float(a)) for t, a in pay]

    def fgap(x: float) -> float:
        base = 1.0 + x
        try:
            return float(sum(a * base**-t for t, a in fp) - sum(a * base**-t for t, a in fa))
        except OverflowError:
            return float("-inf")

    lo, hi = (0.0, 1.0) if at_zero > 0 else (-0.99, 0.0)
    if at_zero > 0:
        while fgap(hi) > 0:
            lo, hi = hi, hi * 4
            if hi > 1e9:
                raise InputError("no annual cost rate below 10^11 % balances these cash flows")
    elif fgap(lo) < 0:
        raise InputError(
            "these cash flows do not bracket a single rate: the payments are too small, or drawdowns "
            "continue after payments in a way that gives no rate or several"
        )
    for _ in range(200):
        mid = (lo + hi) / 2
        if fgap(mid) > 0:
            lo = mid
        else:
            hi = mid
    with localcontext() as ctx:
        ctx.prec = PRECISION
        x = Decimal(repr((lo + hi) / 2))
        for _ in range(8):
            base = ONE + x
            value = gap(x)
            slope = sum((-t * a * base ** (-t - 1) for t, a in pay), Decimal(0)) - sum(
                (-t * a * base ** (-t - 1) for t, a in adv), Decimal(0)
            )
            if slope == 0:
                break
            step = value / slope
            x = x - step
            if abs(step) < Decimal("1e-32"):
                break
        if x <= -1 or abs(gap(x)) > Decimal("1e-9"):
            raise InputError("the annual cost rate could not be determined for these cash flows")
        return +x


def as_percent(x: Decimal, places: int = 4) -> Decimal:
    """The rate as a percentage with ``places`` decimals, rounded half-up (16.4872)."""
    return money(x * 100, places)


def from_periodic(periodic_rate: Number, periods_per_year: int = 12) -> Decimal:
    """Effective annual rate of a rate that compounds every period: (1 + i) ^ k - 1."""
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return (ONE + dec(periodic_rate, "periodic_rate")) ** periods_per_year - ONE
