"""The calculations as plain functions with JSON-friendly arguments and results.

One registry serves the command line (``bankmath call <tool> '<json>'``) and the MCP server, so an
agent and a person at a terminal get the same numbers. Amounts and rates may be given as numbers or
as strings ("0.0399"); rates are fractions (0.0399 for 3.99 %); dates are ISO strings (2026-11-10).

Levies on interest (KKDF, BSMV) are never assumed. Give ``kkdf`` and ``bsmv`` yourself, or give a
``product`` and the date the loan is disbursed and the rates in force are looked up and reported
with their legal basis.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import functools
from collections.abc import Callable
from decimal import Decimal
from typing import Any, cast

from . import (
    adat,
    card,
    costrate,
    discount,
    floating,
    guarantee,
    installment,
    overdraft,
    prepayment_fee,
    revolving,
)
from .daycount import parse_date
from .errors import InputError
from .money import Number, as_float, dec, kurus, money, rate
from .tr import rates

Json = dict[str, Any]


def jsonable(value: Any) -> Any:
    """Decimals to floats, dates to ISO strings, dataclasses to dicts, recursively."""
    if isinstance(value, Decimal):
        return as_float(value)
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        if hasattr(value, "to_dict"):
            return jsonable(value.to_dict())
        return jsonable(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def _out(value: Any) -> Json:
    return cast(Json, jsonable(value))


def _levies(
    product: str | None, disbursed_on: str | None, kkdf: Number | None, bsmv: Number | None
) -> tuple[Decimal, Decimal, Decimal, Json]:
    """Levy rates to apply: (KKDF on interest, BSMV on interest, KKDF on principal at drawdown, report)."""
    zero = Decimal(0)
    if product is not None:
        if disbursed_on is None:
            raise InputError("with a product, give disbursed_on: levies apply by the date the loan is disbursed")
        found = rates.levies(product, parse_date(disbursed_on, "disbursed_on"))  # type: ignore[arg-type]
        if kkdf is not None:
            found["kkdf"], found["kkdf_basis"] = rate(kkdf, "kkdf", maximum=1), "given by the caller"
        if bsmv is not None:
            found["bsmv"], found["bsmv_basis"] = rate(bsmv, "bsmv", maximum=1), "given by the caller"
        return found["kkdf"], found["bsmv"], found["kkdf_on_principal_at_drawdown"], found
    if kkdf is None and bsmv is None:
        return zero, zero, zero, {"kkdf": zero, "bsmv": zero, "source": "none applied: no product and no rates given"}
    if kkdf is None or bsmv is None:
        raise InputError("give both kkdf and bsmv (use 0 for none), or a product and a disbursement date")
    k, b = rate(kkdf, "kkdf", maximum=1), rate(bsmv, "bsmv", maximum=1)
    return k, b, zero, {"kkdf": k, "bsmv": b, "source": "given by the caller"}


def _pairs(value: Any, name: str) -> list[tuple[Any, Any]]:
    """A list of two-item lists, as JSON carries dated amounts."""
    if not isinstance(value, (list, tuple)):
        raise InputError(f"{name} must be a list of [first, second] pairs")
    out = []
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise InputError(f"{name} must be a list of [first, second] pairs, got {item!r}")
        out.append((item[0], item[1]))
    return out


def _options(value: Json | None) -> Json:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise InputError("options must be an object")
    return dict(value)


def _call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except TypeError as exc:
        raise InputError(f"{fn.__name__}: {exc}") from exc


def _safe(fn: Callable[..., Json]) -> Callable[..., Json]:
    """Bad input always ends in an InputError with a reason, never in a traceback."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Json:
        try:
            return fn(*args, **kwargs)
        except InputError:
            raise
        except (ArithmeticError, ValueError, LookupError, TypeError, AttributeError) as exc:
            raise InputError(f"{fn.__name__}: invalid input ({type(exc).__name__}: {exc})") from exc

    return wrapper


# ---- instalment loans -------------------------------------------------------------------------


