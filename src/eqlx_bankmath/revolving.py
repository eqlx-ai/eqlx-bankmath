"""Commercial loans on a daily balance: revolving lines, current accounts, spot loans, and fee caps.

For loans to firms the law fixes almost nothing about the arithmetic. Rates are free (TCMB
Communiqué 2020/3 Article 4; Turkish Commercial Code, TTK, Article 8(1)); the day basis, the accrual
dates, the value dates and the rounding come from the contract. What rules do fix is narrow: the
levies on interest (:mod:`eqlx_bankmath.tr.rates`), the limit on compound interest (TTK Article
8(2)) and the caps on fees (TCMB Communiqué 2020/4). So every convention below is an argument, its
default is the most common bank practice and nothing more, and each result repeats the choices made
under ``conventions``.

Interest is computed with the interest-number method of :mod:`eqlx_bankmath.adat`.
"""

from __future__ import annotations

import calendar
import datetime as dt
from collections.abc import Sequence
from decimal import Decimal
from typing import Any, Literal

from . import adat, costrate
from .daycount import add_months, parse_date
from .errors import InputError
from .money import ZERO, Number, as_float, dec, money, non_negative, positive, rate, whole
from .tr import rates as tr_rates

Accrual = Literal["quarterly", "monthly"]
Unpaid = Literal["capitalise", "paid"]
_ONE_DAY = dt.timedelta(days=1)


def _basis(year_basis: int, name: str = "year_basis", allowed: tuple[int, ...] = (360, 365, 366)) -> int:
    if isinstance(year_basis, bool) or year_basis not in allowed:
        raise InputError(f"{name} must be one of {', '.join(str(a) for a in allowed)}")
    return year_basis


def period_ends(
    start: dt.date | str, end: dt.date | str, accrual: Accrual | Sequence[dt.date | str] = "quarterly"
) -> list[dt.date]:
    """Dates on which interest is charged between ``start`` and ``end``; ``end`` is always the last.

    ``quarterly`` gives 31 March, 30 June, 30 September and 31 December, ``monthly`` every month
    end. Both are bank practice, not a rule. A sequence of dates is used as given. Interest is also
    charged on ``end`` (closure, or the day the calculation stops), whatever day that is.
    """
    first, last = parse_date(start, "start"), parse_date(end, "end")
    if last < first:
        raise InputError("the end date is before the start date")
    out: list[dt.date] = []
    if accrual in ("quarterly", "monthly"):
        year, month = first.year, first.month
        while (year, month) <= (last.year, last.month):
            day = dt.date(year, month, calendar.monthrange(year, month)[1])
            if first <= day < last and (accrual == "monthly" or month % 3 == 0):
                out.append(day)
            year, month = (year, month + 1) if month < 12 else (year + 1, 1)
    elif isinstance(accrual, str):
        raise InputError("accrual must be quarterly, monthly or a list of dates")
    else:
        dates = sorted({parse_date(d, "accrual date") for d in accrual})
        if any(d < first or d > last for d in dates):
            raise InputError("an accrual date lies outside the period")
        out = [d for d in dates if d < last]
    return [*out, last]


def _rate_steps(
    rates: Number | Sequence[tuple[dt.date | str, Number]], start: dt.date
) -> list[tuple[dt.date, Decimal]]:
    if isinstance(rates, (Decimal, int, str, float)):
        return [(start, rate(rates, "rates"))]
    steps = sorted((parse_date(d, "rate date"), rate(r, "rate")) for d, r in rates)
    if not steps or steps[0][0] > start:
        raise InputError("rates must give the rate in force on the start date")
    if len({d for d, _ in steps}) != len(steps):
        raise InputError("two rates are given for the same date")
    return steps


def _rate_on(steps: Sequence[tuple[dt.date, Decimal]], day: dt.date) -> Decimal:
    current = steps[0][1]
    for since, value in steps:
        if since <= day:
            current = value
    return current


