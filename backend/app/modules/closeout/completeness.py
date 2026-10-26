# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure completeness maths and localized status labels for closeout packages.

The closeout service derives a package completeness percentage (delivered
required slots over required slots) inline in several places, and its slot and
package status words were English only. These helpers give that logic one
guarded, tested home and a plain-language, localized surface a UI can use, with
no database, ORM, or ``app.*`` import so they unit-test on any runner.

Nothing here is currency or locale specific: a closeout package is measured in
plain counts, and dates elsewhere in the module are ISO 8601.
"""

from __future__ import annotations

from app.core.i18n import catalogue_table

#: Slot delivery states the service assigns (see ``_slot_status``).
SLOT_STATUS_LABELS: dict[str, dict[str, str]] = catalogue_table(
    "closeout.slot_status_labels", ("verified", "bound", "empty"), by_key=True
)

#: Package lifecycle states (draft -> in_progress -> ready -> issued).
PACKAGE_STATUS_LABELS: dict[str, dict[str, str]] = catalogue_table(
    "closeout.package_status_labels", ("draft", "in_progress", "ready", "issued"), by_key=True
)

#: Completeness bands over the percentage.
BAND_EMPTY = "empty"
BAND_PARTIAL = "partial"
BAND_COMPLETE = "complete"


def _label(catalog: dict[str, dict[str, str]], key: str, lang: str) -> str:
    per_lang = catalog.get(key)
    if per_lang is None:
        return key
    return per_lang.get(lang) or per_lang["en"]


def slot_status_label(status: str, lang: str = "en") -> str:
    """Localized word for a slot delivery status, English as fallback."""
    return _label(SLOT_STATUS_LABELS, status, lang)


def package_status_label(status: str, lang: str = "en") -> str:
    """Localized word for a package lifecycle status, English as fallback."""
    return _label(PACKAGE_STATUS_LABELS, status, lang)


def completeness_pct(delivered: int, required: int) -> int:
    """Percent of required slots delivered, as a whole number in [0, 100].

    Mirrors the service rule: a package with no required slots is complete
    (100), otherwise it is ``round(delivered * 100 / required)``. Delivered is
    clamped into ``[0, required]`` so a stray over-count can never report above
    100 or below 0. Negative inputs are a caller error and raise ``ValueError``.
    """
    if delivered < 0 or required < 0:
        raise ValueError("delivered and required counts cannot be negative")
    if required == 0:
        return 100
    capped = min(delivered, required)
    return round(capped * 100 / required)


def completeness_band(pct: int) -> str:
    """Classify a completeness percent into empty / partial / complete."""
    if pct <= 0:
        return BAND_EMPTY
    if pct >= 100:
        return BAND_COMPLETE
    return BAND_PARTIAL


def explain_completeness(delivered: int, required: int) -> str:
    """One-line plain-language statement of how complete a package is."""
    pct = completeness_pct(delivered, required)
    if required == 0:
        return "No required documents for this package, so it counts as complete (100%)."
    capped = min(delivered, required)
    outstanding = required - capped
    if outstanding == 0:
        return f"All {required} required documents are in: the package is complete (100%)."
    doc_word = "document" if outstanding == 1 else "documents"
    return f"{capped} of {required} required documents in ({pct}%); {outstanding} {doc_word} still outstanding."


__all__ = [
    "SLOT_STATUS_LABELS",
    "PACKAGE_STATUS_LABELS",
    "BAND_EMPTY",
    "BAND_PARTIAL",
    "BAND_COMPLETE",
    "slot_status_label",
    "package_status_label",
    "completeness_pct",
    "completeness_band",
    "explain_completeness",
]
