"""Letters of guarantee (teminat mektubu): the commission schedule, and the fee caps that do exist.

A letter of guarantee is a non-cash credit: the bank lends its signature, not money, and charges a
commission for each period the letter is outstanding (TCMB Communiqué 2020/4, Annex 1 item 1.3.3
"Gayrinakdi Kredi - Dönem Ücreti"). The form found in every published tariff and agreement is

    commission of a period = max(amount outstanding x rate x year fraction of the period, minimum)
    BSMV                   = commission x BSMV rate
    paid                   = commission + BSMV

No law or regulation fixes this formula or caps the price. Article 6(1) of the Communiqué leaves
fees without a stated limit free, and Articles 8 to 11 state none for item 1.3.3; the only ceiling
is the bank's own published maximum tariff (Article 5(3)). The length of a period, whether a
started period is charged in full, the day count, the minimum, and whether anything comes back when
the amount is reduced or the letter is returned early are all bank practice and differ between
banks. Each of them is therefore an explicit argument here, and every result repeats the choices it
was computed with under "conventions". The same letter costs visibly different amounts under
different conventions; compare before trusting a single figure.

What the regulation does cap for commercial customers is in the second half of this module: the
limit allocation fee (Article 9(1)), which is charged on non-cash limits too, and collateral costs
passed on to the customer (Article 10). The disbursement fee may not be charged on non-cash credits
at all (Article 9(2)). All caps are exclusive of BSMV.

Outside this module: a letter that is called (tazmin). The bank pays the beneficiary and the amount
paid becomes a cash loan to the customer (Banking Law 5411 Article 48 counts "the amounts of
non-cash credits that have turned into cash" as credit). From that day it is a cash exposure with
interest under the credit agreement, and the commission schedule here no longer applies. Stamp duty
and letters of credit are not covered either.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from .costrate import as_percent
from .daycount import DayCount, add_months, days, parse_date, year_basis
from .errors import InputError
from .money import ZERO, Number, as_float, money, non_negative, positive, rate, whole
from .tr.rates import Dated

Collection = Literal["advance", "arrears"]
StartedPeriod = Literal["full", "pro_rata"]
TWELVE = Decimal(12)


@dataclass(frozen=True)
class Period:
    """One commission period of a letter."""

    number: int
    start: dt.date
    end: dt.date
    """The scheduled end of the period (the expiry date if that comes first), not the return date."""
    collection_date: dt.date
    days: int
    """Days from start to end under the day count of the schedule."""
    amount: Decimal
    """The amount the commission is computed on: what is outstanding when the period starts."""
    collected: Decimal
    refund: Decimal
    commission: Decimal
    """Commission the period ends up costing: collected less refund."""
    minimum_applied: bool
    bsmv: Decimal

    @property
    def total(self) -> Decimal:
        return self.commission + self.bsmv

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "collection_date": self.collection_date.isoformat(),
            "days": self.days,
            "amount": as_float(self.amount),
            "collected": as_float(self.collected),
            "refund": as_float(self.refund),
            "commission": as_float(self.commission),
            "minimum_applied": self.minimum_applied,
            "bsmv": as_float(self.bsmv),
            "total": as_float(self.total),
        }


@dataclass(frozen=True)
class Schedule:
    """The commission schedule of one letter over its real life."""

    amount: Decimal
    annual_rate: Decimal
    bsmv_rate: Decimal
    issue_date: dt.date
    end_date: dt.date
    """The day the bank's liability ends: the return date if given, otherwise the expiry date."""
    rows: tuple[Period, ...]
    life_days: int
    amount_days: Decimal
    """Sum of (amount outstanding x days it was outstanding) from issue to the end date."""
    year_basis: int
    conventions: dict[str, Any]

    def total(self, column: str) -> Decimal:
        return sum((getattr(r, column) for r in self.rows), ZERO)

    @property
    def commission(self) -> Decimal:
        return self.total("commission")

    @property
    def bsmv(self) -> Decimal:
        return self.total("bsmv")

    @property
    def cost(self) -> Decimal:
        """Everything the customer ends up paying for the letter: commission after refunds, plus BSMV."""
        return self.commission + self.bsmv

    @property
    def average_outstanding(self) -> Decimal:
        """Day-weighted average of the amount outstanding over the life of the letter."""
        return money(self.amount_days / self.life_days)

    @property
    def effective_annual_cost(self) -> Decimal:
        """Cost per year as a fraction of the average outstanding amount, BSMV included.

        Simple annualisation: cost / average amount / (life in days / year basis), which is
        cost x year basis / amount-days. When each payment is made is ignored; this is not an
        annual cost rate in the sense of the consumer credit regulations.
        """
        return self.cost * self.year_basis / self.amount_days

    @property
    def effective_annual_cost_excluding_bsmv(self) -> Decimal:
        return self.commission * self.year_basis / self.amount_days

    def to_dict(self) -> dict[str, Any]:
        return {
            "amount": as_float(self.amount),
            "annual_rate": as_float(self.annual_rate),
            "bsmv_rate": as_float(self.bsmv_rate),
            "issue_date": self.issue_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "periods": [r.to_dict() for r in self.rows],
            "totals": {
                "collected": as_float(self.total("collected")),
                "refund": as_float(self.total("refund")),
                "commission": as_float(self.commission),
                "bsmv": as_float(self.bsmv),
                "cost": as_float(self.cost),
            },
            "life_days": self.life_days,
            "average_outstanding": as_float(self.average_outstanding),
            "effective_annual_cost_percent": as_float(as_percent(self.effective_annual_cost)),
            "effective_annual_cost_excluding_bsmv_percent": as_float(
                as_percent(self.effective_annual_cost_excluding_bsmv)
            ),
            "conventions": self.conventions,
        }