def line(
    opening_balance: Number,
    movements: Sequence[tuple[dt.date | str, Number]],
    start: dt.date | str,
    end: dt.date | str,
    rates: Number | Sequence[tuple[dt.date | str, Number]],
    *,
    accrual: Accrual | Sequence[dt.date | str] = "quarterly",
    year_basis: int = 360,
    count_end_day: bool = True,
    kkdf: Number = 0,
    bsmv: Number = 0,
    unpaid_interest: Unpaid = "capitalise",
    capitalise_levies: bool = True,
    merchant: bool = True,
) -> dict[str, Any]:
    """A revolving line or current account (rotatif, borçlu cari hesap) over several accrual periods.

    * ``opening_balance`` and ``movements``: the debt is positive. Movements are (value date,
      amount); drawings are positive, repayments negative. A movement counts from its value date.
      Which value date a booking gets (same day, next business day for collections) is bank
      practice and is decided by the caller.
    * ``rates``: one annual rate as a fraction (0.45), or (date, rate) pairs; a rate applies from its
      date on, and a period that contains a change is split there. The right to change the rate is
      a contract term.
    * ``accrual``: when interest is charged, see :func:`period_ends`. Bank practice.
    * ``year_basis``: 360 is what banks publish for commercial lira loans ("36000"); 365 also occurs.
    * ``count_end_day``: whether the accrual date itself bears interest in the period it closes
      (the default: a quarter then has its 90 to 92 calendar days and the next period starts the
      day after) or opens the next period (the last day of the whole calculation is then not
      counted). No rule decides this.
    * ``kkdf`` / ``bsmv``: levies on the interest of each period as fractions; look them up in
      :mod:`eqlx_bankmath.tr.rates` by disbursement date.
    * ``unpaid_interest``: ``capitalise`` debits the charge to the account on the accrual date, so
      that it bears interest from the next period on (the mechanics of a current account);
      ``paid`` assumes the borrower pays each charge from outside and the balance is untouched.
    * ``capitalise_levies``: whether the levies are debited together with the interest. They are a
      debit entry like the interest, which is the only reason for the default; no rule says so.

    Compound interest between merchants. Adding interest to the principal and charging interest on
    it is valid only at intervals of at least three months, and only in current accounts and in
    loans that are commercial for both parties (TTK Article 8(2); Article 96 for current accounts);
    interest charged against this is deemed not to exist (Article 8(4)). For anyone who is not a
    merchant compounding cannot be agreed at all (Turkish Code of Obligations Article 388(3)).
    Quarterly accrual with the unpaid charge added to the balance is exactly the three-month
    minimum. This function computes whatever is asked and puts a line under ``warnings`` when
    capitalisation happens at accrual dates less than three months apart or with ``merchant=False``.
    A first period that starts between two accrual dates is not flagged.

    Interest of a period is the sum over rates of (debit interest numbers x rate) / year basis,
    rounded once; each levy is rounded separately. Days with a credit balance bear no interest here;
    their interest numbers are reported so that a deposit rate can be applied to them separately.
    """
    first, last = parse_date(start, "start"), parse_date(end, "end")
    basis = _basis(year_basis)
    k, b = rate(kkdf, "kkdf", maximum=1), rate(bsmv, "bsmv", maximum=1)
    if unpaid_interest not in ("capitalise", "paid"):
        raise InputError("unpaid_interest must be capitalise or paid")
    ends = period_ends(first, last, accrual)
    steps = _rate_steps(rates, first)
    items = sorted((parse_date(d, "value date"), dec(a, "amount")) for d, a in movements)
    if any(d < first or d > last for d, _ in items):
        raise InputError("a movement lies outside the period")

    balance = dec(opening_balance, "opening_balance")
    periods: list[dict[str, Any]] = []
    warnings: list[str] = []
    totals = {"interest": ZERO, "kkdf": ZERO, "bsmv": ZERO, "capitalised": ZERO}
    cursor = first
    previous_end: dt.date | None = None
    for index, period_end in enumerate(ends):
        final = index == len(ends) - 1
        own_end_day = count_end_day or final
        mine = [(d, a) for d, a in items if cursor <= d and (d <= period_end if own_end_day else d < period_end)]
        bearing_until = period_end if count_end_day else period_end - _ONE_DAY
        splits = [(d, ZERO) for d, _ in steps if cursor < d <= bearing_until]
        stretches = adat.stretches_from_movements(
            balance, [*mine, *splits], cursor, period_end, count_end_day=count_end_day
        )
        by_rate: dict[Decimal, Decimal] = {}
        debit = credit = ZERO
        days = 0
        for st in stretches:
            days += st.days
            if st.balance > 0:
                r = _rate_on(steps, st.start or cursor)
                by_rate[r] = by_rate.get(r, ZERO) + st.number
                debit += st.number
            else:
                credit += -st.number
        interest = money(sum((number * r for r, number in by_rate.items()), ZERO) / basis)
        kk, bs = money(interest * k), money(interest * b)
        charge = interest + kk + bs
        closing = balance + sum((a for _, a in mine), ZERO)
        added = ZERO
        if unpaid_interest == "capitalise":
            added = charge if capitalise_levies else interest
            if not final and previous_end is not None and add_months(previous_end, 3) > period_end:
                warnings.append(
                    f"interest capitalised on {period_end.isoformat()}, less than three months after "
                    f"{previous_end.isoformat()}: TTK Article 8(2) allows intervals of three months or more"
                )
        periods.append(
            {
                "from": cursor.isoformat(),
                "to": period_end.isoformat(),
                "days": days,
                "opening_balance": as_float(balance),
                "interest_numbers": as_float(debit),
                "credit_interest_numbers": as_float(credit),
                "average_debit_balance": as_float(money(debit / days)) if days else 0.0,
                "interest_numbers_by_rate": [
                    {"annual_rate": as_float(r), "interest_numbers": as_float(number)}
                    for r, number in sorted(by_rate.items(), key=lambda item: -item[0])
                ],
                "interest": as_float(interest),
                "kkdf": as_float(kk),
                "bsmv": as_float(bs),
                "charge": as_float(charge),
                "capitalised": as_float(added),
                "closing_balance": as_float(closing + added),
            }
        )
        totals["interest"] += interest
        totals["kkdf"] += kk
        totals["bsmv"] += bs
        totals["capitalised"] += added
        balance = closing + added
        previous_end = period_end
        cursor = period_end + _ONE_DAY if count_end_day else period_end
    if unpaid_interest == "capitalise" and not merchant and len(ends) > 1:
        warnings.append(
            "interest is capitalised although the borrower is not a merchant: compound interest is valid only "
            "between merchants (TTK Article 8(2)); otherwise it cannot be agreed (Code of Obligations Article 388(3))"
        )
    total_charge = totals["interest"] + totals["kkdf"] + totals["bsmv"]
    return {
        "periods": periods,
        "total_interest": as_float(totals["interest"]),
        "total_kkdf": as_float(totals["kkdf"]),
        "total_bsmv": as_float(totals["bsmv"]),
        "total_charge": as_float(total_charge),
        "total_capitalised": as_float(totals["capitalised"]),
        "paid_separately": as_float(total_charge - totals["capitalised"]),
        "closing_balance": as_float(balance),
        "warnings": warnings,
        "conventions": {
            "formula": f"sum(debit balance x days x annual rate) / {basis} per accrual period",
            "year_basis": basis,
            "accrual_dates": accrual if isinstance(accrual, str) else "as given",
            "end_day": "the accrual date bears interest in the period it closes"
            if count_end_day
            else "the accrual date opens the next period; the last day of the calculation is not counted",
            "rate_changes": "a rate applies from its date on; the period is split at the change",
            "unpaid_interest": "debited to the account on the accrual date (capitalised)"
            if unpaid_interest == "capitalise"
            else "paid by the borrower on the accrual date; the balance is not changed",
            "levies_capitalised": unpaid_interest == "capitalise" and capitalise_levies,
            "rounding": "interest rounded half-up to 0.01 once per period; each levy rounded separately",
            "credit_balances": "bear no interest here; their interest numbers are reported",
            "legal_basis": "day basis, accrual dates and end-day counting are bank practice; "
            "capitalisation is limited by TTK Article 8(2)",
        },
    }


