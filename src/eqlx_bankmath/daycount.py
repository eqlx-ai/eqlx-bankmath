"""Counting days and year fractions. The convention is always an explicit choice.

* ``actual``    calendar days between two dates (first day excluded, last included)
* ``30/360``    every month counts as 30 days
* year basis    360 or 365

The Turkish consumer credit regulations measure time for the annual cost rate in a year of 360 days
and 12 equal months of 30 days. Interest between two instalment dates is computed on the actual
days divided by 30 (regulation annexes: 03.07 to 24.07 is 21 days, interest = balance x rate x 21/30).
"""

from __future__ import annotations

import calendar
import datetime as dt
from decimal import Decimal
from typing import Literal

from .errors import InputError

DayCount = Literal["actual/360", "actual/365", "30/360"]


def actual_days(start: dt.date, end: dt.date) -> int:
    if end < start:
        raise InputError("the end date is before the start date")
    return (end - start).days


def days_30_360(start: dt.date, end: dt.date) -> int:
    if end < start:
        raise InputError("the end date is before the start date")
    d1, d2 = min(start.day, 30), min(end.day, 30)
    return (end.year - start.year) * 360 + (end.month - start.month) * 30 + (d2 - d1)


def days(start: dt.date, end: dt.date, convention: DayCount = "actual/360") -> int:
    if convention == "30/360":
        return days_30_360(start, end)
    if convention in ("actual/360", "actual/365"):
        return actual_days(start, end)
    raise InputError(f"unknown day count {convention!r}")


def year_basis(convention: DayCount) -> int:
    if convention in ("actual/360", "30/360"):
        return 360
    if convention == "actual/365":
        return 365
    raise InputError(f"unknown day count {convention!r}")


def add_months(date: dt.date, months: int) -> dt.date:
    """Same day of a later month; the last day of the month if that day does not exist."""
    index = date.year * 12 + date.month - 1 + months
    year, month = divmod(index, 12)
    return dt.date(year, month + 1, min(date.day, calendar.monthrange(year, month + 1)[1]))


def year_fraction_equal_months(start: dt.date, end: dt.date) -> Decimal:
    """Whole months as twelfths of a year plus the remaining days over 360.

    Whole months are counted backwards from ``end``, as the housing finance regulation describes;
    the days left over at the start are divided by 360.
    """
    if end < start:
        raise InputError("the end date is before the start date")
    months = (end.year - start.year) * 12 + (end.month - start.month)
    while months > 0 and add_months(end, -months) < start:
        months -= 1
    rest = (add_months(end, -months) - start).days
    return Decimal(months) / 12 + Decimal(rest) / 360


def parse_date(value: object, name: str = "date") -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            pass
    raise InputError(f"{name} must be a date like 2026-11-10, got {value!r}")