def loan_plan(
    principal: Number,
    monthly_rate: Number,
    instalments: int,
    product: str | None = None,
    disbursed_on: str | None = None,
    kkdf: Number | None = None,
    bsmv: Number | None = None,
    method: str = "annuity",
    fee: Number = 0,
    interest_only_periods: int = 0,
    balloon: Number = 0,
    first_period_days: int = 30,
    rows: bool = True,
) -> Json:
    """Repayment plan of an instalment loan: instalment, each row split into interest, KKDF, BSMV and
    principal, total repayment, and the annual cost rate as the consumer credit regulation defines it.

    product: consumer | housing_first_home | commercial_tl | commercial_fx (looks up KKDF and BSMV for
    the disbursement date), or give kkdf and bsmv as fractions. method: annuity | equal_principal | bullet.
    """
    k, b, at_drawdown, used = _levies(product, disbursed_on, kkdf, bsmv)
    kkdf_at_drawdown = money(kurus(principal, "principal") * at_drawdown)
    p = _call(
        installment.plan,
        principal,
        monthly_rate,
        instalments,
        kkdf=k,
        bsmv=b,
        method=method,
        fee=dec(fee, "fee") + kkdf_at_drawdown,
        start=disbursed_on,
        interest_only_periods=interest_only_periods,
        balloon=balloon,
        first_period_days=first_period_days,
    )
    out = p.to_dict(rows=rows)
    out["levies"] = used
    if kkdf_at_drawdown > 0:
        out["kkdf_at_drawdown"] = kkdf_at_drawdown
        out["fee_at_drawdown_note"] = "includes KKDF charged once on the principal"
    return _out(out)


def _plan(principal: Number, monthly_rate: Number, instalments: int, k: Decimal, b: Decimal) -> installment.Plan:
    return installment.plan(principal, monthly_rate, instalments, kkdf=k, bsmv=b)


def loan_early_repayment(
    principal: Number,
    monthly_rate: Number,
    instalments: int,
    instalments_paid: int,
    days_since_last_due: int = 0,
    partial_amount: Number | None = None,
    days_to_next_due: int | None = None,
    product: str | None = None,
    disbursed_on: str | None = None,
    kkdf: Number | None = None,
    bsmv: Number | None = None,
) -> Json:
    """Closing a loan early, or paying part of it early, under the consumer credit regulation.

    Without partial_amount: the amount that closes the loan after `instalments_paid` instalments,
    `days_since_last_due` days after the last due date (0 = on a due date), and what is saved.
    With partial_amount: the new, lower instalment for the same remaining due dates.
    """
    k, b, _, used = _levies(product, disbursed_on, kkdf, bsmv)
    p = _plan(principal, monthly_rate, instalments, k, b)
    if partial_amount is None:
        out = installment.payoff(p, instalments_paid, days_since_last_due)
    else:
        new = installment.prepay(p, instalments_paid, partial_amount, days_since_last_due, days_to_next_due)
        out = {
            "old_instalment": p.instalment,
            "new_instalment": new.instalment,
            "new_principal": new.principal,
            "remaining_instalments": new.n,
            "new_plan": new.to_dict(rows=False),
        }
    out["levies"] = used
    return _out(out)


def loan_affordability(
    monthly_rate: Number,
    instalments: int | None = None,
    instalment: Number | None = None,
    principal: Number | None = None,
    product: str | None = None,
    disbursed_on: str | None = None,
    kkdf: Number | None = None,
    bsmv: Number | None = None,
) -> Json:
    """The loan question asked backwards. Give two of principal, instalment, instalments:

    instalment + instalments -> the largest loan whose instalment stays within the budget;
    principal + instalment   -> the shortest term in months;
    principal + instalments  -> the instalment (same as loan_plan, without the rows).
    """
    k, b, _, used = _levies(product, disbursed_on, kkdf, bsmv)
    out: Json
    if principal is None and instalment is not None and instalments is not None:
        best = installment.largest_principal(instalment, monthly_rate, instalments, kkdf=k, bsmv=b)
        out = {"largest_principal": best, "plan": _plan(best, monthly_rate, instalments, k, b).to_dict(rows=False)}
    elif principal is not None and instalment is not None and instalments is None:
        n = installment.shortest_term(principal, instalment, monthly_rate, kkdf=k, bsmv=b)
        out = {"shortest_term_months": n, "plan": _plan(principal, monthly_rate, n, k, b).to_dict(rows=False)}
    elif principal is not None and instalments is not None and instalment is None:
        out = {"plan": _plan(principal, monthly_rate, instalments, k, b).to_dict(rows=False)}
    else:
        raise InputError("give exactly two of principal, instalment and instalments")
    out["levies"] = used
    return _out(out)