def spot(
    principal: Number,
    annual_rate: Number,
    days: int,
    *,
    year_basis: int = 360,
    kkdf: Number = 0,
    bsmv: Number = 0,
    interest_days: Sequence[int] | None = None,
    fee: Number = 0,
    blocked: Number = 0,
    cost_year_days: int = 365,
) -> dict[str, Any]:
    """A spot loan (spot kredi): fixed term, fixed rate, principal repaid in one sum.

    Interest is simple: ``principal x annual rate x days / year basis`` (the formula banks publish,
    with 360; bank practice, no rule).

    * ``interest_days``: by default all interest is paid at maturity. For interest paid during the
      term give the length in days of each interest period (they must add up to ``days``); each
      period's interest is computed and rounded on its own.
    * ``kkdf`` / ``bsmv``: levies as fractions of the interest. ``bsmv`` is also charged on the fee,
      because the tax covers everything the bank receives in its own favour (Law 6802 Article 28).
    * ``fee``: paid at drawdown, without tax (for example the utilisation fee; its cap is in
      :func:`utilisation_fee_cap`).
    * ``blocked``: part of the loan the borrower must leave in an account that pays no interest
      until maturity; it lowers the money actually received and comes back at the end.
    * ``cost_year_days``: 365 or 360, the year used for the annual effective cost.

    The annual effective cost is the rate X at which what the borrower receives equals the present
    value of what it pays, time measured in days / ``cost_year_days``. No regulation defines such a
    rate for commercial loans; this is the equation of the consumer credit annex applied here as a
    stated convention, so always quote it together with its year.
    """
    p = positive(principal, "principal")
    r = rate(annual_rate, "annual_rate")
    term = whole(days, "days", minimum=1)
    basis = _basis(year_basis)
    cost_year = _basis(cost_year_days, "cost_year_days", (360, 365))
    k, b = rate(kkdf, "kkdf", maximum=1), rate(bsmv, "bsmv", maximum=1)
    fee_d = non_negative(fee, "fee")
    held = non_negative(blocked, "blocked")
    spans = [term] if interest_days is None else [whole(d, "interest_days", minimum=1) for d in interest_days]
    if sum(spans) != term:
        raise InputError("interest_days must add up to days")
    fee_tax = money(fee_d * b)
    net = p - fee_d - fee_tax - held
    if net <= 0:
        raise InputError("the fee and the blocked amount leave nothing to receive")

    rows: list[dict[str, Any]] = []
    flows: list[costrate.Flow] = []
    total_interest = total_kkdf = total_bsmv = ZERO
    day = 0
    for index, span in enumerate(spans):
        day += span
        interest = money(p * r * span / basis)
        kk, bs = money(interest * k), money(interest * b)
        last = index == len(spans) - 1
        payment = interest + kk + bs + (p if last else ZERO)
        rows.append(
            {
                "day": day,
                "days": span,
                "interest": as_float(interest),
                "kkdf": as_float(kk),
                "bsmv": as_float(bs),
                "principal": as_float(p if last else ZERO),
                "payment": as_float(payment),
            }
        )
        flows.append((Decimal(day) / cost_year, payment - (held if last else ZERO)))
        total_interest += interest
        total_kkdf += kk
        total_bsmv += bs
    cost = total_interest + total_kkdf + total_bsmv + fee_d + fee_tax
    effective = costrate.annual_cost_rate([(ZERO, net)], flows)
    return {
        "principal": as_float(p),
        "annual_rate": as_float(r),
        "days": term,
        "interest": as_float(total_interest),
        "kkdf": as_float(total_kkdf),
        "bsmv": as_float(total_bsmv),
        "fee": as_float(fee_d),
        "bsmv_on_fee": as_float(fee_tax),
        "blocked": as_float(held),
        "net_received": as_float(net),
        "paid_at_maturity": rows[-1]["payment"],
        "total_repayment": as_float(p + total_interest + total_kkdf + total_bsmv),
        "total_cost": as_float(cost),
        "simple_annual_cost_percent": as_float(costrate.as_percent(cost / net * basis / term)),
        "annual_effective_cost_percent": as_float(costrate.as_percent(effective)),
        "payments": rows,
        "conventions": {
            "formula": f"principal x annual rate x days / {basis}",
            "year_basis": basis,
            "interest_timing": "at maturity" if interest_days is None else "at the end of each interest period",
            "rounding": "interest of each period rounded half-up to 0.01; each levy rounded separately",
            "fee": "paid at drawdown; BSMV charged on it at the same rate as on interest",
            "simple_annual_cost": f"total cost / net amount received x {basis} / days",
            "annual_effective_cost": f"compound rate equating net amount received and payments, "
            f"time in days / {cost_year}; own convention, no regulation prescribes it for commercial loans",
        },
    }