def _choice(value: str, name: str, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        raise InputError(f"{name} must be one of {', '.join(allowed)}; got {value!r}")
    return value


def _releases(
    reductions: Sequence[tuple[dt.date | str, Number]], amount: Decimal, issue: dt.date, end: dt.date
) -> list[tuple[dt.date, Decimal]]:
    merged: dict[dt.date, Decimal] = {}
    for when, released in reductions:
        day = parse_date(when, "reduction date")
        if not issue < day < end:
            raise InputError(
                f"the reduction on {day.isoformat()} is not between the issue date and the end of the letter"
            )
        merged[day] = merged.get(day, ZERO) + positive(released, "released amount")
    if sum(merged.values(), ZERO) >= amount:
        raise InputError("the reductions release the whole amount; that is a return, give return_date instead")
    return sorted(merged.items())


def commission_schedule(
    amount: Number,
    commission_rate: Number,
    issue_date: dt.date | str,
    *,
    bsmv: Number,
    expiry_date: dt.date | str | None = None,
    return_date: dt.date | str | None = None,
    rate_period_months: int = 12,
    period_months: int = 3,
    collection: Collection = "advance",
    started_period: StartedPeriod = "full",
    day_count: DayCount = "actual/360",
    minimum_commission: Number = 0,
    reductions: Sequence[tuple[dt.date | str, Number]] = (),
    refund_on_reduction: bool | None = None,
    refund_on_return: bool | None = None,
    refund_bsmv: bool = True,
) -> Schedule:
    """Commission schedule of a letter of guarantee, period by period.

    Nothing below is set by law; every argument is bank practice (see the module text), stated in
    the tariff or the credit agreement. The defaults are the reading most published tariffs use.

    ``commission_rate`` is a fraction (0.024 for 2.40 %) per ``rate_period_months``: 12 for a rate
    per year (the default), 3 for a tariff that quotes its rate per three months. The yearly rate
    is the simple multiple, rate x 12 / rate_period_months.

    The letter runs from ``issue_date`` to ``expiry_date``, or to ``return_date`` if it comes back
    earlier; an open-ended letter has only a return date. Periods of ``period_months`` months
    (default 3; one agreement uses 1 for bid bonds) are counted from the issue date. Each period is
    charged on the amount outstanding at its start, ``collection`` "advance" at the start of the
    period (default) or "arrears" at its end, or on the return date if that comes first.

    ``started_period``:

    * "full" (default): a period that has started is charged as a whole period, amount x rate x
      period_months / rate_period_months, whatever happens inside it and even if the expiry date
      cuts it short. Nothing is refunded unless ``refund_on_reduction`` / ``refund_on_return`` say so.
    * "pro_rata": a period is charged for its days under ``day_count``, and the days not used after
      a reduction or the return are always refunded, so the commission equals plain accrual on what
      was actually outstanding. The refund flags cannot be switched off in this mode.

    A refund is released amount x yearly rate x days left to the end of the period / year basis of
    ``day_count``. It is never more than what the period was charged, and never brings the period
    below ``minimum_commission`` (a floor per period; for a tariff with a minimum per month pass
    minimum x period_months). In arrears there is nothing to refund: the same deduction is made
    before the commission is collected.

    ``reductions`` are (date, amount released) pairs: partial releases, each lowering the amount
    from its date. ``bsmv`` is the BSMV rate on the commission as a fraction and has no default;
    the general rate on bank commissions is 0.05 and export-related letters can be exempt, so the
    caller states it. With ``refund_bsmv`` (default) BSMV is charged on the commission after
    refunds; without it the BSMV on a refunded commission is not given back (no rule was found for
    commercial customers).

    The result also gives the day-weighted average amount outstanding and the cost per year on that
    average (simple; see :attr:`Schedule.effective_annual_cost`).
    """
    n0 = positive(amount, "amount")
    r = rate(commission_rate, "commission_rate", maximum=1)
    b = rate(bsmv, "bsmv", maximum=1)
    rate_months = whole(rate_period_months, "rate_period_months", minimum=1)
    months = whole(period_months, "period_months", minimum=1)
    minimum = non_negative(minimum_commission, "minimum_commission")
    _choice(collection, "collection", ("advance", "arrears"))
    _choice(started_period, "started_period", ("full", "pro_rata"))
    basis = year_basis(day_count)
    pro_rata = started_period == "pro_rata"
    if pro_rata and (refund_on_reduction is False or refund_on_return is False):
        raise InputError('under started_period="pro_rata" unused days are always refunded; use "full" to charge them')
    on_reduction = pro_rata if refund_on_reduction is None else refund_on_reduction
    on_return = pro_rata if refund_on_return is None else refund_on_return
    for flag, name in (
        (on_reduction, "refund_on_reduction"),
        (on_return, "refund_on_return"),
        (refund_bsmv, "refund_bsmv"),
    ):
        if not isinstance(flag, bool):
            raise InputError(f"{name} must be true or false, got {flag!r}")

    issue = parse_date(issue_date, "issue_date")
    expiry = None if expiry_date is None else parse_date(expiry_date, "expiry_date")
    returned = None if return_date is None else parse_date(return_date, "return_date")
    if expiry is None and returned is None:
        raise InputError("give expiry_date, return_date or both (an open-ended letter needs its return date)")
    if expiry is not None and expiry <= issue:
        raise InputError("the expiry date must be after the issue date")
    if returned is not None and returned <= issue:
        raise InputError("the return date must be after the issue date")
    if expiry is not None and returned is not None and returned > expiry:
        raise InputError(
            "the return date is after the expiry date; if commission runs until the letter is back, omit expiry_date"
        )
    end_of_life = returned if returned is not None else expiry
    assert end_of_life is not None
    releases = _releases(reductions, n0, issue, end_of_life)

    def outstanding(on: dt.date) -> Decimal:
        return n0 - sum((released for day, released in releases if day <= on), ZERO)

    def by_days(base: Decimal, start: dt.date, end: dt.date) -> Decimal:
        return base * r * TWELVE * days(start, end, day_count) / (rate_months * basis)

    advance = collection == "advance"
    rows: list[Period] = []
    start, k = issue, 0
    while start < end_of_life:
        k += 1
        end = add_months(issue, k * months)
        if expiry is not None and end > expiry:
            end = expiry
        base = outstanding(start)
        raw = by_days(base, start, end) if pro_rata else base * r * months / rate_months
        charged = money(max(raw, minimum))
        unused = ZERO
        if on_reduction:
            unused += sum((money(by_days(rel, day, end)) for day, rel in releases if start < day < end), ZERO)
        if on_return and returned is not None and start < returned < end:
            unused += money(by_days(outstanding(returned), returned, end))
        refund = min(unused, charged - minimum) if charged > minimum else ZERO
        net = charged - refund
        rows.append(
            Period(
                number=k,
                start=start,
                end=end,
                collection_date=start if advance else min(end, end_of_life),
                days=days(start, end, day_count),
                amount=base,
                collected=charged if advance else net,
                refund=refund if advance else ZERO,
                commission=net,
                minimum_applied=minimum > 0 and money(raw) - unused < minimum,
                bsmv=money((net if refund_bsmv or not advance else charged) * b),
            )
        )
        start = end

    amount_days = ZERO
    cursor = issue
    for day, _ in releases:
        amount_days += outstanding(cursor) * days(cursor, day, day_count)
        cursor = day
    amount_days += outstanding(cursor) * days(cursor, end_of_life, day_count)
    life = days(issue, end_of_life, day_count)
    if life <= 0:
        raise InputError(f"the letter has no days under {day_count}")

    refund_text = "released amount x yearly rate x days left in the period / " + str(basis)
    return Schedule(
        amount=n0,
        annual_rate=r * TWELVE / rate_months,
        bsmv_rate=b,
        issue_date=issue,
        end_date=end_of_life,
        rows=tuple(rows),
        life_days=life,
        amount_days=amount_days,
        year_basis=basis,
        conventions={
            "legal_basis": "none: no statutory formula or cap for this commission (TCMB Communiqué 2020/4 "
            "Article 6(1), Annex 1 item 1.3.3); every choice below is bank practice",
            "rate": f"{r} per {rate_months} months; yearly rate is the simple multiple",
            "period_months": months,
            "periods_counted_from": "issue date",
            "collection": "in advance, at the start of each period"
            if advance
            else "in arrears, at the end of each period or on the return date",
            "started_period": "by days: amount x yearly rate x days / " + str(basis)
            if pro_rata
            else "charged in full: amount x rate x period months / rate months, also when cut short",
            "day_count": day_count,
            "commission_base": "amount outstanding at the start of the period",
            "minimum_commission": f"{minimum} per period, a floor on the commission after refunds"
            if minimum > 0
            else "none",
            "refund_on_reduction": refund_text
            if on_reduction
            else "none; the lower amount counts from the next period",
            "refund_on_return": refund_text if on_return else "none; collection stops with the period of the return",
            "bsmv": f"{b} of the commission"
            + (" after refunds" if refund_bsmv or not advance else " collected; not given back on refunds"),
            "rounding": "commission, each refund and BSMV rounded half-up to 0.01 per period",
            "average_outstanding": f"sum(amount x days) / days, {day_count}",
            "effective_annual_cost": f"simple: total cost x {basis} / sum(amount x days); payment timing ignored",
        },
    )


# --- Fee caps for commercial customers (TCMB Communiqué 2020/4) ---------------------------------------
# Dated entries, as in tr/rates.py. Only what was read in the official text is recorded: the caps
# were different before these dates (2020 text: allocation 0.25 %, collateral costs at cost) and the
# amendments in between were not traced, so earlier dates are refused instead of guessed.

CHECKED_ON = dt.date(2026, 11, 10)
ALLOCATION_FEE_CAP: tuple[Dated, ...] = (
    Dated(
        dt.date(2025, 11, 1),
        Decimal("0.0020"),
        "TCMB Communiqué 2020/4 Article 9(1) as amended by Communiqué 2025/24 (Official Gazette 18.09.2025 "
        "no. 33021): of the allocated limit, per year, pro rata by the months of the limit term; all limits "
        "that may create credit risk, non-cash included",
    ),
)
COLLATERAL_COST_MARKUP: tuple[Dated, ...] = (
    Dated(
        dt.date(2026, 2, 1),
        Decimal("0.15"),
        "TCMB Communiqué 2020/4 Article 10(1), consolidated text as updated by Communiqué 2026/5 (Official "
        "Gazette 31.01.2026 no. 33154): at most 15 % above the amount paid to third parties; the date the "
        "mark-up entered the article was not traced",
    ),
)


@dataclass(frozen=True)
class CapCheck:
    """The highest fee the regulation allows, and whether a quoted fee is above it. BSMV is outside both."""

    fee: str
    base: Decimal
    cap_rate: Decimal
    maximum: Decimal
    quoted: Decimal | None
    exceeds: bool | None
    """None when no quoted fee was given."""
    excess: Decimal
    basis: str
    since: dt.date
    on: dt.date
    conventions: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "fee": self.fee,
            "base": as_float(self.base),
            "cap_rate": as_float(self.cap_rate),
            "maximum": as_float(self.maximum),
            "quoted": None if self.quoted is None else as_float(self.quoted),
            "exceeds": self.exceeds,
            "excess": as_float(self.excess),
            "basis": self.basis,
            "since": self.since.isoformat(),
            "on": self.on.isoformat(),
            "table_checked_on": CHECKED_ON.isoformat(),
            "conventions": self.conventions,
        }