def late_payment_interest(
    principal_in_instalment: Number,
    monthly_rate: Number,
    days_late: int,
    kkdf: Number = 0,
    bsmv: Number = 0,
    multiplier: Number = "1.3",
) -> Json:
    """Default interest on one late instalment of a consumer or housing loan: on the principal inside
    the instalment only, for the days late, at no more than 1.3 times the contractual rate, no compounding."""
    return _out(
        installment.late_interest(
            principal_in_instalment, monthly_rate, days_late, kkdf=kkdf, bsmv=bsmv, multiplier=multiplier
        )
    )


def annual_cost_rate(advances: list[list[Number]], payments: list[list[Number]]) -> Json:
    """Annual cost rate of any set of cash flows. advances: what the lender pays out; payments: all the
    borrower pays, fees and levies included. Each as [years from the first drawdown, amount]; the first
    advance is at 0. In Türkiye a month counts as 1/12 of a year and a day as 1/360."""
    try:
        adv = _pairs(advances, "advances")
        pay = _pairs(payments, "payments")
    except InputError as exc:
        raise InputError("advances and payments are lists of [years, amount]") from exc
    x = costrate.annual_cost_rate(adv, pay)
    return {"annual_cost_rate": as_float(x), "annual_cost_rate_percent": as_float(costrate.as_percent(x))}


def levies(product: str, disbursed_on: str) -> Json:
    """KKDF and BSMV rates on loan interest for a product and disbursement date, with the legal basis
    and the date the table was last checked. product: consumer | housing_first_home | commercial_tl | commercial_fx."""
    return _out(rates.levies(product, parse_date(disbursed_on, "disbursed_on")))  # type: ignore[arg-type]


# ---- daily-balance products -------------------------------------------------------------------


def overdraft_interest(
    opening_balance: Number,
    movements: list[list[Any]],
    period_start: str,
    period_end: str,
    monthly_rate: Number,
    kkdf: Number = 0,
    bsmv: Number = 0,
    options: Json | None = None,
) -> Json:
    """Interest on a retail overdraft (KMH, "ek hesap") for a period, from dated movements
    ([date, amount]; positive = more debt), at a monthly rate on daily balances, with KKDF and BSMV.
    options: max_monthly_rate or reference_rate (to check the TCMB ceiling), count_end_day, rounding."""
    moves = _pairs(movements, "movements")
    return _out(
        _call(
            overdraft.period_interest,
            opening_balance,
            moves,
            period_start,
            period_end,
            monthly_rate,
            kkdf=kkdf,
            bsmv=bsmv,
            **_options(options),
        )
    )


def revolving_line(
    opening_balance: Number,
    movements: list[list[Any]],
    start: str,
    end: str,
    annual_rate: Number | list[list[Any]],
    kkdf: Number = 0,
    bsmv: Number = 0,
    options: Json | None = None,
) -> Json:
    """A commercial revolving line or current account (rotatif, borçlu cari hesap) over several accrual
    periods: interest and levies per period on daily balances. annual_rate is one fraction or a list of
    [date, rate] changes. options: accrual (quarterly | monthly | list of dates), year_basis (360 | 365),
    count_end_day, unpaid_interest (capitalise | paid). Day basis and accrual dates are contractual."""
    moves = _pairs(movements, "movements")
    rate_arg: Any = _pairs(annual_rate, "annual_rate") if isinstance(annual_rate, list) else annual_rate
    return _out(
        _call(revolving.line, opening_balance, moves, start, end, rate_arg, kkdf=kkdf, bsmv=bsmv, **_options(options))
    )


def spot_loan(
    principal: Number,
    annual_rate: Number,
    days: int,
    kkdf: Number = 0,
    bsmv: Number = 0,
    fee: Number = 0,
    options: Json | None = None,
) -> Json:
    """A spot loan: principal repaid at maturity, simple interest principal x rate x days / basis, with
    levies and fees, total repayment and annual cost. options: year_basis, interest_days, blocked, cost_year_days."""
    return _out(_call(revolving.spot, principal, annual_rate, days, kkdf=kkdf, bsmv=bsmv, fee=fee, **_options(options)))