# ---- fee caps (TCMB Communiqué 2020/4 Article 9; implementation instruction section 4/II) -------


def _cap_entry(entry: tr_rates.Dated, on: dt.date | str | None) -> tr_rates.Dated:
    if on is not None and parse_date(on, "on") < entry.since:
        raise InputError(
            f"the cap recorded in tr.rates applies from {entry.since.isoformat()}; earlier caps are not in the table"
        )
    return entry


def _verdict(maximum: Decimal | None, quoted_fee: Number | None) -> dict[str, Any]:
    out: dict[str, Any] = {"allowed_maximum": None if maximum is None else as_float(maximum)}
    if quoted_fee is not None:
        quoted = non_negative(quoted_fee, "quoted_fee")
        over = maximum is not None and quoted > maximum
        out["quoted_fee"] = as_float(quoted)
        out["exceeds"] = over
        out["excess"] = as_float(quoted - maximum) if over and maximum is not None else 0.0
    return out


def allocation_fee_cap(
    limit: Number, months: int = 12, *, quoted_fee: Number | None = None, on: dt.date | str | None = None
) -> dict[str, Any]:
    """Highest allocation fee (kredi tahsis ücreti) for a limit allocated or renewed for ``months`` months.

    The cap is a share of the limit per year, read from :mod:`eqlx_bankmath.tr.rates`, and is
    pro-rated by the number of months of the limit period (TCMB Communiqué 2020/4 Article 9(1);
    implementation instruction 4/II/a). For an increase pass the additional limit. The cap does
    not include BSMV (instruction 3/j); compare a fee quoted without tax. ``on`` is the date of the
    allocation, used only to refuse dates before the entry in the table.
    """
    amount = positive(limit, "limit")
    m = whole(months, "months", minimum=1)
    entry = _cap_entry(tr_rates.COMMERCIAL_ALLOCATION_FEE_CAP, on)
    maximum = money(amount * entry.value * m / 12)
    return {
        "limit": as_float(amount),
        "months": m,
        "cap_rate_per_year": as_float(entry.value),
        **_verdict(maximum, quoted_fee),
        "basis": entry.basis,
        "cap_since": entry.since.isoformat(),
        "conventions": {
            "formula": "limit x cap per year x months / 12",
            "tax": "the cap and the quoted fee are without BSMV",
            "rounding": "maximum rounded half-up to 0.01",
        },
    }


