# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""How a country's law protects a subcontractor's payment, per country. Data, not branches.

Two protections recur across construction laws: on public works the buyer
pays an accepted subcontractor directly once its share reaches an amount, and
on private works the main contractor has to secure the subcontractor's
payment. This table writes each country's figures down once with the article
they come from; two rules of the ``contracts`` set read it
(:class:`app.modules.contracts.validators.SubcontractDirectPaymentRule` and
:class:`app.modules.contracts.validators.SubcontractPaymentGuaranteeRule`).
A country without a row is never measured.

France, loi n° 75-1334 du 31 décembre 1975 relative à la sous-traitance:

* Art. 6 and Code de la commande publique L2193-11 and R2193-10: an accepted
  subcontractor whose payment terms were approved is paid directly by the
  public buyer when its share reaches EUR 600 including tax, and no clause
  may waive it. The amount is compared with the subcontract's recorded total;
  record that total including tax.
* Art. 14: on private works the main contractor guarantees the payments due
  to the subcontractor by a personal and joint bank guarantee (caution) or by
  a delegation of payment on the owner; without one the subcontract can be
  voided. Art. 14-1 (the owner's duty once aware of an unaccepted
  subcontractor) and the 15-day acceptance procedure of R2193-10 ff. were not
  read in a primary text and are not encoded.

Pure data; no ORM, no I/O.
"""

from __future__ import annotations

import copy
from typing import Any

_LOI_75_1334_URL = "https://www.legifrance.gouv.fr/loda/id/JORFTEXT000000889241"

#: The table, keyed by ISO 3166-1 alpha-2. Each figure carries its source.
SUBCONTRACT_PAYMENT_PROTECTION: dict[str, dict[str, Any]] = {
    "FR": {
        "law": "Loi n° 75-1334 du 31 décembre 1975 relative à la sous-traitance; Code de la commande publique",
        "public_direct_payment_min_amount": {
            "value": 600,
            "currency": "EUR",
            "includes_tax": True,
            "statute_reference": "Loi 75-1334, art. 6; Code de la commande publique, art. L2193-11 and R2193-10",
            "source_url": _LOI_75_1334_URL,
            "read_date": "2026-10-19",
            "effective_date": None,
            "note": (
                "Direct payment is owed to an accepted subcontractor whose payment terms the buyer approved, once "
                "its share reaches EUR 600 including tax. It cannot be waived."
            ),
        },
        "private_payment_guarantee_kinds": {
            "value": ["caution", "delegation_de_paiement"],
            "currency": None,
            "includes_tax": None,
            "statute_reference": "Loi 75-1334, art. 14",
            "source_url": _LOI_75_1334_URL,
            "read_date": "2026-10-19",
            "effective_date": None,
            "note": (
                "A personal and joint bank guarantee for the subcontract, or a delegation of payment on the "
                "owner. Without one the subcontract can be voided at the subcontractor's request."
            ),
        },
    },
}

_FIGURES = ("public_direct_payment_min_amount", "private_payment_guarantee_kinds")
_FIGURE_KEYS = frozenset(
    {"value", "currency", "includes_tax", "statute_reference", "source_url", "read_date", "effective_date", "note"}
)


def _validate() -> None:
    for country, row in SUBCONTRACT_PAYMENT_PROTECTION.items():
        if len(country) != 2 or not country.isupper():
            raise ValueError(f"country key {country!r} is not ISO 3166-1 alpha-2")
        if not row.get("law") or set(row) != {"law", *_FIGURES}:
            raise ValueError(f"{country} must name its law and carry exactly {_FIGURES}")
        for field in _FIGURES:
            figure = row[field]
            if set(figure) != _FIGURE_KEYS or not figure["statute_reference"] or not figure["note"]:
                raise ValueError(f"{country}.{field} must be a sourced figure with {sorted(_FIGURE_KEYS)}")


_validate()


def protection_for(country_code: str | None) -> dict[str, Any] | None:
    """The subcontractor payment protections of ``country_code``, or ``None``. A copy."""
    row = SUBCONTRACT_PAYMENT_PROTECTION.get((country_code or "").strip().upper())
    return copy.deepcopy(row) if row is not None else None


__all__ = ["SUBCONTRACT_PAYMENT_PROTECTION", "protection_for"]