def balance_interest(
    balances: list[list[Any]], annual_rate: Number, year_basis: int = 360, kkdf: Number = 0, bsmv: Number = 0
) -> Json:
    """Interest by the interest-number (adat) method: balances is a list of [balance, days];
    interest = sum(balance x days) x annual rate / year basis."""
    return _out(adat.interest(_pairs(balances, "balances"), annual_rate, year_basis=year_basis, kkdf=kkdf, bsmv=bsmv))


def bill_discount(
    face_value: Number,
    annual_rate: Number,
    days: int,
    method: str = "external",
    kkdf: Number = 0,
    bsmv: Number = 0,
    fee: Number = 0,
    options: Json | None = None,
) -> Json:
    """Discounting a bill or cheque (iskonto, iştira): the interest taken up front, the net proceeds, and
    the annual rate actually paid on those proceeds. method: external (interest on the face value) | internal."""
    return _out(
        _call(
            discount.discount,
            face_value,
            annual_rate,
            days,
            method=method,
            kkdf=kkdf,
            bsmv=bsmv,
            fee=fee,
            **_options(options),
        )
    )


def floating_rate_plan(
    principal: Number,
    instalments: int,
    rates_by_instalment: list[list[Any]],
    kkdf: Number = 0,
    bsmv: Number = 0,
    options: Json | None = None,
) -> Json:
    """A variable-rate instalment loan: rates_by_instalment is a list of [instalment number or date, monthly
    rate] from which a new rate applies; the instalment is recomputed on the remaining balance each time.
    How the instalment is adjusted at repricing is contractual (options: adjustment, method, start)."""
    seq = _pairs(rates_by_instalment, "rates_by_instalment")
    return _out(
        _call(floating.repricing_schedule, principal, instalments, seq, kkdf=kkdf, bsmv=bsmv, **_options(options))
    )


def compounded_reference_rate(observations: list[list[Any]], year_basis: int = 365) -> Json:
    """Compound an overnight reference rate (such as TLREF) over a period: observations is a list of
    [annual rate as a fraction, days it applies]; actual/365 as the index is defined."""
    return _out(floating.compound_reference(_pairs(observations, "observations"), year_basis=year_basis))


# ---- cards ------------------------------------------------------------------------------------


def card_minimum_payment(
    statement_balance: Number, card_limit: Number, on: str, contract_ratio: Number | None = None
) -> Json:
    """Minimum payment of a credit card statement under the BDDK decision in force on a date."""
    return _out(card.minimum_payment(statement_balance, card_limit, on, contract_ratio=contract_ratio))


def card_rate_caps(
    reference_rate: Number, statement_balance: Number | None = None, kind: str = "purchase", on: str | None = None
) -> Json:
    """Maximum monthly contractual and default rates for a card from the TCMB reference rate (a monthly
    fraction, e.g. 0.0311). kind: purchase | corporate | cash | fx | restructured. Overdrafts use the cash cap."""
    return _out(_call(card.max_rates, reference_rate, statement_balance, kind=kind, on=on))


def card_statement_interest(
    statement_balance: Number,
    minimum: Number,
    statement_date: str,
    due_date: str,
    next_statement_date: str,
    contractual_rate: Number,
    default_rate: Number,
    payments: list[list[Any]] | None = None,
    kkdf: Number = 0,
    bsmv: Number = 0,
    options: Json | None = None,
) -> Json:
    """Interest that one card statement produces on the next one. payments: [date, amount]. If at least the
    minimum is paid, contractual interest runs on the unpaid part; if less, default interest runs on the
    unpaid part of the minimum (the Regulation's reading; options shortfall_basis="whole_balance" gives the
    Law's wording). Simple interest on daily balances. options also: cash_balance, cash_advances, charges,
    day_count, interest_from, rounding, payment_order."""
    pays = _pairs(payments or [], "payments")
    return _out(
        _call(
            card.statement_interest,
            statement_balance,
            minimum,
            statement_date,
            due_date,
            next_statement_date,
            contractual_rate,
            default_rate,
            payments=pays,
            kkdf=kkdf,
            bsmv=bsmv,
            **_options(options),
        )
    )


