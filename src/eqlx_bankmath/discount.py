"""Discounting bills and cheques (iskonto, iştira), and any loan whose interest is collected in advance.

The bank pays the holder of a bill less than its face value today and collects the face value at
maturity. Two ways of computing the deduction exist:

    external discount (dış iskonto)   D = C x n x t / Y              interest on the face value
    internal discount (iç iskonto)    D = C x n x t / (Y + n x t)    interest on the proceeds

with C the face value, n the days to maturity, t the annual discount rate as a fraction and Y the
year basis. Banks discount short-term paper with the external method; because the interest is taken
up front on the full face value, the rate actually paid on the money received is higher than the
quoted rate. None of this is fixed by a rule for commercial customers: the method, the year basis
(360 in current teaching material, 365 in older textbooks) and how the days are counted come from
the contract and are arguments here.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Literal

from .costrate import as_percent
from .daycount import parse_date
from .errors import InputError
from .money import ONE, Number, as_float, money, non_negative, positive, power, rate, whole

Method = Literal["external", "internal"]


def _basis(value: int, name: str, allowed: tuple[int, ...]) -> int:
    if isinstance(value, bool) or value not in allowed:
        raise InputError(f"{name} must be one of {', '.join(str(a) for a in allowed)}")
    return value


def _method(method: str) -> str:
    if method not in ("external", "internal"):
        raise InputError("method must be external or internal")
    return method


def term_days(value_date: dt.date | str, maturity: dt.date | str, *, count_both_days: bool = False) -> int:
    """Days from the day the bank pays to the maturity of the bill.

    By default the calendar days between the two dates. With ``count_both_days`` the transaction
    day and the maturity day are both counted, one day more; some banks do this, it is practice.
    """
    first, last = parse_date(value_date, "value_date"), parse_date(maturity, "maturity")
    if last <= first:
        raise InputError("the maturity must be after the value date")
    return (last - first).days + (1 if count_both_days else 0)


def _deduction(c: Decimal, t: Decimal, n: int, basis: int, method: str) -> Decimal:
    weight = t * n
    if method == "external":
        if weight >= basis:
            raise InputError("the discount would take the whole face value; check the rate and the days")
        return c * weight / basis
    return c * weight / (basis + weight)


def _upfront(
    c: Decimal, t: Decimal, n: int, basis: int, method: str, k: Decimal, b: Decimal, fee: Decimal, cost_year: int
) -> dict[str, Decimal]:
    deducted = money(_deduction(c, t, n, basis, method))
    kk, bs = money(deducted * k), money(deducted * b)
    fee_tax = money(fee * b)
    net = c - deducted - kk - bs - fee - fee_tax
    if net <= 0:
        raise InputError("the deductions leave nothing to pay out")
    growth = c / net
    return {
        "deducted": deducted,
        "kkdf": kk,
        "bsmv": bs,
        "fee_tax": fee_tax,
        "net": net,
        "simple": (growth - ONE) * basis / n,
        "rate_only": t / (ONE - t * n / basis) if method == "external" else t,
        "effective": power(growth, Decimal(cost_year) / n) - ONE,
    }


def _conventions(basis: int, method: str, cost_year: int) -> dict[str, Any]:
    return {
        "method": "external: interest on the face value, deducted up front"
        if method == "external"
        else "internal: interest on the proceeds",
        "formula": f"C x n x t / {basis}" if method == "external" else f"C x n x t / ({basis} + n x t)",
        "year_basis": basis,
        "levies": "KKDF and BSMV on the amount deducted, collected up front; BSMV also on the fee",
        "rounding": "deduction rounded half-up to 0.01; each levy rounded separately",
        "simple_rate_on_net": f"(amount due / net amount received - 1) x {basis} / days",
        "annual_effective_rate": f"(amount due / net amount received) ^ ({cost_year} / days) - 1; "
        "own convention, no regulation prescribes it for commercial customers",
    }


def discount(
    face_value: Number,
    annual_rate: Number,
    days: int,
    *,
    method: Method = "external",
    year_basis: int = 360,
    kkdf: Number = 0,
    bsmv: Number = 0,
    fee: Number = 0,
    cost_year_days: int = 365,
) -> dict[str, Any]:
    """Discount a bill or cheque: the deduction, what the holder receives, and what it really costs.

    * ``method``: ``external`` (the default, bank practice for short-term paper) or ``internal``.
    * ``days``: days to maturity; see :func:`term_days` for counting them from dates.
    * ``year_basis``: 360 or 365. Practice; neither is prescribed.
    * ``kkdf`` / ``bsmv``: levies as fractions of the discount, deducted up front with it. ``bsmv``
      is also charged on the fee (Law 6802 Article 28 taxes everything the bank receives).
    * ``fee``: a fee deducted up front, without tax.
    * ``cost_year_days``: 365 or 360, the year of the annual effective rate.

    Besides the amounts the result gives three rates on the money actually received: the simple
    rate on the net proceeds, the same without levies and fees (for the external method the
    identity ``t / (1 - n t / Y)``), and the annual effective (compound) rate.
    """
    c = positive(face_value, "face_value")
    t = rate(annual_rate, "annual_rate")
    n = whole(days, "days", minimum=1)
    basis = _basis(year_basis, "year_basis", (360, 365, 366))
    cost_year = _basis(cost_year_days, "cost_year_days", (360, 365))
    how = _method(method)
    fee_d = non_negative(fee, "fee")
    x = _upfront(c, t, n, basis, how, rate(kkdf, "kkdf", maximum=1), rate(bsmv, "bsmv", maximum=1), fee_d, cost_year)
    return {
        "face_value": as_float(c),
        "annual_rate": as_float(t),
        "days": n,
        "discount": as_float(x["deducted"]),
        "proceeds_before_levies": as_float(c - x["deducted"]),
        "kkdf": as_float(x["kkdf"]),
        "bsmv": as_float(x["bsmv"]),
        "fee": as_float(fee_d),
        "bsmv_on_fee": as_float(x["fee_tax"]),
        "net_proceeds": as_float(x["net"]),
        "simple_rate_on_net_percent": as_float(as_percent(x["simple"])),
        "equivalent_rate_without_levies_percent": as_float(as_percent(x["rate_only"])),
        "annual_effective_rate_percent": as_float(as_percent(x["effective"])),
        "conventions": _conventions(basis, how, cost_year),
    }


def face_value_for_proceeds(
    proceeds: Number, annual_rate: Number, days: int, *, method: Method = "external", year_basis: int = 360
) -> Decimal:
    """Face value a bill must have so that its discounted value is ``proceeds`` (before levies and fees).

    External: ``C = P x Y / (Y - n x t)``. Internal: ``C = P x (Y + n x t) / Y``. Rounded to 0.01.
    """
    p = positive(proceeds, "proceeds")
    t = rate(annual_rate, "annual_rate")
    n = whole(days, "days", minimum=1)
    basis = _basis(year_basis, "year_basis", (360, 365, 366))
    weight = t * n
    if _method(method) == "external":
        if weight >= basis:
            raise InputError("no face value gives these proceeds; check the rate and the days")
        return money(p * basis / (basis - weight))
    return money(p * (basis + weight) / basis)


def interest_in_advance(
    principal: Number,
    annual_rate: Number,
    days: int,
    *,
    year_basis: int = 360,
    kkdf: Number = 0,
    bsmv: Number = 0,
    fee: Number = 0,
    cost_year_days: int = 365,
) -> dict[str, Any]:
    """A loan whose interest is collected on the day it is drawn (peşin faizli kredi).

    The borrower signs for ``principal``, receives it less the interest for the whole term
    (``principal x annual rate x days / year basis``), the levies on that interest and any fee, and
    repays ``principal`` at maturity. This is the arithmetic of the external discount; the result
    shows the rate the borrower really pays on the money received.
    """
    c = positive(principal, "principal")
    t = rate(annual_rate, "annual_rate")
    n = whole(days, "days", minimum=1)
    basis = _basis(year_basis, "year_basis", (360, 365, 366))
    cost_year = _basis(cost_year_days, "cost_year_days", (360, 365))
    fee_d = non_negative(fee, "fee")
    x = _upfront(
        c, t, n, basis, "external", rate(kkdf, "kkdf", maximum=1), rate(bsmv, "bsmv", maximum=1), fee_d, cost_year
    )
    conventions = _conventions(basis, "external", cost_year)
    conventions["method"] = "interest on the principal for the whole term, collected at drawdown"
    conventions["formula"] = f"principal x annual rate x days / {basis}"
    return {
        "principal": as_float(c),
        "annual_rate": as_float(t),
        "days": n,
        "interest_collected_in_advance": as_float(x["deducted"]),
        "kkdf": as_float(x["kkdf"]),
        "bsmv": as_float(x["bsmv"]),
        "fee": as_float(fee_d),
        "bsmv_on_fee": as_float(x["fee_tax"]),
        "net_received": as_float(x["net"]),
        "repaid_at_maturity": as_float(c),
        "total_cost": as_float(c - x["net"]),
        "simple_rate_on_net_percent": as_float(as_percent(x["simple"])),
        "equivalent_rate_without_levies_percent": as_float(as_percent(x["rate_only"])),
        "annual_effective_rate_percent": as_float(as_percent(x["effective"])),
        "conventions": conventions,
    }
