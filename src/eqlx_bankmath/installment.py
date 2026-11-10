"""Instalment loans: the repayment plan, with the levies charged on interest.

In Türkiye two levies are charged on the interest of a loan: KKDF (a fund levy) and BSMV (a
transaction tax). Each is a percentage of the interest of the period, not of the other levy. The
instalment is level *including* the levies, so it is the annuity at the gross monthly rate

    gross rate = monthly rate x (1 + KKDF + BSMV)

Rounding follows the worked examples in the annexes of the consumer credit regulation: the
instalment, the interest, and each levy are rounded to the kuruş separately (half-up); the principal
of a period is what is left of the instalment; the last instalment absorbs the difference so that
the principal adds up exactly.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from . import costrate
from .daycount import add_months, parse_date
from .errors import InputError
from .money import ONE, ZERO, Number, as_float, kurus, money, non_negative, positive, power, rate, whole
from .tr.rates import DEFAULT_RATE_MULTIPLIER_CAP

Method = Literal["annuity", "equal_principal", "bullet"]
MAX_INSTALMENTS = 1200
THIRTY = Decimal(30)


@dataclass(frozen=True)
class Levies:
    """Levies on interest, as fractions (0.15 for 15 %)."""

    kkdf: Decimal = ZERO
    bsmv: Decimal = ZERO

    @classmethod
    def of(cls, kkdf: Number = 0, bsmv: Number = 0) -> Levies:
        return cls(rate(kkdf, "kkdf", maximum=1), rate(bsmv, "bsmv", maximum=1))

    @property
    def factor(self) -> Decimal:
        return ONE + self.kkdf + self.bsmv

    def on(self, interest: Decimal) -> tuple[Decimal, Decimal]:
        return money(interest * self.kkdf), money(interest * self.bsmv)


@dataclass(frozen=True)
class Row:
    number: int
    date: dt.date | None
    payment: Decimal
    interest: Decimal
    kkdf: Decimal
    bsmv: Decimal
    principal: Decimal
    balance: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "date": self.date.isoformat() if self.date else None,
            "payment": as_float(self.payment),
            "interest": as_float(self.interest),
            "kkdf": as_float(self.kkdf),
            "bsmv": as_float(self.bsmv),
            "principal": as_float(self.principal),
            "balance": as_float(self.balance),
        }


@dataclass(frozen=True)
class Plan:
    principal: Decimal
    monthly_rate: Decimal
    levies: Levies
    method: str
    rows: tuple[Row, ...]
    fee: Decimal = ZERO
    """Paid by the borrower at drawdown (for example the allocation fee, with its own tax if any)."""
    first_period_days: int = 30
    interest_only_periods: int = 0
    balloon: Decimal = ZERO

    @property
    def n(self) -> int:
        return len(self.rows)

    @property
    def gross_rate(self) -> Decimal:
        return self.monthly_rate * self.levies.factor

    @property
    def instalment(self) -> Decimal:
        """The regular instalment (the first one after any interest-only periods)."""
        if self.method == "bullet":
            return self.rows[0].payment
        return self.rows[min(self.interest_only_periods, self.n - 1)].payment

    def total(self, column: str) -> Decimal:
        return sum((getattr(r, column) for r in self.rows), ZERO)

    @property
    def total_repayment(self) -> Decimal:
        """Everything the borrower pays: all instalments plus the fee at drawdown."""
        return self.total("payment") + self.fee

    @property
    def total_cost(self) -> Decimal:
        return self.total_repayment - self.principal

    def annual_cost_rate(self) -> Decimal:
        """Annual cost rate of the plan with months as twelfths of a year (the regulation's method).

        The fee is taken as paid at drawdown. A first period that is not 30 days long is measured
        in days over 360.
        """
        shift = Decimal(self.first_period_days - 30) / 360
        payments: list[costrate.Flow] = [(Decimal(r.number) / 12 + shift, r.payment) for r in self.rows]
        if self.fee > 0:
            payments.insert(0, (ZERO, self.fee))
        return costrate.annual_cost_rate([(ZERO, self.principal)], payments)

    def to_dict(self, rows: bool = True) -> dict[str, Any]:
        x = self.annual_cost_rate()
        out: dict[str, Any] = {
            "principal": as_float(self.principal),
            "monthly_rate": as_float(self.monthly_rate),
            "kkdf_rate": as_float(self.levies.kkdf),
            "bsmv_rate": as_float(self.levies.bsmv),
            "gross_monthly_rate": as_float(self.gross_rate),
            "method": self.method,
            "instalments": self.n,
            "instalment": as_float(self.instalment),
            "last_instalment": as_float(self.rows[-1].payment),
            "fee_at_drawdown": as_float(self.fee),
            "total_interest": as_float(self.total("interest")),
            "total_kkdf": as_float(self.total("kkdf")),
            "total_bsmv": as_float(self.total("bsmv")),
            "total_repayment": as_float(self.total_repayment),
            "total_cost": as_float(self.total_cost),
            "annual_cost_rate_percent": as_float(costrate.as_percent(x)),
            "annual_rate_from_monthly_rate_percent": as_float(
                costrate.as_percent(costrate.from_periodic(self.monthly_rate))
            ),
            "conventions": {
                "rounding": "instalment, interest, KKDF and BSMV each rounded half-up to 0.01; "
                "the last instalment absorbs the difference",
                "interest": "balance x monthly rate x days / 30",
                "annual_cost_rate": "360-day year, 12 equal months; fee paid at drawdown",
            },
        }
        if rows:
            out["rows"] = [r.to_dict() for r in self.rows]
        return out


def annuity_payment(
    principal: Decimal, gross_rate: Decimal, n: int, balloon: Decimal = ZERO, first_period_days: int = 30
) -> Decimal:
    """Level instalment, unrounded: ``(P - R v^n) i / (1 - v^n)`` with ``v = 1 / (1 + i)``.

    A first period of other than 30 days scales the instalment by ``(1 + i) ^ ((days - 30) / 30)``,
    which is how the regulation's partial prepayment example carries odd days.
    """
    if gross_rate == 0:
        pay = (principal - balloon) / n
    else:
        v_n = power(ONE + gross_rate, -n)
        pay = (principal - balloon * v_n) * gross_rate / (ONE - v_n)
    if first_period_days != 30:
        pay = pay * power(ONE + gross_rate, Decimal(first_period_days - 30) / THIRTY)
    return pay


def plan(
    principal: Number,
    monthly_rate: Number,
    n: int,
    *,
    kkdf: Number = 0,
    bsmv: Number = 0,
    method: Method = "annuity",
    fee: Number = 0,
    start: dt.date | str | None = None,
    interest_only_periods: int = 0,
    balloon: Number = 0,
    first_period_days: int = 30,
) -> Plan:
    """Build a repayment plan with monthly instalments.

    * ``monthly_rate``: the contractual monthly rate as a fraction (0.0399 for 3.99 %).
    * ``kkdf`` / ``bsmv``: levies on interest as fractions; see :mod:`eqlx_bankmath.tr.rates` for
      the rates by product and date. They are inputs, never assumed.
    * ``method``: ``annuity`` (equal instalments), ``equal_principal``, or ``bullet`` (interest every
      month, principal at the end).
    * ``fee``: paid at drawdown; it enters the total cost and the annual cost rate.
    * ``interest_only_periods``: months at the start in which only interest and levies are paid.
    * ``balloon``: principal left for the last instalment (annuity only).
    * ``first_period_days``: days from drawdown to the first instalment when not 30.
    * ``start``: drawdown date; instalments then carry dates one month apart.
    """
    p = kurus(principal, "principal")
    r = rate(monthly_rate, "monthly_rate", maximum=1)
    count = whole(n, "n", minimum=1, maximum=MAX_INSTALMENTS)
    lev = Levies.of(kkdf, bsmv)
    fee_d = non_negative(fee, "fee")
    grace = whole(interest_only_periods, "interest_only_periods")
    residual = non_negative(balloon, "balloon")
    first_days = whole(first_period_days, "first_period_days", minimum=1, maximum=366)
    if method not in ("annuity", "equal_principal", "bullet"):
        raise InputError("method must be annuity, equal_principal or bullet")
    if grace >= count:
        raise InputError("interest_only_periods must be smaller than the number of instalments")
    if residual >= p:
        raise InputError("the balloon must be smaller than the principal")
    if residual > 0 and method != "annuity":
        raise InputError("a balloon is only defined for the annuity method")
    start_date = parse_date(start, "start") if start is not None else None

    gross = r * lev.factor
    paying = count - grace
    level = ZERO
    if method == "annuity":
        odd = first_days if grace == 0 else 30
        level = money(annuity_payment(p, gross, paying, residual, odd))
    slice_ = money(p / paying) if method == "equal_principal" else ZERO

    rows: list[Row] = []
    balance = p
    for k in range(1, count + 1):
        days = first_days if k == 1 else 30
        interest = money(balance * r * days / THIRTY)
        kk, bs = lev.on(interest)
        last = k == count
        if k <= grace or (method == "bullet" and not last):
            principal_part = ZERO
        elif last:
            principal_part = balance
        elif method == "annuity":
            principal_part = level - interest - kk - bs
            # After a long first period the interest can exceed the instalment: the balance then
            # grows in that month, as the regulation's own formula implies. Anywhere else it is an error.
            if principal_part < 0 and not (k == 1 and first_days > 30):
                raise InputError("the instalment does not cover the interest; check the rate and the term")
        else:
            principal_part = slice_
        principal_part = min(principal_part, balance)  # rounding must not repay more than is owed
        payment = principal_part + interest + kk + bs
        balance -= principal_part
        if start_date is None:
            date = None
        elif first_days == 30:
            date = add_months(start_date, k)
        else:
            date = add_months(start_date + dt.timedelta(days=first_days), k - 1)
        rows.append(Row(k, date, payment, interest, kk, bs, principal_part, balance))
    return Plan(p, r, lev, method, tuple(rows), fee_d, first_days, grace, residual)


# ---- early repayment, partial prepayment, late payment ----------------------------------------


def accrued(balance: Decimal, monthly_rate: Decimal, days: int, levies: Levies) -> tuple[Decimal, Decimal, Decimal]:
    """Interest for ``days`` on a balance, with its levies: balance x rate x days / 30."""
    interest = money(balance * monthly_rate * days / THIRTY)
    kk, bs = levies.on(interest)
    return interest, kk, bs


def _balance_after(p: Plan, paid: int) -> Decimal:
    whole(paid, "instalments_paid", maximum=p.n)
    return p.principal if paid == 0 else p.rows[paid - 1].balance


def payoff(p: Plan, instalments_paid: int, days_since_last_due: int = 0) -> dict[str, Any]:
    """Amount that closes the loan early (consumer credit regulation, Article 16 and Annex 2).

    ``instalments_paid`` instalments have been paid in full. With ``days_since_last_due = 0`` the
    loan is closed on a due date, right after that instalment: only the remaining principal is owed.
    Otherwise interest for the actual days since the last due date is added, with its levies.
    """
    balance = _balance_after(p, instalments_paid)
    d = whole(days_since_last_due, "days_since_last_due", maximum=59)
    interest, kk, bs = accrued(balance, p.monthly_rate, d, p.levies)
    remaining = sum((r.payment for r in p.rows[instalments_paid:]), ZERO)
    total = balance + interest + kk + bs
    return {
        "remaining_principal": as_float(balance),
        "interest": as_float(interest),
        "kkdf": as_float(kk),
        "bsmv": as_float(bs),
        "payoff": as_float(total),
        "instalments_no_longer_due": as_float(remaining),
        "saving": as_float(remaining - total),
    }


def prepay(
    p: Plan, instalments_paid: int, amount: Number, days_since_last_due: int = 0, days_to_next_due: int | None = None
) -> Plan:
    """Partial prepayment keeping the number and dates of the remaining instalments (Article 17, Annex 4).

    After ``instalments_paid`` instalments the borrower pays ``amount`` on top.

    * On a due date (``days_since_last_due = 0``) the whole amount reduces the principal and the
      remaining instalments are recomputed.
    * Between due dates, interest for the days since the last due date and its levies are taken
      first, the rest reduces the principal, the instalment falling due next is skipped, and the new
      plan starts on the due date after it; the days until the skipped due date
      (``days_to_next_due``, by default 30 minus the days since the last one; give the calendar
      days when the month is not 30 days long) are carried in the new instalment.

    Returns the new plan for the remaining instalments. Only plans with equal instalments and no
    balloon are supported, and only after any interest-only months have passed: how a prepayment
    reshapes other plans is a matter for the contract.
    """
    if p.method != "annuity" or p.balloon > 0 or instalments_paid < p.interest_only_periods:
        raise InputError(
            "partial prepayment is computed for equal-instalment plans without a balloon, after the "
            "interest-only months; other plans are reshaped as the contract says"
        )
    balance = _balance_after(p, instalments_paid)
    pay = positive(amount, "amount")
    d = whole(days_since_last_due, "days_since_last_due")
    if d == 0:
        remaining = p.n - instalments_paid
        new_balance = balance - pay
        odd = 30
    else:
        if d >= 30:
            raise InputError("days_since_last_due must be below 30; count the instalment as due instead")
        interest, kk, bs = accrued(balance, p.monthly_rate, d, p.levies)
        new_balance = balance - (pay - interest - kk - bs)
        remaining = p.n - instalments_paid - 1
        to_next = (30 - d) if days_to_next_due is None else whole(days_to_next_due, "days_to_next_due")
        odd = 30 + to_next
    if new_balance <= 0:
        raise InputError("the amount covers the whole debt; use payoff instead")
    if new_balance >= balance:
        raise InputError("the amount does not even cover the interest accrued")
    if remaining < 1:
        raise InputError("no instalment is left to recompute")
    return plan(
        new_balance,
        p.monthly_rate,
        remaining,
        kkdf=p.levies.kkdf,
        bsmv=p.levies.bsmv,
        first_period_days=odd,
    )


def late_interest(
    principal_in_instalment: Number,
    monthly_rate: Number,
    days_late: int,
    *,
    kkdf: Number = 0,
    bsmv: Number = 0,
    multiplier: Number = DEFAULT_RATE_MULTIPLIER_CAP.value,
) -> dict[str, Any]:
    """Default interest on a late instalment (consumer credit regulation, Article 18 and Annex 5).

    It runs on the principal contained in the late instalment only, for the days late, at a rate of
    at most 1.3 times the contractual rate, without compounding:
    ``principal x rate x multiplier x days / 30``, plus the levies on that amount.
    """
    base = non_negative(principal_in_instalment, "principal_in_instalment")
    r = rate(monthly_rate, "monthly_rate", maximum=1)
    m = positive(multiplier, "multiplier")
    d = whole(days_late, "days_late")
    lev = Levies.of(kkdf, bsmv)
    interest = money(base * r * m * d / THIRTY)
    kk, bs = lev.on(interest)
    return {
        "default_monthly_rate": as_float(r * m),
        "interest": as_float(interest),
        "kkdf": as_float(kk),
        "bsmv": as_float(bs),
        "total": as_float(interest + kk + bs),
        "above_legal_cap": m > DEFAULT_RATE_MULTIPLIER_CAP.value,
        "legal_cap": as_float(DEFAULT_RATE_MULTIPLIER_CAP.value),
        "basis": DEFAULT_RATE_MULTIPLIER_CAP.basis,
    }


def housing_prepayment_compensation(
    principal_repaid_early: Number, remaining_months: int, *, interest_saved: Number | None = None
) -> dict[str, Any]:
    """Upper limit of the early repayment compensation on a fixed-rate housing loan.

    At most 1 % of the principal repaid early when the remaining term does not exceed 36 months,
    2 % when it does, and never more than the interest the borrower saves (Law 6502 Article 37;
    Konut Finansmanı Sözleşmeleri Yönetmeliği Article 11(4)). Not allowed on variable-rate loans.
    """
    base = non_negative(principal_repaid_early, "principal_repaid_early")
    months = whole(remaining_months, "remaining_months")
    pct = Decimal("0.01") if months <= 36 else Decimal("0.02")
    cap = money(base * pct)
    if interest_saved is not None:
        cap = min(cap, money(non_negative(interest_saved, "interest_saved")))
    return {"rate": as_float(pct), "maximum_compensation": as_float(cap)}


# ---- the questions asked the other way round --------------------------------------------------


def largest_principal(
    instalment: Number, monthly_rate: Number, n: int, *, kkdf: Number = 0, bsmv: Number = 0
) -> Decimal:
    """Largest loan, to the kuruş, none of whose instalments exceeds ``instalment``.

    The last instalment absorbs the rounding of the plan and can be a little higher than the others;
    it is kept within the budget too.
    """
    budget = positive(instalment, "instalment")
    r = rate(monthly_rate, "monthly_rate", maximum=1)
    count = whole(n, "n", minimum=1, maximum=MAX_INSTALMENTS)
    lev = Levies.of(kkdf, bsmv)
    gross = r * lev.factor
    cent = Decimal("0.01")
    guess = money(budget / annuity_payment(ONE, gross, count))
    while guess > 0 and money(annuity_payment(guess, gross, count)) > budget:
        guess -= cent
    while money(annuity_payment(guess + cent, gross, count)) <= budget:
        guess += cent
    for _ in range(100_000):
        if guess <= 0:
            raise InputError("the instalment is too small for any loan")
        over = plan(guess, r, count, kkdf=lev.kkdf, bsmv=lev.bsmv).rows[-1].payment - budget
        if over <= 0:
            return guess
        guess -= max(cent, money(over / 2))
    raise InputError("no loan fits this instalment")


def implied_monthly_rate(
    principal: Number, instalment: Number, n: int, *, kkdf: Number = 0, bsmv: Number = 0
) -> Decimal:
    """Contractual monthly rate behind a quoted instalment (unrounded annuity), by bisection."""
    p = positive(principal, "principal")
    a = positive(instalment, "instalment")
    count = whole(n, "n", minimum=1, maximum=MAX_INSTALMENTS)
    factor = Levies.of(kkdf, bsmv).factor
    if a * count < p:
        raise InputError("the instalments add up to less than the principal")
    if annuity_payment(p, factor, count) < a:
        raise InputError("the implied rate is above 100 % a month")
    lo, hi = ZERO, ONE
    for _ in range(120):
        mid = (lo + hi) / 2
        if annuity_payment(p, mid * factor, count) > a:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def shortest_term(
    principal: Number, instalment: Number, monthly_rate: Number, *, kkdf: Number = 0, bsmv: Number = 0, limit: int = 600
) -> int:
    """Smallest number of monthly instalments whose instalment does not exceed ``instalment``."""
    p = positive(principal, "principal")
    a = positive(instalment, "instalment")
    gross = rate(monthly_rate, "monthly_rate", maximum=1) * Levies.of(kkdf, bsmv).factor
    for count in range(1, limit + 1):
        if money(annuity_payment(p, gross, count)) <= a:
            return count
    raise InputError(f"the instalment does not repay the loan within {limit} months")


def flows(p: Plan) -> Sequence[tuple[Decimal, Decimal]]:
    """Borrower payments as (years from drawdown, amount), for a custom cost rate calculation."""
    shift = Decimal(p.first_period_days - 30) / 360
    return [(Decimal(r.number) / 12 + shift, r.payment) for r in p.rows]
