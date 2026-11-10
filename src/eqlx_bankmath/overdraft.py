"""Retail overdraft (kredili mevduat hesabı, KMH): interest for a period of use, and the limit rule.

An overdraft has no instalments: the debt moves with every withdrawal and deposit, and interest is
charged on the debit balance for the days it stood (the interest-number method of
:mod:`eqlx_bankmath.adat`):

    interest = sum(debit balance x days) x monthly rate / 30

What the texts fix: the rate may not exceed the ceiling the central bank (TCMB) sets for card cash
advances (TCMB Communiqué 2020/3 Article 4(2); TCMB publishes the cash column of the card table as
valid for overdraft accounts); no fee of any kind may be charged on overdraft credit (TCMB
Communiqué 2020/7 Article 10(6)); interest is never charged on interest (Law 6502 Article 4(7));
a new limit may not exceed twice the documented average monthly income (BDDK decision 11365).

What no text fixes, and is therefore an argument or a stated convention: the interest method and
the 30-day month, the value date of each movement, the accrual period and whether its last day
counts, and the rounding. They come from the contract and from bank practice.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from decimal import Decimal
from typing import Any, Literal

from . import adat, card
from .daycount import parse_date
from .errors import InputError
from .money import ZERO, Number, as_float, dec, money, non_negative, positive, rate
from .tr.rates import Dated

Rounding = Literal["each", "total"]
THIRTY = Decimal(30)

LIMIT_INCOME_MULTIPLE = Dated(
    dt.date(2026, 1, 29),
    Decimal(2),
    "BDDK Board Decision 11365 of 29.01.2026, point 1: twice the average monthly income shown by documents",
)
NO_FEE_BASIS = "TCMB Communiqué 2020/7 Article 10(6): no fee may be charged on credit drawn from an overdraft account"
RATE_CAP_BASIS = (
    "TCMB Communiqué 2020/3 Article 4(2): overdraft rates may not exceed the ceilings set for credit cards; "
    "TCMB publishes the cash advance ceiling as valid for overdraft accounts"
)


def period_interest(
    opening_balance: Number,
    movements: Sequence[tuple[dt.date | str, Number]],
    period_start: dt.date | str,
    period_end: dt.date | str,
    monthly_rate: Number,
    *,
    max_monthly_rate: Number | None = None,
    reference_rate: Number | None = None,
    kkdf: Number = 0,
    bsmv: Number = 0,
    count_end_day: bool = True,
    rounding: Rounding = "each",
) -> dict[str, Any]:
    """Interest and levies on an overdraft for one accrual period (a month, or any period).

    * ``opening_balance``: the debt at the start of ``period_start`` (principal only; interest and
      levies charged earlier must be left out, because interest is never charged on interest).
      A negative number is money in the account.
    * ``movements``: (value date, amount) within the period; positive amounts are drawings, negative
      amounts are deposits. A movement counts from its value date; which value date a bank gives to
      a deposit is contract practice, so the caller supplies value dates.
    * ``monthly_rate``: the contractual monthly rate as a fraction (0.0425 for 4.25 %). It is
      compared with ``max_monthly_rate`` if given, otherwise with the cash advance ceiling computed
      from ``reference_rate`` (:func:`eqlx_bankmath.card.max_rates`); a rate above the ceiling is
      computed as given and flagged. With neither, no comparison is made and the result says so.
    * ``kkdf`` / ``bsmv``: levies on the interest as fractions; inputs, see :mod:`eqlx_bankmath.tr.rates`.
    * ``count_end_day`` (default True): ``period_end`` is the last day that bears interest, so a
      calendar month given by its first and last day counts every day of the month. With False the
      period stops at the start of ``period_end``.
    * ``rounding``: ``each`` (default: interest rounded once for the period, each levy rounded
      separately, as a statement that prints the three lines must) or ``total`` (interest and levies
      together rounded once, as in a published bank illustration; the three lines are then rounded
      for display and may differ from the total by 0.01).

    Days on which the account is not overdrawn bear no interest. The convention is
    "monthly rate x days / 30" on actual calendar days.
    """
    r = rate(monthly_rate, "monthly_rate", maximum=1)
    k, b = rate(kkdf, "kkdf", maximum=1), rate(bsmv, "bsmv", maximum=1)
    if rounding not in ("each", "total"):
        raise InputError("rounding must be each or total")
    if not isinstance(count_end_day, bool):
        raise InputError("count_end_day must be True or False")
    opening = dec(opening_balance, "opening_balance")
    stretches = adat.stretches_from_movements(opening, movements, period_start, period_end, count_end_day=count_end_day)
    out = adat.interest(stretches, r * 12, year_basis=360, kkdf=k, bsmv=b)
    if rounding == "total":
        number = sum((s.number for s in stretches if s.balance > 0), ZERO)
        raw = number * r / THIRTY
        out["interest"] = as_float(money(raw))
        out["kkdf"] = as_float(money(raw * k))
        out["bsmv"] = as_float(money(raw * b))
        out["total"] = as_float(money(raw * (1 + k + b)))

    if max_monthly_rate is not None:
        ceiling: Decimal | None = rate(max_monthly_rate, "max_monthly_rate", maximum=1)
        source = "supplied by the caller"
    elif reference_rate is not None:
        caps = card.max_rates(reference_rate, kind="cash")
        ceiling = caps.contractual
        source = f"reference rate plus the cash advance spread; {caps.basis}"
    else:
        ceiling, source = None, "not checked: neither max_monthly_rate nor reference_rate was given"
    closing = opening + sum((dec(a, "amount") for _, a in movements), ZERO)
    conventions = dict(out["conventions"])
    conventions.update(
        {
            "formula": "sum(debit balance x days) x monthly rate / 30, on actual calendar days",
            "value_dates": "each movement counts from the value date supplied",
            "period_end": "the last day bears interest" if count_end_day else "the last day bears no interest",
            "rounding": "interest rounded half-up to 0.01 once per period; each levy rounded separately"
            if rounding == "each"
            else "interest and levies rounded half-up to 0.01 once, together; the three lines are for display",
            "interest_base": "principal only; charges of this and earlier periods bear no interest",
        }
    )
    out.update(
        {
            "period_start": parse_date(period_start, "period_start").isoformat(),
            "period_end": parse_date(period_end, "period_end").isoformat(),
            "monthly_rate": as_float(r),
            "max_monthly_rate": as_float(ceiling) if ceiling is not None else None,
            "above_legal_cap": (r > ceiling) if ceiling is not None else None,
            "rate_cap_source": source,
            "closing_principal": as_float(closing),
            "fee": 0.0,
            "legal_basis": {
                "rate_cap": RATE_CAP_BASIS,
                "no_fee": NO_FEE_BASIS,
                "no_compound_interest": "Law 6502 Article 4(7)",
            },
            "notes": [
                "No fee may be charged on overdraft credit (TCMB Communiqué 2020/7 Article 10(6)); "
                "the cost is interest and its levies only.",
                "The interest method, value dates and the accrual period are bank practice; no regulation fixes them.",
            ],
            "conventions": conventions,
        }
    )
    return out


def limit_check(
    limit: Number,
    average_monthly_income: Number,
    *,
    on: dt.date | str | None = None,
    education_payment: bool = False,
    multiple: Number | None = None,
) -> dict[str, Any]:
    """Does an overdraft limit respect BDDK decision 11365 (at most twice the documented income)?

    The rule covers new overdraft accounts and limit increases for individuals from 29.01.2026.
    ``average_monthly_income`` is the average monthly income shown by documents the bank accepts as
    proof. ``on`` is the date the limit is granted or raised; without it the rule is taken to
    apply. Limits given for education payments under a contract between the bank and a school are
    exempt (point 2). ``multiple`` replaces the recorded multiple.
    """
    amount = positive(limit, "limit")
    income = non_negative(average_monthly_income, "average_monthly_income")
    if not isinstance(education_payment, bool):
        raise InputError("education_payment must be True or False")
    factor = LIMIT_INCOME_MULTIPLE.value if multiple is None else positive(multiple, "multiple")
    day = parse_date(on, "on") if on is not None else None
    if education_payment:
        applies, reason = False, "education payment limits are exempt (decision 11365, point 2)"
    elif day is not None and day < LIMIT_INCOME_MULTIPLE.since:
        applies, reason = False, f"granted before {LIMIT_INCOME_MULTIPLE.since.isoformat()}, the decision date"
    else:
        applies, reason = True, "new overdraft account or limit increase for an individual"
    maximum = money(income * factor)
    return {
        "limit": as_float(amount),
        "average_monthly_income": as_float(income),
        "multiple": as_float(factor),
        "maximum_limit": as_float(maximum),
        "rule_applies": applies,
        "reason": reason,
        "within_rule": (amount <= maximum) if applies else None,
        "excess": as_float(max(amount - maximum, ZERO)) if applies else 0.0,
        "on": day.isoformat() if day else None,
        "legal_basis": LIMIT_INCOME_MULTIPLE.basis,
        "conventions": {
            "income": "average monthly income as documented; the bank decides which documents count",
            "scope": "applies when an account is opened or a limit is raised, not to limits already in place",
            "multiple_source": "recorded decision" if multiple is None else "supplied by the caller",
        },
    }