# ---- non-cash and fees ------------------------------------------------------------------------


def guarantee_commission(
    amount: Number,
    commission_rate: Number,
    issue_date: str,
    bsmv: Number,
    expiry_date: str | None = None,
    return_date: str | None = None,
    options: Json | None = None,
) -> Json:
    """Commission on a letter of guarantee (teminat mektubu), period by period, with BSMV, the average
    amount outstanding and the cost per year. No law fixes how it is charged: defaults are quarterly
    periods collected in advance, a started period charged in full, no refund. options: rate_period_months
    (12 = annual rate), period_months, collection (advance | arrears), started_period (full | pro_rata),
    day_count, minimum_commission, reductions ([date, amount released]), refund_on_reduction, refund_on_return."""
    opts = _options(options)
    if "reductions" in opts:
        opts["reductions"] = _pairs(opts["reductions"], "reductions")
    return _out(
        _call(
            guarantee.commission_schedule,
            amount,
            commission_rate,
            issue_date,
            bsmv=bsmv,
            expiry_date=expiry_date,
            return_date=return_date,
            **opts,
        )
    )


def fee_cap_check(kind: str, arguments: Json) -> Json:
    """Is a fee within the regulated ceiling? kind and its arguments:

    consumer_allocation  {principal, quoted_fee}                      0.5 % of the principal (TCMB 2020/7)
    commercial_allocation {limit, months, quoted_fee, on}             0.20 % of the limit per year (TCMB 2020/4)
    allocation_with_non_cash {cash_limit, non_cash_limit, months, on, quoted_fee}   the same, non-cash limits included
    commercial_utilisation {amount, days, quoted_fee, revolving, on}  1.10 %, pro-rated under a year
    collateral_cost {third_party_cost, on, quoted_fee}                cost paid to third parties plus 15 %
    cash_advance {advance, fee, instalment}                           1 % of a card cash advance
    commercial_prepayment {disbursed_on, ...}                         early repayment fee on commercial loans
    """
    if not isinstance(arguments, dict):
        raise InputError("arguments must be an object")
    a = dict(arguments)
    if kind == "consumer_allocation":
        cap = rates.CONSUMER_ALLOCATION_FEE_CAP
        extra = sorted(set(a) - {"principal", "quoted_fee", "on"})
        if extra or "principal" not in a:
            raise InputError("consumer_allocation takes principal, and optionally quoted_fee and on")
        if "on" in a and parse_date(a["on"], "on") < cap.since:
            raise InputError(f"no ceiling is recorded before {cap.since.isoformat()}")
        maximum = money(kurus(a["principal"], "principal") * cap.value)
        quoted = a.get("quoted_fee")
        return _out(
            {
                "maximum_fee": maximum,
                "basis": cap.basis,
                "in_force_since": cap.since,
                "exceeds": None if quoted is None else dec(quoted, "quoted_fee") > maximum,
                "note": "the allocation fee is the only fee allowed on a consumer or housing loan",
            }
        )
    table: dict[str, Callable[..., Any]] = {
        "commercial_allocation": revolving.allocation_fee_cap,
        "allocation_with_non_cash": guarantee.allocation_fee_cap,
        "commercial_utilisation": revolving.utilisation_fee_cap,
        "collateral_cost": guarantee.collateral_cost_cap,
        "cash_advance": card.cash_advance_fee_check,
        "commercial_prepayment": prepayment_fee.cap,
    }
    if kind not in table:
        raise InputError(f"unknown kind {kind!r}; one of: consumer_allocation, {', '.join(table)}")
    return _out(_call(table[kind], **a))


TOOLS: dict[str, Callable[..., Json]] = {
    f.__name__: _safe(f)
    for f in (
        loan_plan,
        loan_early_repayment,
        loan_affordability,
        late_payment_interest,
        annual_cost_rate,
        levies,
        overdraft_interest,
        revolving_line,
        spot_loan,
        balance_interest,
        bill_discount,
        floating_rate_plan,
        compounded_reference_rate,
        card_minimum_payment,
        card_rate_caps,
        card_statement_interest,
        guarantee_commission,
        fee_cap_check,
    )
}
