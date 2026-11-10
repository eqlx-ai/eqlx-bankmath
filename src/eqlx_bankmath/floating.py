"""Variable-rate loans: compounding an overnight reference rate, and instalment loans that reprice.

No regulation prescribes how a commercial variable-rate loan is computed. The contract names the
reference rate, the spread, how the two are combined, the day basis, the repricing dates and what
happens to the instalment when the rate changes. Only the reference rate itself has a public
definition: Borsa İstanbul publishes TLREF, the Turkish lira overnight reference rate, as an annual
rate on an actual/365 basis, and compounds it over a period as

    factor = product of (1 + r_i x n_i / 365)      r_i the rate of business day i,
                                                   n_i the calendar days it applies (3 on a Friday)
    rate   = (factor - 1) x 365 / N                N the calendar days of the period

(Borsa İstanbul, TLREF rules and the settlement price of the overnight reference rate futures).
Everything else in this module is a contract choice passed as an argument.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal
from typing import Any, Literal

from . import installment
from .daycount import add_months, parse_date
from .errors import InputError
from .money import ONE, ZERO, Number, as_float, money, positive, rate, whole

Observation = tuple[Number, int]
"""(annual rate as a fraction, calendar days it applies)."""
SpreadMethod = Literal["compounded_plus_spread", "compounded_with_spread", "simple_average_plus_spread"]
Adjustment = Literal["recompute_instalment", "keep_principal"]


def _basis(year_basis: int) -> int:
    if isinstance(year_basis, bool) or year_basis not in (360, 365, 366):
        raise InputError("year_basis must be 360, 365 or 366")
    return year_basis


def _observations(observations: Sequence[Observation]) -> list[tuple[Decimal, int]]:
    out = [(rate(r, "reference rate"), whole(n, "days", minimum=1)) for r, n in observations]
    if not out:
        raise InputError("at least one observation is needed")
    return out


def _factor(obs: Sequence[tuple[Decimal, int]], basis: int, add: Decimal = ZERO) -> Decimal:
    factor = ONE
    for r, n in obs:
        factor *= ONE + (r + add) * n / basis
    return factor


def compound_factor(observations: Sequence[Observation], *, year_basis: int = 365) -> Decimal:
    """Product of ``1 + r_i x n_i / year basis`` over the observations, unrounded.

    With ``year_basis=365`` this is the compounding Borsa İstanbul defines for TLREF. Which days are
    observed (lag, lookback) is decided by the caller through the observations passed in.
    """
    return _factor(_observations(observations), _basis(year_basis))


def compound_reference(observations: Sequence[Observation], *, year_basis: int = 365) -> dict[str, Any]:
    """Compound an overnight reference rate over a period and express it as an annual rate.

    ``observations`` are (rate, calendar days it applies): one entry per business day, with 3 days
    for a Friday and more before a holiday. The result follows the Borsa İstanbul definition above:
    the compounding factor, the calendar days, and ``(factor - 1) x 365 / days``. The percentage
    rounded to two decimals is how the exchange prints it.
    """
    obs = _observations(observations)
    basis = _basis(year_basis)
    factor = _factor(obs, basis)
    days = sum(n for _, n in obs)
    annual = (factor - ONE) * basis / days
    return {
        "factor": as_float(money(factor, 9)),
        "days": days,
        "business_days": len(obs),
        "period_rate": as_float(factor - ONE),
        "annual_rate": as_float(annual),
        "annual_rate_percent": as_float(money(annual * 100, 2)),
        "conventions": {
            "formula": f"product(1 + rate x days / {basis}); annual rate = (factor - 1) x {basis} / calendar days",
            "year_basis": basis,
            "rounding": "factor shown with 9 decimals, percentage with 2 (half-up); the unrounded rate is returned too",
            "source": "Borsa İstanbul TLREF definition (actual/365)" if basis == 365 else "not the TLREF basis",
        },
    }


def period_interest(
    principal: Number,
    observations: Sequence[Observation],
    spread: Number = 0,
    *,
    method: SpreadMethod = "compounded_plus_spread",
    year_basis: int = 365,
    kkdf: Number = 0,
    bsmv: Number = 0,
) -> dict[str, Any]:
    """Interest of one period on a loan priced at an overnight reference rate plus a spread.

    How the spread joins the reference rate is contractual; ``method`` states it:

    * ``compounded_plus_spread`` (default): the reference rate is compounded daily and the spread
      is added to the resulting annual rate, so the spread accrues simply:
      ``period rate = (factor - 1) + spread x days / year basis``.
    * ``compounded_with_spread``: the spread is added to each day's rate before compounding:
      ``period rate = product(1 + (r_i + spread) x n_i / year basis) - 1``.
    * ``simple_average_plus_spread``: no compounding; the day-weighted average of the rates plus
      the spread: ``period rate = (average + spread) x days / year basis``.

    ``year_basis`` is used for the reference rate and for the spread alike; 365 is the basis of
    TLREF, 360 occurs in loan contracts. The rate is not rounded before it is applied. Interest is
    rounded to 0.01 and each levy separately. Daily compounding here sets the rate of one interest
    period; whether that is compound interest in the sense of TTK Article 8(2) is a legal question
    this function does not answer.
    """
    p = positive(principal, "principal")
    obs = _observations(observations)
    s = rate(spread, "spread")
    basis = _basis(year_basis)
    k, b = rate(kkdf, "kkdf", maximum=1), rate(bsmv, "bsmv", maximum=1)
    days = sum(n for _, n in obs)
    if method == "compounded_plus_spread":
        period = _factor(obs, basis) - ONE + s * days / basis
        how = "reference compounded daily; spread added to the annualised compounded rate (accrues simply)"
    elif method == "compounded_with_spread":
        period = _factor(obs, basis, s) - ONE
        how = "spread added to each day's rate, then compounded daily"
    elif method == "simple_average_plus_spread":
        average = sum((r * n for r, n in obs), ZERO) / days
        period = (average + s) * days / basis
        how = "day-weighted average of the daily rates plus spread, no compounding"
    else:
        raise InputError("method must be compounded_plus_spread, compounded_with_spread or simple_average_plus_spread")
    interest = money(p * period)
    kk, bs = money(interest * k), money(interest * b)
    return {
        "principal": as_float(p),
        "days": days,
        "spread": as_float(s),
        "period_rate": as_float(period),
        "annual_rate": as_float(period * basis / days),
        "annual_rate_percent": as_float(money(period * basis / days * 100, 4)),
        "interest": as_float(interest),
        "kkdf": as_float(kk),
        "bsmv": as_float(bs),
        "total": as_float(interest + kk + bs),
        "conventions": {
            "method": how,
            "year_basis": basis,
            "annual_rate": f"period rate x {basis} / calendar days",
            "rounding": "rate not rounded; interest rounded half-up to 0.01; each levy rounded separately",
            "legal_basis": "contractual; only the reference rate itself (TLREF, actual/365) has a public definition",
        },
    }


def _steps(
    rates: Sequence[tuple[int | dt.date | str, Number]], n: int, start: dt.date | None
) -> list[tuple[int, Decimal]]:
    out: list[tuple[int, Decimal]] = []
    for key, value in rates:
        r = rate(value, "monthly rate", maximum=1)
        if isinstance(key, int) and not isinstance(key, bool):
            first = key
        else:
            if start is None:
                raise InputError("repricing by date needs the drawdown date in start")
            day = parse_date(key, "repricing date")
            first = next((j for j in range(1, n + 1) if add_months(start, j - 1) >= day), 0)
        if not 1 <= first <= n:
            raise InputError(f"a repricing falls outside the {n} instalments: {key!r}")
        out.append((first, r))
    out.sort(key=lambda item: item[0])
    if not out or out[0][0] != 1:
        raise InputError("rates must start with the rate of the first instalment")
    if len({k for k, _ in out}) != len(out):
        raise InputError("two rates apply from the same instalment")
    return out


def repricing_schedule(
    principal: Number,
    n: int,
    rates: Sequence[tuple[int | dt.date | str, Number]],
    *,
    kkdf: Number = 0,
    bsmv: Number = 0,
    method: installment.Method = "annuity",
    adjustment: Adjustment = "recompute_instalment",
    start: dt.date | str | None = None,
) -> dict[str, Any]:
    """Repayment schedule of an instalment loan whose monthly rate changes on repricing dates.

    ``rates`` are (from, monthly rate as a fraction). ``from`` is an instalment number (``7``: the
    rate applies from the seventh instalment period, that is, the loan reprices on the sixth due
    date) or a date (the rate applies to instalment periods that begin on or after it; ``start``
    is then required). The first entry must be instalment 1 or a date not after the drawdown.

    How a bank adjusts the instalment at repricing is contractual. No rule prescribes it for
    commercial loans, so it is the ``adjustment`` argument and the result states which was used:

    * ``recompute_instalment`` (default, the usual method): at each repricing a new plan is built
      with :func:`eqlx_bankmath.installment.plan` on the remaining balance, the remaining number of
      instalments and the new rate. The term does not change; the instalment does.
    * ``keep_principal``: the principal part of every instalment stays as in the plan drawn up at
      the first rate; only the interest and its levies follow the new rate.

    Returns the segments (one per rate) and the combined schedule. Rounding and levies are those
    of :mod:`eqlx_bankmath.installment`. The schedule shows what is known today: future reference
    rates are not forecast, the caller supplies each rate once it is set.
    """
    p = positive(principal, "principal")
    count = whole(n, "n", minimum=1)
    start_date = parse_date(start, "start") if start is not None else None
    if adjustment not in ("recompute_instalment", "keep_principal"):
        raise InputError("adjustment must be recompute_instalment or keep_principal")
    steps = _steps(rates, count, start_date)
    lev = installment.Levies.of(kkdf, bsmv)
    base = installment.plan(p, steps[0][1], count, kkdf=lev.kkdf, bsmv=lev.bsmv, method=method)

    rows: list[installment.Row] = []
    segments: list[dict[str, Any]] = []
    balance = p
    for index, (first, r) in enumerate(steps):
        last = steps[index + 1][0] - 1 if index + 1 < len(steps) else count
        opening = balance
        part: list[installment.Row] = []
        if adjustment == "recompute_instalment":
            segment = (
                base
                if index == 0
                else installment.plan(balance, r, count - first + 1, kkdf=lev.kkdf, bsmv=lev.bsmv, method=method)
            )
            part = [replace(row, number=first + row.number - 1) for row in segment.rows[: last - first + 1]]
            balance = part[-1].balance
        else:
            for number in range(first, last + 1):
                interest = money(balance * r)
                kk, bs = lev.on(interest)
                principal_part = base.rows[number - 1].principal
                balance -= principal_part
                part.append(
                    installment.Row(
                        number, None, principal_part + interest + kk + bs, interest, kk, bs, principal_part, balance
                    )
                )
        if start_date is not None:
            part = [replace(row, date=add_months(start_date, row.number)) for row in part]
        rows.extend(part)
        segments.append(
            {
                "from_instalment": first,
                "to_instalment": last,
                "monthly_rate": as_float(r),
                "opening_balance": as_float(opening),
                "instalment": as_float(part[0].payment),
                "closing_balance": as_float(balance),
            }
        )

    def total(column: str) -> Decimal:
        return sum((getattr(row, column) for row in rows), ZERO)

    return {
        "principal": as_float(p),
        "instalments": count,
        "method": method,
        "segments": segments,
        "rows": [row.to_dict() for row in rows],
        "total_interest": as_float(total("interest")),
        "total_kkdf": as_float(total("kkdf")),
        "total_bsmv": as_float(total("bsmv")),
        "total_repayment": as_float(total("payment")),
        "conventions": {
            "adjustment": "instalment recomputed on the remaining balance, remaining term and new rate"
            if adjustment == "recompute_instalment"
            else "principal parts kept from the plan at the first rate; interest follows the new rate",
            "repricing": "a rate applies to whole instalment periods, from the due date before its first instalment",
            "interest": "balance x monthly rate, months of equal length",
            "rounding": "instalment, interest, KKDF and BSMV each rounded half-up to 0.01; "
            "the last instalment absorbs the difference",
            "legal_basis": "contractual: no rule prescribes how the instalment is adjusted at repricing",
        },
    }