def utilisation_fee_cap(
    amount: Number,
    days: int,
    *,
    revolving: bool = False,
    turkish_lira: bool = True,
    quoted_fee: Number | None = None,
    on: dt.date | str | None = None,
) -> dict[str, Any]:
    """Highest utilisation fee (kredi kullandırım ücreti) on a commercial cash loan.

    * Loans that do not revolve (spot, instalment): the cap is a share of ``amount`` drawn, charged
      at each drawdown; for a term under one year it is reduced in proportion to the days of the
      term. ``days`` at or above 360 give the full cap.
    * Revolving loans (``revolving=True``; current accounts and overdrafts included): the fee
      accrues at period ends on the average utilisation balance, which is ``amount`` here: the debit
      balances of the days in debit added up and divided by the days of the period
      (``average_debit_balance`` in :func:`line`). The cap is per year and is reduced or increased
      in proportion to the length of the period.
    * In the pro-rating a month is 30 days and a year 360 (so a quarter is ``days=90``).
    * The cap applies to Turkish lira loans only; for others the fee is free and the result has no
      maximum.

    Source: TCMB Communiqué 2020/4 Article 9(2)-(3); implementation instruction 4/II/b, c, d, h. The
    cap does not include BSMV (instruction 3/j).
    """
    base = positive(amount, "amount")
    d = whole(days, "days", minimum=1)
    entry = _cap_entry(tr_rates.COMMERCIAL_UTILISATION_FEE_CAP, on)
    maximum: Decimal | None = None
    counted = d if revolving else min(d, 360)
    if turkish_lira:
        maximum = money(base * entry.value * counted / 360)
    return {
        "amount": as_float(base),
        "days": d,
        "revolving": revolving,
        "cap_rate_per_year": as_float(entry.value) if turkish_lira else None,
        "cap_rate_for_term": as_float(entry.value * counted / 360) if turkish_lira else None,
        **_verdict(maximum, quoted_fee),
        "basis": entry.basis if turkish_lira else "TCMB Communiqué 2020/4 Article 9(3): no cap on loans not in lira",
        "cap_since": entry.since.isoformat(),
        "conventions": {
            "formula": "average utilisation balance x cap per year x days / 360"
            if revolving
            else "amount drawn x cap x min(days, 360) / 360",
            "pro_rating": "month of 30 days, year of 360 days (implementation instruction 4/II/d)",
            "tax": "the cap and the quoted fee are without BSMV",
            "rounding": "maximum rounded half-up to 0.01",
        },
    }
