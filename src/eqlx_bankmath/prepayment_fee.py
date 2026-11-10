"""The highest early repayment fee a bank may charge a commercial customer.

TCMB Communiqué 2020/4 (fees banks may charge commercial customers), Article 11 and Provisional
Article 5, with the TCMB implementation instruction, section 4/IV. The cap is a percentage of the
amount repaid early, after the reduction for interest and other costs that have not yet accrued,
and depends on the date the loan was drawn:

    drawn before 01.03.2021        lira: 1 % if the remaining term is 24 months or less, else 2 %
                                   foreign currency or indexed to it: one point more
    01.03.2021 to 30.06.2024       lira: 2 % up to 24 months; beyond that 2 % plus 1 % for each
                                   year, rounded up, of the remaining term above 24 months
                                   foreign currency or indexed to it: one point more
    from 01.07.2024, fixed rate    lira: f x 5 % + k x 0.20 %
                                   foreign currency or indexed to it: 2 % + k x 0.15 %,
                                   and for loans drawn from 06.01.2025: 3 % + k x 0.10 %
    from 01.07.2024, variable rate 2 %

f is the annual compound interest rate of the loan, without fees and taxes; k is the remaining
weighted average maturity in months. The formula results are rounded to two decimals of a per cent,
half-up (the instruction's illustration: 1.6412 becomes 1.64).

The cap covers repayment of the whole loan, which the bank must accept. A bank may refuse a partial
early repayment, and the fee for one is agreed freely (instruction 4/IV/h). Payments into a
revolving loan are not early repayment (4/IV/c).
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from . import costrate
from .daycount import parse_date
from .errors import InputError
from .money import ZERO, Number, as_float, money, non_negative, positive, rate, whole

Currency = Literal["lira", "foreign"]
RateType = Literal["fixed", "variable"]
_D = Decimal


@dataclass(frozen=True)
class Regime:
    """Caps for loans drawn from ``since`` on, as fractions, with the text they come from."""

    since: dt.date
    name: str
    basis: str
    formula: bool
    lira_base: Decimal
    lira_step: Decimal
    foreign_base: Decimal
    foreign_step: Decimal
    variable: Decimal | None = None
    per_year_beyond: bool = False


REGIMES: tuple[Regime, ...] = (
    Regime(
        dt.date.min,
        "drawn before 01.03.2021",
        "TCMB Communiqué 2020/4 Provisional Article 5(1); implementation instruction 4/IV/d",
        False,
        _D("0.01"),
        _D("0.01"),
        _D("0.02"),
        _D("0.01"),
    ),
    Regime(
        dt.date(2021, 3, 1),
        "drawn from 01.03.2021 to 30.06.2024",
        "TCMB Communiqué 2020/4 Provisional Article 5(2); implementation instruction 4/IV/e",
        False,
        _D("0.02"),
        _D("0.01"),
        _D("0.03"),
        _D("0.01"),
        per_year_beyond=True,
    ),
    Regime(
        dt.date(2024, 7, 1),
        "drawn from 01.07.2024",
        "TCMB Communiqué 2020/4 Article 11(3); implementation instruction 4/IV/f",
        True,
        _D("0.05"),
        _D("0.0020"),
        _D("0.02"),
        _D("0.0015"),
        _D("0.02"),
    ),
    Regime(
        dt.date(2025, 1, 6),
        "drawn from 06.01.2025",
        "TCMB Communiqué 2020/4 Article 11(3); implementation instruction 4/IV/f and g",
        True,
        _D("0.05"),
        _D("0.0020"),
        _D("0.03"),
        _D("0.0010"),
        _D("0.02"),
    ),
)
"""For the first two regimes ``*_base`` is the cap up to 24 months and ``*_step`` what is added
beyond; for the formula regimes the lira cap is ``f x lira_base + k x lira_step`` and the foreign
currency cap ``foreign_base + k x foreign_step``."""


def regime_for(disbursed_on: dt.date | str) -> Regime:
    """The regime that applies to a loan drawn on the given date."""
    day = parse_date(disbursed_on, "disbursed_on")
    current = REGIMES[0]
    for regime in REGIMES:
        if regime.since <= day:
            current = regime
    return current


def weighted_average_months(remaining_instalments: Sequence[tuple[int, Number]]) -> Decimal:
    """Remaining weighted average maturity in months (k in the formula).

    ``remaining_instalments`` are (days from the closing date to the due date, instalment amount).
    The days are weighted with the instalment amounts and the result is divided by 30
    (implementation instruction 4/IV/f). A bullet loan is one instalment.
    """
    items = [(whole(d, "days", minimum=0), positive(a, "instalment")) for d, a in remaining_instalments]
    if not items:
        raise InputError("at least one remaining instalment is needed")
    weighted = sum((a * d for d, a in items), ZERO)
    return weighted / sum((a for _, a in items), ZERO) / 30


def cap(
    disbursed_on: dt.date | str,
    *,
    currency: Currency = "lira",
    rate_type: RateType = "fixed",
    remaining_months: Number | None = None,
    monthly_rate: Number | None = None,
    annual_compound_rate: Number | None = None,
    remaining_instalments: Sequence[tuple[int, Number]] | None = None,
    weighted_months: Number | None = None,
    amount_repaid: Number | None = None,
    quoted_fee: Number | None = None,
) -> dict[str, Any]:
    """Highest early repayment fee on a commercial loan repaid in full, by the date it was drawn.

    * ``currency``: ``lira``, or ``foreign`` for loans in or indexed to a foreign currency.
    * ``rate_type``: ``fixed`` or ``variable``. Only loans drawn from 01.07.2024 have their own
      variable-rate cap (2 %); the provisional article for older loans does not distinguish, so the
      same caps are applied to them and the result says so.
    * Loans drawn before 01.07.2024 need ``remaining_months``, the remaining term in months.
    * Fixed-rate loans drawn from 01.07.2024 need k: give ``remaining_instalments`` as (days from
      the closing date to the due date, amount), or ``weighted_months`` directly. Lira loans also
      need f: ``annual_compound_rate``, or ``monthly_rate`` from which it is ``(1 + i) ^ 12 - 1`` as
      in the instruction's example. For a loan that is not paid monthly the instruction does not
      show how f is formed; pass the annual compound rate you can justify.
    * ``amount_repaid``: the amount repaid early after the reduction for unaccrued interest and
      costs; with it the result includes the maximum fee as an amount. ``quoted_fee`` (without
      BSMV) is then compared with that maximum.
    """
    regime = regime_for(disbursed_on)
    if currency not in ("lira", "foreign"):
        raise InputError("currency must be lira or foreign")
    if rate_type not in ("fixed", "variable"):
        raise InputError("rate_type must be fixed or variable")
    lira = currency == "lira"
    parts: dict[str, Any] = {}
    notes: list[str] = []
    if not regime.formula:
        if remaining_months is None:
            raise InputError("remaining_months is needed for loans drawn before 01.07.2024")
        months = positive(remaining_months, "remaining_months")
        base, step = (regime.lira_base, regime.lira_step) if lira else (regime.foreign_base, regime.foreign_step)
        years_beyond = 0
        if months > 24:
            years_beyond = math.ceil((months - 24) / 12) if regime.per_year_beyond else 1
        fraction = base + step * years_beyond
        parts = {"remaining_months": as_float(months), "base": as_float(base), "added": as_float(step * years_beyond)}
        formula = (
            "2 % up to 24 months remaining; plus 1 % per started year beyond 24 months"
            if regime.per_year_beyond
            else "1 % up to 24 months remaining, 2 % beyond"
        ) + ("" if lira else "; one point more for foreign currency")
        if rate_type == "variable":
            notes.append("the provisional article has no separate rule for variable-rate loans; the same cap is used")
    elif rate_type == "variable":
        if regime.variable is None:
            raise InputError("no variable-rate cap is recorded for this regime")
        fraction = regime.variable
        formula = "2 % of the amount repaid early (variable rate)"
    else:
        if (remaining_instalments is None) == (weighted_months is None):
            raise InputError("give either remaining_instalments or weighted_months")
        k = (
            weighted_average_months(remaining_instalments)
            if remaining_instalments is not None
            else non_negative(weighted_months if weighted_months is not None else 0, "weighted_months")
        )
        parts["weighted_average_months"] = as_float(k)
        if lira:
            if (monthly_rate is None) == (annual_compound_rate is None):
                raise InputError("give either monthly_rate or annual_compound_rate")
            if annual_compound_rate is not None:
                f = rate(annual_compound_rate, "annual_compound_rate")
            else:
                f = costrate.from_periodic(rate(monthly_rate if monthly_rate is not None else 0, "monthly_rate"))
            a, b = f * regime.lira_base, k * regime.lira_step
            parts.update(annual_compound_rate=as_float(f), rate_part=as_float(a), maturity_part=as_float(b))
            fraction = a + b
            formula = "f x 5 % + k x 0.20 %"
        else:
            fraction = regime.foreign_base + k * regime.foreign_step
            parts.update(base=as_float(regime.foreign_base), maturity_part=as_float(k * regime.foreign_step))
            formula = f"{regime.foreign_base * 100:.0f} % + k x {regime.foreign_step * 100:.2f} %"
    percent = money(fraction * 100, 2)
    out: dict[str, Any] = {
        "regime": regime.name,
        "currency": currency,
        "rate_type": rate_type,
        "cap_percent": as_float(percent),
        "cap_rate": as_float(percent / 100),
        "unrounded_percent": as_float(fraction * 100),
        "components": parts,
        "basis": regime.basis,
        "notes": notes,
    }
    if amount_repaid is not None:
        maximum = money(positive(amount_repaid, "amount_repaid") * percent / 100)
        out["maximum_fee"] = as_float(maximum)
        if quoted_fee is not None:
            quoted = non_negative(quoted_fee, "quoted_fee")
            out["quoted_fee"] = as_float(quoted)
            out["exceeds"] = quoted > maximum
            out["excess"] = as_float(max(quoted - maximum, ZERO))
    elif quoted_fee is not None:
        raise InputError("quoted_fee can only be checked together with amount_repaid")
    out["conventions"] = {
        "formula": formula,
        "base": "amount repaid early after the reduction for interest and costs not yet accrued",
        "rounding": "percentage rounded half-up to two decimals (implementation instruction 4/IV/f); "
        "maximum fee rounded half-up to 0.01",
        "weighted_average_months": "sum(instalment x days to its due date) / sum(instalments) / 30",
        "tax": "the cap and the quoted fee are without BSMV",
        "scope": "repayment of the whole loan; the fee for a partial early repayment is agreed freely",
    }
    return out
