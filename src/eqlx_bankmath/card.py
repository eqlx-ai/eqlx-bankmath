"""Credit cards: minimum payment, maximum rates, the interest of one statement cycle, cash advance fee.

What the law fixes (Law 5464 on Bank Cards and Credit Cards, "the Law"; the Regulation on Bank
Cards and Credit Cards, "the Regulation"):

* a purchase bears no interest before the statement date of the statement it appears on; cash use
  may bear interest from the transaction date (Law Article 26(1));
* nothing is charged when the whole statement balance is paid by the due date; after a partial
  payment interest is computed on the remaining balance (Law Article 26(2));
* when at least the minimum is paid the contractual rate applies; when less is paid, the default
  rate applies to the unpaid part of the minimum and the contractual rate to the rest (Regulation
  Article 20(3)). The Law's own sentence says "default interest on the remaining balance"; that
  reading is available as ``shortfall_basis="whole_balance"``;
* interest is never charged on interest, also in default (Law Article 26(2)).

What no text fixes, and is therefore an explicit argument echoed in every result: the day count
(actual days over a 30-day month in published bank examples), the date interest runs from, how
payments are allocated, what a payment after the due date reduces first, and the rounding. No
official worked example of a card statement exists; the defaults reproduce the examples banks publish.

The dated tables below (minimum payment, spreads over the reference rate) were compared with the
sources on 2026-11-10. The reference rate itself is announced monthly by the central bank (TCMB)
and is always an input.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Any, Literal

from .daycount import days_30_360, parse_date
from .errors import InputError
from .money import CENT, ZERO, Number, as_float, money, non_negative, positive, rate
from .tr.rates import Dated

Kind = Literal["purchase", "corporate", "cash", "fx", "restructured"]
ShortfallBasis = Literal["unpaid_minimum", "whole_balance"]
InterestFrom = Literal["statement_date", "due_date"]
CardDayCount = Literal["actual/30", "30/30"]
PaidByDueDate = Literal["no_interest", "daily_balance"]
LatePayments = Literal["unpaid_minimum_first", "rest_first"]
Rounding = Literal["total", "parts"]

CHECKED_ON = dt.date(2026, 11, 10)
THIRTY = Decimal(30)
_D = Decimal
_CLASSES = ("charges", "cash", "purchases")
DEFAULT_PAYMENT_ORDER: tuple[str, ...] = ("charges", "cash", "purchases")
MINIMUM_GAP_DAYS = 10  # Law 5464 Article 26(4): statement date to due date


# ---- (a) minimum payment ------------------------------------------------------------------------


@dataclass(frozen=True)
class MinimumRule:
    """Minimum payment as a share of the statement balance, by card limit."""

    since: dt.date
    limit_threshold: Decimal
    ratio_up_to_threshold: Decimal
    ratio_above_threshold: Decimal
    basis: str


# Decisions of the banking regulator (BDDK) under Regulation Article 22(7). The Law allows 20 % to 40 %.
# The decisions state no separate commencement date; the decision date is used.
MINIMUM_PAYMENT_RULES: tuple[MinimumRule, ...] = (
    MinimumRule(
        dt.date(2022, 6, 9),
        _D(25000),
        _D("0.20"),
        _D("0.40"),
        "BDDK Board Decision 10222 of 09.06.2022: 40 % for cards with a limit above 25,000 TL; 20 % otherwise",
    ),
    MinimumRule(
        dt.date(2024, 9, 26),
        _D(50000),
        _D("0.20"),
        _D("0.40"),
        "BDDK Board Decision 10970 of 26.09.2024: 20 % up to a limit of 50,000 TL, 40 % above",
    ),
    MinimumRule(
        dt.date(2026, 10, 1),
        _D(100000),
        _D("0.20"),
        _D("0.40"),
        "BDDK Board Decision 11581 of 01.10.2026: 20 % up to a limit of 100,000 TL, 40 % above",
    ),
)


def minimum_rule(on: dt.date | str) -> MinimumRule:
    """The minimum payment decision in force on a date."""
    day = parse_date(on, "on")
    found = None
    for entry in MINIMUM_PAYMENT_RULES:
        if entry.since <= day:
            found = entry
    if found is None:
        first = MINIMUM_PAYMENT_RULES[0].since.isoformat()
        raise InputError(f"no minimum payment decision is recorded before {first}; pass the rule in")
    return found


def minimum_payment(
    statement_balance: Number,
    card_limit: Number,
    on: dt.date | str,
    *,
    rule: MinimumRule | None = None,
    contract_ratio: Number | None = None,
) -> dict[str, Any]:
    """Minimum payment of a statement under the BDDK decision in force on ``on`` (the statement date).

    The minimum is a share of the statement balance that depends on the card's limit (Law 5464
    Article 24(3), Regulation Article 22(7) and the decision named in the result). A limit exactly
    at the threshold takes the lower share ("up to and including" in the decisions).

    * ``rule``: a decision not in the table, or one for a date before the table starts.
    * ``contract_ratio``: the bank's own higher share (Regulation Article 17(5)(h) lets a bank set
      more than the regulatory minimum, never less); a lower one is used as given and flagged.
    """
    balance = non_negative(statement_balance, "statement_balance")
    limit = positive(card_limit, "card_limit")
    day = parse_date(on, "on")
    used = rule if rule is not None else minimum_rule(day)
    regulatory = used.ratio_up_to_threshold if limit <= used.limit_threshold else used.ratio_above_threshold
    ratio = regulatory if contract_ratio is None else rate(contract_ratio, "contract_ratio", maximum=1)
    return {
        "statement_balance": as_float(balance),
        "card_limit": as_float(limit),
        "on": day.isoformat(),
        "limit_threshold": as_float(used.limit_threshold),
        "regulatory_ratio": as_float(regulatory),
        "ratio": as_float(ratio),
        "minimum_payment": as_float(money(balance * ratio)),
        "below_regulatory_minimum": ratio < regulatory,
        "legal_basis": used.basis,
        "rule_since": used.since.isoformat(),
        "table_checked_on": CHECKED_ON.isoformat(),
        "conventions": {
            "limit": "the limit of the card itself, as the decision words it; the decisions do not say "
            "whether a customer's total limit at the bank is meant",
            "effective_date": "the decision date; the decisions state no separate commencement date",
            "ratio_source": "regulatory" if contract_ratio is None else "contract (supplied by the caller)",
            "rounding": "half-up to 0.01",
        },
    }


# ---- (b) maximum rates --------------------------------------------------------------------------


@dataclass(frozen=True)
class CapRule:
    """Spreads over the monthly reference rate (fractions: 0.0014 is 14 basis points) and the balance bands."""

    since: dt.date
    lower_band: Decimal
    upper_band: Decimal
    spread_low: Decimal
    spread_middle: Decimal
    spread_high: Decimal
    spread_corporate: Decimal
    spread_cash: Decimal
    fx_share: Decimal
    default_spread: Decimal
    basis: str


# TCMB Communiqué 2020/16 Articles 4 and 5 as consolidated on 31.01.2026; rates computed this way
# apply from 01.01.2026 (Provisional Article 8). Earlier spreads and bands are not recorded here.
CAP_RULES: tuple[CapRule, ...] = (
    CapRule(
        dt.date(2026, 1, 1),
        _D(30000),
        _D(180000),
        _D("0.0014"),
        _D("0.0064"),
        _D("0.0114"),
        _D("0.0114"),
        _D("0.0114"),
        _D("0.70"),
        _D("0.0030"),
        "TCMB Communiqué 2020/16 Articles 4 and 5 (text as amended to Official Gazette 31.01.2026 no. 33154)",
    ),
)


@dataclass(frozen=True)
class RateCaps:
    """Highest monthly contractual and default rates a card issuer may charge, as fractions."""

    kind: str
    band: str | None
    reference_rate: Decimal
    contractual: Decimal
    default: Decimal
    basis: str
    rule_since: dt.date

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "band": self.band,
            "reference_rate": as_float(self.reference_rate),
            "max_contractual_monthly_rate": as_float(self.contractual),
            "max_default_monthly_rate": as_float(self.default),
            "legal_basis": self.basis,
            "rule_since": self.rule_since.isoformat(),
            "table_checked_on": CHECKED_ON.isoformat(),
            "conventions": {
                "band": "decided by the statement balance of the card account; one rate for the whole balance; "
                "a balance exactly on a band limit falls in the middle band (wording of Article 4(1))",
                "fx": "share of the cash rate, in per cent rounded half-up to two decimals (Article 4(4))",
                "nature": "these are ceilings; the rate charged is the contract's, at or below them",
            },
        }


def cap_rule(on: dt.date | str | None = None) -> CapRule:
    """The spreads in force on a date; the latest recorded ones when no date is given."""
    if on is None:
        return CAP_RULES[-1]
    day = parse_date(on, "on")
    found = None
    for entry in CAP_RULES:
        if entry.since <= day:
            found = entry
    if found is None:
        raise InputError(f"no spreads are recorded before {CAP_RULES[0].since.isoformat()}; pass the rule in")
    return found


def max_rates(
    reference_rate: Number,
    statement_balance: Number | None = None,
    *,
    kind: Kind = "purchase",
    on: dt.date | str | None = None,
    rule: CapRule | None = None,
) -> RateCaps:
    """Maximum monthly contractual and default rates from the TCMB reference rate (Communiqué 2020/16).

    ``reference_rate`` is the monthly reference rate as a fraction (0.0311 for 3.11 %).

    * ``purchase``: Turkish lira purchases; the spread depends on the statement balance, which is
      then required (Article 4(1)).
    * ``corporate``: corporate cards (Article 4(2)).
    * ``cash``: cash withdrawal or cash use (Article 4(3)). TCMB states that this ceiling also holds
      for overdraft accounts.
    * ``fx``: foreign currency transactions, 70 % of the cash rate (Article 4(4)).
    * ``restructured``: card debt restructured under BDDK decisions 10972, 11240 and 11366: the
      reference rate itself, and the highest default ceiling (Provisional Article 5).

    The default ceiling is the contractual ceiling plus 30 basis points (Article 5).
    """
    ref = rate(reference_rate, "reference_rate", maximum=1)
    used = rule if rule is not None else cap_rule(on)
    highest_default = ref + max(used.spread_high, used.spread_cash, used.spread_corporate) + used.default_spread
    band: str | None = None
    if kind == "purchase":
        if statement_balance is None:
            raise InputError("statement_balance is required for purchases: the ceiling depends on it")
        balance = non_negative(statement_balance, "statement_balance")
        if balance < used.lower_band:
            band, spread = f"below {used.lower_band}", used.spread_low
        elif balance <= used.upper_band:
            band, spread = f"{used.lower_band} to {used.upper_band}", used.spread_middle
        else:
            band, spread = f"above {used.upper_band}", used.spread_high
        contractual = ref + spread
    elif kind == "corporate":
        contractual = ref + used.spread_corporate
    elif kind == "cash":
        contractual = ref + used.spread_cash
    elif kind == "fx":
        contractual = money((ref + used.spread_cash) * used.fx_share, 4)
    elif kind == "restructured":
        return RateCaps(kind, None, ref, ref, highest_default, used.basis + "; Provisional Article 5", used.since)
    else:
        raise InputError("kind must be purchase, corporate, cash, fx or restructured")
    return RateCaps(kind, band, ref, contractual, contractual + used.default_spread, used.basis, used.since)


# ---- (c) one statement cycle --------------------------------------------------------------------


@dataclass(frozen=True)
class _State:
    """Balances after everything dated on or before ``start`` has been booked."""

    start: dt.date
    charges: Decimal
    cash: Decimal
    purchases: Decimal
    new_cash: Decimal
    paid: Decimal


def _dated(items: Sequence[tuple[dt.date | str, Number]], name: str) -> list[tuple[dt.date, Decimal]]:
    out = []
    for item in items:
        try:
            day, amount = item
        except (TypeError, ValueError):
            raise InputError(f"{name} must be (date, amount) pairs, got {item!r}") from None
        out.append((parse_date(day, f"{name} date"), positive(amount, f"{name} amount")))
    return sorted(out)


def _count(start: dt.date, end: dt.date, day_count: str) -> int:
    return days_30_360(start, end) if day_count == "30/30" else (end - start).days


def _choice(value: str, name: str, allowed: tuple[str, ...]) -> None:
    if value not in allowed:
        raise InputError(f"{name} must be one of: {', '.join(allowed)}; got {value!r}")


def statement_interest(
    statement_balance: Number,
    minimum: Number,
    statement_date: dt.date | str,
    due_date: dt.date | str,
    next_statement_date: dt.date | str,
    contractual_rate: Number,
    default_rate: Number,
    *,
    payments: Sequence[tuple[dt.date | str, Number]] = (),
    cash_balance: Number = 0,
    charges: Number = 0,
    cash_advances: Sequence[tuple[dt.date | str, Number]] = (),
    cash_contractual_rate: Number | None = None,
    cash_default_rate: Number | None = None,
    new_purchases: Number = 0,
    kkdf: Number = 0,
    bsmv: Number = 0,
    shortfall_basis: ShortfallBasis = "unpaid_minimum",
    interest_from: InterestFrom = "statement_date",
    day_count: CardDayCount = "actual/30",
    paid_by_due_date: PaidByDueDate = "no_interest",
    late_payments: LatePayments = "unpaid_minimum_first",
    payment_order: Sequence[str] = DEFAULT_PAYMENT_ORDER,
    rounding: Rounding = "total",
) -> dict[str, Any]:
    """Interest of one statement cycle: what the next statement will show for this statement's debt.

    The statement of ``statement_date`` shows ``statement_balance`` and ``minimum`` (see
    :func:`minimum_payment`), payable by ``due_date``. The cycle ends on ``next_statement_date``.
    Rates are monthly fractions (0.0325 for 3.25 %); see :func:`max_rates` for the ceilings.

    Rules taken from the texts:

    * the whole balance paid by the due date: no interest on purchases (Law 5464 Article 26(2));
    * at least the minimum paid by the due date: the contractual rate on the remaining balance;
    * less than the minimum paid: with ``shortfall_basis="unpaid_minimum"`` (default; Regulation
      Article 20(3), the reading banks publish) the default rate on the unpaid part of the minimum
      and the contractual rate on the rest; with ``"whole_balance"`` (the sentence of Law Article
      26(2)) the default rate on the whole remaining balance. Default interest starts at the due date;
    * ``new_purchases`` of the running cycle bear no interest before their own statement date
      (Law Article 26(1)); the amount is only added to the next statement balance;
    * interest is simple, on daily balances; ``charges`` (interest, levies and fees posted on
      earlier statements and still in the balance) never bear interest (Law Article 26(2));
    * cash advances bear interest from the transaction date (Law Article 26(1), if the contract
      says so): ``cash_balance`` is the cash advance principal inside the statement balance, whose
      earlier interest is already posted; ``cash_advances`` are new advances of this cycle as
      (date, amount). Both bear ``cash_contractual_rate`` day by day until repaid, even when the
      statement is paid in full.

    Bank practice, each an explicit choice echoed under ``conventions``:

    * ``day_count``: ``actual/30`` (default: calendar days over a 30-day month, as in published
      bank examples) or ``30/30`` (every month counted as 30 days);
    * ``interest_from``: ``statement_date`` (default, the earliest date the Law allows) or ``due_date``;
    * ``paid_by_due_date``: ``no_interest`` (default: what is paid by the due date never bore
      interest, whatever the day it was paid) or ``daily_balance`` (it bears interest until the day
      it is paid, unless the whole balance is paid by the due date);
    * ``late_payments``: what a payment after the due date reduces, ``unpaid_minimum_first``
      (default) or ``rest_first``. Under ``whole_balance`` the default rate stays on the whole
      remaining balance until the next statement date;
    * ``payment_order``: the order in which a payment is set against ``charges``, ``cash`` and
      ``purchases`` (default in that order); the unpaid part of the minimum is taken from the
      interest-bearing balances in the same order. A payment beyond the statement balance reduces
      the new cash advances;
    * ``rounding``: ``total`` (default: the interest is rounded once, on the sum, as published bank
      examples do; the parts are shown rounded) or ``parts`` (each part rounded, then added).

    ``kkdf`` and ``bsmv`` are levies on the interest, as fractions; they are inputs (no text names
    card interest; banks collect both at the consumer loan rates, see :mod:`eqlx_bankmath.tr.rates`).
    A payment made on the due date counts as paid by the due date; a payment reduces the balance
    from its own date.
    """
    balance = non_negative(statement_balance, "statement_balance")
    min_due = non_negative(minimum, "minimum")
    cash0 = non_negative(cash_balance, "cash_balance")
    charges0 = non_negative(charges, "charges")
    new_buys = non_negative(new_purchases, "new_purchases")
    t0 = parse_date(statement_date, "statement_date")
    t1 = parse_date(due_date, "due_date")
    t2 = parse_date(next_statement_date, "next_statement_date")
    r_c = rate(contractual_rate, "contractual_rate", maximum=1)
    r_d = rate(default_rate, "default_rate", maximum=1)
    k, b = rate(kkdf, "kkdf", maximum=1), rate(bsmv, "bsmv", maximum=1)
    _choice(shortfall_basis, "shortfall_basis", ("unpaid_minimum", "whole_balance"))
    _choice(interest_from, "interest_from", ("statement_date", "due_date"))
    _choice(day_count, "day_count", ("actual/30", "30/30"))
    _choice(paid_by_due_date, "paid_by_due_date", ("no_interest", "daily_balance"))
    _choice(late_payments, "late_payments", ("unpaid_minimum_first", "rest_first"))
    _choice(rounding, "rounding", ("total", "parts"))
    order = tuple(payment_order)
    if sorted(order) != sorted(_CLASSES):
        raise InputError("payment_order must list charges, cash and purchases once each")
    if not (t0 <= t1 <= t2) or t0 == t2:
        raise InputError(
            "dates must run statement_date <= due_date <= next_statement_date, with a cycle of at least a day"
        )
    if min_due > balance:
        raise InputError("the minimum cannot exceed the statement balance")
    if cash0 + charges0 > balance:
        raise InputError("cash_balance and charges are parts of the statement balance and cannot exceed it")
    pays = _dated(payments, "payments")
    advances = _dated(cash_advances, "cash_advances")
    if any(d < t0 or d > t2 for d, _ in pays + advances):
        raise InputError("payments and cash advances must be dated within the cycle")
    has_cash = cash0 > 0 or bool(advances)
    if has_cash and cash_contractual_rate is None:
        raise InputError("cash_contractual_rate is required when there is a cash advance")
    r_cc = rate(cash_contractual_rate, "cash_contractual_rate", maximum=1) if cash_contractual_rate is not None else r_c
    r_cd = rate(cash_default_rate, "cash_default_rate", maximum=1) if cash_default_rate is not None else r_d

    # 1. book advances and payments in date order (advances first on a shared date)
    events = sorted([(d, 0, a) for d, a in advances] + [(d, 1, a) for d, a in pays])
    points = sorted({t0, t1, t2} | {d for d, _, _ in events})
    bal = {"charges": charges0, "cash": cash0, "purchases": balance - cash0 - charges0}
    new_cash = paid = credit = ZERO
    states: list[_State] = []
    position = 0
    for point in points:
        while position < len(events) and events[position][0] == point:
            _, is_payment, amount = events[position]
            position += 1
            if not is_payment:
                new_cash += amount
                continue
            for name in order:
                take = min(amount, bal[name])
                bal[name] -= take
                amount -= take
                paid += take
            take = min(amount, new_cash)
            new_cash -= take
            credit += amount - take
        states.append(_State(point, bal["charges"], bal["cash"], bal["purchases"], new_cash, paid))
    at_due = next(s for s in states if s.start == t1)
    final = states[-1]
    paid_by_due = at_due.paid
    unpaid_at_due = balance - paid_by_due
    unpaid_minimum = max(min_due - paid_by_due, ZERO)
    below_minimum = paid_by_due < min_due
    bearing_order = [name for name in order if name != "charges"]

    # 2. interest numbers (balance x days) per class, period and rate
    keys = [
        ("purchases", "statement_to_due", "contractual", r_c),
        ("purchases", "after_due", "default", r_d),
        ("purchases", "after_due", "contractual", r_c),
        ("cash", "statement_to_due", "contractual", r_cc),
        ("cash", "after_due", "default", r_cd),
        ("cash", "after_due", "contractual", r_cc),
    ]
    numbers = {key[:3]: ZERO for key in keys}
    rows = []
    for state, end in zip(states, points[1:], strict=False):
        n = _count(state.start, end, day_count)
        default_base = {"cash": ZERO, "purchases": ZERO}
        if state.start < t1:
            if interest_from == "due_date" or unpaid_at_due == 0:
                purchase_base = ZERO
            else:
                purchase_base = at_due.purchases if paid_by_due_date == "no_interest" else state.purchases
            numbers[("purchases", "statement_to_due", "contractual")] += purchase_base * n
            numbers[("cash", "statement_to_due", "contractual")] += (state.cash + state.new_cash) * n
        else:
            if not below_minimum:
                in_default = ZERO
            elif shortfall_basis == "whole_balance":
                in_default = state.cash + state.purchases
            elif late_payments == "unpaid_minimum_first":
                in_default = max(min_due - state.paid, ZERO)
            else:
                in_default = unpaid_minimum
            for name in bearing_order:
                default_base[name] = min(in_default, getattr(state, name))
                in_default -= default_base[name]
            purchase_base = state.purchases
            numbers[("purchases", "after_due", "default")] += default_base["purchases"] * n
            numbers[("purchases", "after_due", "contractual")] += (state.purchases - default_base["purchases"]) * n
            numbers[("cash", "after_due", "default")] += default_base["cash"] * n
            numbers[("cash", "after_due", "contractual")] += (state.cash - default_base["cash"] + state.new_cash) * n
        rows.append(
            {
                "from": state.start.isoformat(),
                "to": end.isoformat(),
                "days": n,
                "purchases_bearing_interest": as_float(purchase_base),
                "cash_bearing_interest": as_float(state.cash + state.new_cash),
                "at_default_rate": as_float(default_base["cash"] + default_base["purchases"]),
                "charges_without_interest": as_float(state.charges),
            }
        )

    # 3. interest, levies, next statement
    parts = []
    exact = rounded = default_exact = default_rounded = ZERO
    for name, period, kind, r in keys:
        number = numbers[(name, period, kind)]
        if number == 0:
            continue
        amount = number * r / THIRTY
        exact += amount
        rounded += money(amount)
        if kind == "default":
            default_exact += amount
            default_rounded += money(amount)
        parts.append(
            {
                "balance": name,
                "period": period,
                "rate_type": kind,
                "monthly_rate": as_float(r),
                "interest_number": as_float(number),
                "interest": as_float(money(amount)),
            }
        )
    interest = money(exact) if rounding == "total" else rounded
    default_interest = money(default_exact) if rounding == "total" else default_rounded
    kk, bs = money(interest * k), money(interest * b)
    principal = final.cash + final.purchases + final.new_cash
    posted = final.charges + interest + kk + bs
    gap = (t1 - t0).days
    return {
        "statement_balance": as_float(balance),
        "minimum": as_float(min_due),
        "paid_by_due_date": as_float(paid_by_due),
        "paid_after_due_date": as_float(final.paid - paid_by_due),
        "unpaid_at_due_date": as_float(unpaid_at_due),
        "minimum_met": not below_minimum,
        "unpaid_part_of_minimum": as_float(unpaid_minimum),
        "interest": as_float(interest),
        "of_which_default_interest": as_float(default_interest),
        "kkdf": as_float(kk),
        "bsmv": as_float(bs),
        "total": as_float(interest + kk + bs),
        "parts": parts,
        "daily_balances": rows,
        "principal_carried": as_float(principal),
        "charges_carried": as_float(posted),
        "new_purchases": as_float(new_buys),
        "credit_balance": as_float(credit),
        "next_statement_balance": as_float(principal + posted + new_buys - credit),
        "days_statement_to_due": gap,
        "due_date_gap_meets_law": gap >= MINIMUM_GAP_DAYS,
        "legal_basis": {
            "interest": "Law 5464 Article 26(1)-(2); Regulation on Bank Cards and Credit Cards Article 20",
            "shortfall": "Regulation Article 20(3): default rate on the unpaid part of the minimum"
            if shortfall_basis == "unpaid_minimum"
            else "Law 5464 Article 26(2), literal wording: default rate on the remaining balance",
            "no_compound_interest": "Law 5464 Article 26(2); Law 6502 Article 4(7)",
            "due_date_gap": "Law 5464 Article 26(4): at least ten days between statement date and due date",
        },
        "conventions": {
            "formula": "sum(balance x days) x monthly rate / 30, simple interest",
            "day_count": day_count,
            "interest_from": interest_from,
            "shortfall_basis": shortfall_basis,
            "paid_by_due_date": paid_by_due_date,
            "late_payments": late_payments,
            "payment_order": list(order),
            "unpaid_minimum_taken_from": "interest-bearing balances in payment order: " + ", ".join(bearing_order),
            "default_interest_from": "the due date; the contractual rate applies up to the due date",
            "cash_advances": "interest from the transaction date day by day until repaid, also when the "
            "statement is paid in full; a payment counts from its own date",
            "charges": "posted interest, levies and fees bear no interest",
            "rounding": "interest rounded half-up to 0.01 once on the sum of the parts; each levy rounded separately"
            if rounding == "total"
            else "each part rounded half-up to 0.01 and added; each levy rounded separately on the total interest",
            "levies": "KKDF and BSMV on the interest, at the rates supplied",
        },
    }


# ---- (d) cash advance fee -----------------------------------------------------------------------

CASH_ADVANCE_FEE_CAP = Dated(
    dt.date(2020, 3, 7), _D("0.01"), "TCMB Communiqué 2020/7 Article 10(6): of the amount of the advance"
)


def cash_advance_fee_check(
    advance: Number, fee: Number, *, instalment: bool = False, cap: Number | None = None
) -> dict[str, Any]:
    """Is a cash advance fee within the ceiling of TCMB Communiqué 2020/7 Article 10(6)?

    The fee may not exceed 1 % of the advance; for an instalment cash advance no fee may be charged
    at all. ``fee`` is the fee without its tax (the BSMV rate on card fees is not settled in the
    sources read, so no tax is computed here). ``cap`` replaces the recorded ceiling.
    """
    amount = positive(advance, "advance")
    charged = non_negative(fee, "fee")
    if not isinstance(instalment, bool):
        raise InputError("instalment must be True or False")
    share = CASH_ADVANCE_FEE_CAP.value if cap is None else rate(cap, "cap", maximum=1)
    maximum = ZERO if instalment else (amount * share).quantize(CENT, rounding=ROUND_DOWN)
    return {
        "advance": as_float(amount),
        "fee": as_float(charged),
        "cap_ratio": 0.0 if instalment else as_float(share),
        "maximum_fee": as_float(maximum),
        "within_cap": charged <= maximum,
        "excess": as_float(max(charged - maximum, ZERO)),
        "legal_basis": CASH_ADVANCE_FEE_CAP.basis
        + ("; no fee on instalment cash advances (same paragraph)" if instalment else ""),
        "conventions": {
            "maximum_fee": "ceiling rounded down to 0.01, so that the fee never exceeds the stated share",
            "tax_on_fee": "not included; the fee is compared without tax",
            "cap_source": "recorded ceiling" if cap is None else "supplied by the caller",
        },
    }
