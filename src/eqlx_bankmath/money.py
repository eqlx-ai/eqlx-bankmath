"""Exact decimal arithmetic for money and rates.

Everything in this library is computed with :class:`decimal.Decimal`. Binary floating point cannot
represent 0.1 or 899.75 exactly, and a bank statement must add up to the kuruş. Floats are accepted
as input only through their shortest decimal representation (``0.0149`` means exactly 0.0149).

Rounding is half-up to two decimals unless stated otherwise: that is what the worked examples in the
annexes of the Turkish consumer credit regulations use.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext

from .errors import InputError

Number = Decimal | int | str | float
ZERO = Decimal(0)
ONE = Decimal(1)
CENT = Decimal("0.01")
PRECISION = 40
MAX_MAGNITUDE = Decimal("1e13")  # above this a float can no longer carry the kuruş in JSON output
MIN_MAGNITUDE = Decimal("1e-12")
MAX_COUNT = 1_000_000


def dec(value: Number, name: str = "value") -> Decimal:
    """Convert to Decimal without picking up binary noise."""
    if isinstance(value, bool):
        raise InputError(f"{name} must be a number, got {value!r}")
    if isinstance(value, Decimal):
        out = value
    elif isinstance(value, int):
        out = Decimal(value)
    elif isinstance(value, float):
        out = Decimal(repr(value))
    elif isinstance(value, str):
        try:
            out = Decimal(value.strip())
        except InvalidOperation:
            raise InputError(f"{name}: {value!r} is not a number") from None
    else:
        raise InputError(f"{name} must be a number, got {value!r}")
    if not out.is_finite():
        raise InputError(f"{name} must be finite, got {value!r}")
    if out != 0 and not (MIN_MAGNITUDE <= abs(out) <= MAX_MAGNITUDE):
        raise InputError(f"{name} is outside the range this library computes on (1e-12 to 1e13), got {value!r}")
    return out


def money(value: Decimal, places: int = 2) -> Decimal:
    """Round half-up to ``places`` decimals (2 = kuruş)."""
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def non_negative(value: Number, name: str) -> Decimal:
    d = dec(value, name)
    if d < 0:
        raise InputError(f"{name} must not be negative, got {value!r}")
    return d


def positive(value: Number, name: str) -> Decimal:
    d = dec(value, name)
    if d <= 0:
        raise InputError(f"{name} must be positive, got {value!r}")
    return d


def rate(value: Number, name: str, *, maximum: Number = 100) -> Decimal:
    """A rate as a fraction (0.0149 for 1.49 %), not negative and not absurdly large."""
    d = non_negative(value, name)
    if d > dec(maximum):
        raise InputError(f"{name} is a fraction (0.05 for 5 %), got {value!r}")
    return d


def whole(value: object, name: str, *, minimum: int = 0, maximum: int = MAX_COUNT) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise InputError(f"{name} must be a whole number of at least {minimum}, got {value!r}")
    if value > maximum:
        raise InputError(f"{name} must not exceed {maximum}, got {value!r}")
    return value


def kurus(value: Number, name: str) -> Decimal:
    """A positive amount of money with at most two decimals."""
    d = positive(value, name)
    if d != money(d):
        raise InputError(f"{name} has more than two decimals, got {value!r}")
    return d


def power(base: Decimal, exponent: Decimal | int) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return base ** Decimal(exponent)


def as_float(value: Decimal) -> float:
    """For JSON output. A value already rounded to kuruş prints back exactly."""
    return float(value)