def _in_force(table: tuple[Dated, ...], on: dt.date, what: str) -> Dated:
    entry = None
    for e in table:
        if e.since <= on:
            entry = e
    if entry is None:
        raise InputError(f"no {what} is recorded before {table[0].since.isoformat()}; check the text in force then")
    return entry


def _check(
    fee: str, base: Decimal, cap: Dated, maximum: Decimal, quoted_fee: Number | None, on: dt.date, formula: str
) -> CapCheck:
    quoted = None if quoted_fee is None else non_negative(quoted_fee, "quoted_fee")
    return CapCheck(
        fee=fee,
        base=base,
        cap_rate=cap.value,
        maximum=maximum,
        quoted=quoted,
        exceeds=None if quoted is None else quoted > maximum,
        excess=ZERO if quoted is None else max(quoted - maximum, ZERO),
        basis=cap.basis,
        since=cap.since,
        on=on,
        conventions={
            "formula": formula,
            "bsmv": "not included; capped fees are exclusive of BSMV (TCMB instruction to 2020/4, section 3(j))",
            "rounding": "maximum rounded half-up to 0.01",
        },
    )


def allocation_fee_cap(
    cash_limit: Number,
    non_cash_limit: Number,
    months: int,
    on: dt.date | str,
    *,
    quoted_fee: Number | None = None,
) -> CapCheck:
    """Highest limit allocation fee (kredi tahsis ücreti) a bank may charge a commercial customer.

    TCMB Communiqué 2020/4 Article 9(1): at most 0.20 % of the allocated or renewed limit per year,
    applied in proportion to the months of the limit term. The base is every limit that may create
    credit risk, so the limit for letters of guarantee and other non-cash credits counts together
    with the cash limit. On an increase pass only the added limit and the months left. The fee may
    be charged only if the customer asked for the allocation or renewal; that is not checked here.

    ``on`` is the date of the allocation and selects the cap in force. ``quoted_fee`` is the fee the
    bank asks, without BSMV.
    """
    base = non_negative(cash_limit, "cash_limit") + non_negative(non_cash_limit, "non_cash_limit")
    if base <= 0:
        raise InputError("the limits add up to zero")
    term = whole(months, "months", minimum=1)
    day = parse_date(on, "on")
    cap = _in_force(ALLOCATION_FEE_CAP, day, "allocation fee cap")
    maximum = money(base * cap.value * term / TWELVE)
    return _check(
        "allocation fee", base, cap, maximum, quoted_fee, day, f"(cash + non-cash limit) x {cap.value} x {term} / 12"
    )


def collateral_cost_cap(
    third_party_cost: Number,
    on: dt.date | str,
    *,
    quoted_fee: Number | None = None,
) -> CapCheck:
    """Highest appraisal or collateral fee a bank may pass on to a commercial customer.

    TCMB Communiqué 2020/4 Article 10(1): for appraisals and for setting up pledges and mortgages
    from allocation until the credit is closed, at most 15 % above the amount the bank paid to
    third parties. The instruction to the Communiqué (section 4/III) applies the same rule to
    mortgage changes and releases and similar collateral work. Where the bank does the work itself
    the rule is "a reasonable price", which has no number and is not covered here.

    ``third_party_cost`` is the amount paid to the appraiser, registry or other third party for
    this transaction. ``on`` selects the rule in force; ``quoted_fee`` is what the bank asks,
    without BSMV.
    """
    base = positive(third_party_cost, "third_party_cost")
    day = parse_date(on, "on")
    cap = _in_force(COLLATERAL_COST_MARKUP, day, "collateral cost mark-up")
    maximum = money(base * (1 + cap.value))
    return _check("collateral cost", base, cap, maximum, quoted_fee, day, f"third-party cost x (1 + {cap.value})")
