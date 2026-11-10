"""Rates set by law or by the regulators in Türkiye, each with the date it took effect and its source.

Nothing here is a constant of nature. Every table is a list of dated entries; a lookup needs the
date the loan is disbursed (levies apply by disbursement date) and returns the entry in force with
its legal basis, so that a result can always say which rule it used. Check the source before
relying on an entry: decrees change these numbers without notice, and this table was last compared
with the sources on 2026-11-10.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from ..errors import InputError

Product = Literal["consumer", "housing_first_home", "commercial_tl", "commercial_fx"]
CHECKED_ON = dt.date(2026, 11, 10)


@dataclass(frozen=True)
class Dated:
    since: dt.date
    value: Decimal
    basis: str


_D = Decimal
# BSMV (banking and insurance transactions tax) on interest
BSMV: dict[str, tuple[Dated, ...]] = {
    "consumer": (
        Dated(dt.date(1998, 9, 1), _D("0.05"), "general rate; decree 98/11591"),
        Dated(dt.date(2022, 6, 11), _D("0.10"), "Presidential Decision 5729 (Official Gazette 11.06.2022)"),
        Dated(dt.date(2023, 7, 7), _D("0.15"), "Presidential Decision 7345 (Official Gazette 07.07.2023)"),
    ),
    "housing_first_home": (
        Dated(dt.date(2007, 3, 6), _D("0"), "Law 6802 Article 29(y): exempt if the borrower owns no dwelling"),
    ),
    "commercial_tl": (Dated(dt.date(1998, 9, 1), _D("0.05"), "general rate; decree 98/11591"),),
    "commercial_fx": (Dated(dt.date(1998, 9, 1), _D("0.05"), "general rate; decree 98/11591"),),
}
# KKDF (resource utilisation support fund) on interest
KKDF: dict[str, tuple[Dated, ...]] = {
    "consumer": (Dated(dt.date(2010, 10, 28), _D("0.15"), "Council of Ministers Decision 2010/974"),),
    "housing_first_home": (Dated(dt.date(1988, 6, 7), _D("0"), "Decision 88/12944 Article 4: housing loans"),),
    "commercial_tl": (
        Dated(dt.date(2025, 7, 19), _D("0"), "Presidential Decision 10094 (Official Gazette 18.07.2025)"),
    ),
    "commercial_fx": (
        Dated(dt.date(2025, 7, 19), _D("0.01"), "Presidential Decision 10094 (Official Gazette 18.07.2025)"),
    ),
}

KKDF_ON_PRINCIPAL = frozenset({"commercial_fx"})

# Caps on fees (TCMB communiqués), as fractions of the stated base
CONSUMER_ALLOCATION_FEE_CAP = Dated(
    dt.date(2020, 3, 7), _D("0.005"), "TCMB Communiqué 2020/7 Article 10(1): of the principal disbursed"
)
COMMERCIAL_ALLOCATION_FEE_CAP = Dated(
    dt.date(2025, 11, 1), _D("0.002"), "TCMB Communiqué 2020/4 Article 9 as amended by 2025/24: of the limit, per year"
)
COMMERCIAL_UTILISATION_FEE_CAP = Dated(
    dt.date(2025, 11, 1), _D("0.011"), "TCMB Communiqué 2020/4 Article 9 as amended by 2025/24: of the amount drawn"
)
DEFAULT_RATE_MULTIPLIER_CAP = Dated(
    dt.date(2015, 11, 22), _D("1.3"), "Tüketici Kredisi Sözleşmeleri Yönetmeliği Article 18(2)"
)


def _lookup(table: dict[str, tuple[Dated, ...]], product: str, on: dt.date, what: str) -> Dated:
    if product not in table:
        raise InputError(f"unknown product {product!r}; one of: {', '.join(table)}")
    entry = None
    for e in table[product]:
        if e.since <= on:
            entry = e
    if entry is None:
        raise InputError(f"no {what} rate is recorded for {product} before {table[product][0].since.isoformat()}")
    return entry


def levies(product: Product, disbursed_on: dt.date) -> dict[str, Any]:
    """KKDF and BSMV rates for a loan disbursed on a given date, with their legal basis.

    ``kkdf`` and ``bsmv`` are charged on the interest of each period. On foreign-currency and gold
    loans KKDF is not a levy on interest: it is charged once, on the principal, when the loan is
    drawn. It is returned separately as ``kkdf_on_principal_at_drawdown`` and ``kkdf`` is zero.
    (The base is taken from a secondary copy of the KKDF communiqué; confirm it before relying on it.)
    """
    k = _lookup(KKDF, product, disbursed_on, "KKDF")
    b = _lookup(BSMV, product, disbursed_on, "BSMV")
    on_principal = product in KKDF_ON_PRINCIPAL
    return {
        "product": product,
        "disbursed_on": disbursed_on.isoformat(),
        "kkdf": _D("0") if on_principal else k.value,
        "kkdf_on_principal_at_drawdown": k.value if on_principal else _D("0"),
        "kkdf_basis": k.basis + ("; charged once on the principal at drawdown" if on_principal else ""),
        "kkdf_since": k.since.isoformat(),
        "bsmv": b.value,
        "bsmv_basis": b.basis,
        "bsmv_since": b.since.isoformat(),
        "table_checked_on": CHECKED_ON.isoformat(),
        "note": "rates change by decree; confirm against the official source for dates after the table was checked",
    }
