# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""International, locale-safe helpers for the document register.

Pure functions only. No database, no I/O, no framework dependency. Every
helper here is deterministic and safe to call from a unit test or a request
handler. The goal is clarity for construction teams worldwide:

* dates are rendered as ISO 8601 (unambiguous across regions),
* file sizes are rendered with an explicit unit (never a bare number),
* status and type words are localised to en / de / ru with an English
  fallback for any language we do not carry a word for,
* aggregate figures guard against an empty register (no divide by zero,
  no NaN, no infinity) and expose the components they are built from so a
  reader can see exactly how each figure was derived.

The register stores its approval lifecycle in the ISO 19650 common data
environment (CDE) state: ``wip`` -> ``shared`` -> ``published`` ->
``archived``. ``published`` is the "approved and issued for use" state.
Document types are the register categories (``drawing``, ``contract``,
``specification``, ``photo``, ``correspondence``, ``reality_capture``,
``other``). These vocabularies mirror ``service.VALID_CATEGORIES`` and
``DocumentService.VALID_CDE_TRANSITIONS`` so this module stays additive and
never redefines the source of truth.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from app.core.i18n import catalogue_table

# ── Language vocabulary ────────────────────────────────────────────────────

DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES: tuple[str, ...] = ("en", "de", "ru")

# Sentinels for records that carry no value in the relevant column. Kept
# distinct from a real category / status so counts stay faithful.
CATEGORY_UNKNOWN = "other"
STATUS_UNSET = "unset"

# Ordered approval lifecycle (CDE state). Index order is meaningful: a
# document only ever moves forward through this sequence.
APPROVAL_STATES: tuple[str, ...] = ("wip", "shared", "published", "archived")

# The CDE state(s) that count as "approved and issued for use".
APPROVED_STATES: frozenset[str] = frozenset({"published"})

# Localised document-type (category) words. English is the fallback.
_CATEGORY_LABELS: dict[str, dict[str, str]] = catalogue_table(
    "documents.intl.category_labels",
    ("drawing", "contract", "specification", "photo", "correspondence", "reality_capture", "other"),
)

# Localised approval-status (CDE state) words. English is the fallback.
_STATUS_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "wip": "Work in progress",
        "shared": "Shared for review",
        "published": "Published (approved)",
        "archived": "Archived",
        STATUS_UNSET: "Not set",
    },
    "de": {
        "wip": "In Bearbeitung",
        "shared": "Geteilt zur Abstimmung",
        "published": "Veroeffentlicht (freigegeben)",
        "archived": "Archiviert",
        STATUS_UNSET: "Nicht gesetzt",
    },
    "ru": {
        "wip": "В работе",
        "shared": "На согласовании",
        "published": "Опубликовано (утверждено)",
        "archived": "В архиве",
        STATUS_UNSET: "Не задан",
    },
}

# One-line plain-language meaning of each approval status. English only;
# used as the explainer sentence frame.
_STATUS_MEANING: dict[str, str] = {
    "wip": "Draft being worked on, not yet shared.",
    "shared": "Shared for coordination and review, not yet approved.",
    "published": "Approved and issued for use.",
    "archived": "Superseded, kept for the record.",
    STATUS_UNSET: "No approval status recorded yet.",
}

# File-size unit ladders. Binary steps by 1024 (KiB, MiB, ...), decimal
# steps by 1000 (kB, MB, ...). Both label the unit explicitly so a reader
# never has to guess the base.
_BINARY_UNITS: tuple[str, ...] = ("B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB")
_DECIMAL_UNITS: tuple[str, ...] = ("B", "kB", "MB", "GB", "TB", "PB", "EB")


# ── Small internal helpers ─────────────────────────────────────────────────


def normalize_language(lang: str | None) -> str:
    """Return a supported language code, defaulting to English.

    Accepts full locale tags (``de-DE``) and mixed case (``DE``); only the
    leading subtag is considered. Anything we do not carry falls back to
    ``en`` so callers never have to guard the language themselves.
    """
    if not lang:
        return DEFAULT_LANGUAGE
    primary = str(lang).strip().lower().replace("_", "-").split("-", 1)[0]
    return primary if primary in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def _get_field(item: Any, name: str, default: Any = None) -> Any:
    """Read ``name`` from a mapping or an object, returning ``default``.

    Lets every helper accept either an ORM row, a Pydantic model, a plain
    object, or a dict without the caller having to normalise first.
    """
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


# ── Dates ──────────────────────────────────────────────────────────────────


def to_iso8601(value: datetime | date | str | None) -> str | None:
    """Render a date or datetime as an ISO 8601 string.

    ISO 8601 is region-neutral (2026-07-05, never 07/05/2026 vs 05/07/2026),
    so it is the only date format the register emits. ``None`` maps to
    ``None`` (no date recorded). A string is assumed to be ISO already and
    passed through unchanged. Any other type is a programming error and
    raises ``ValueError`` rather than returning something ambiguous.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    msg = f"cannot render {type(value).__name__} as an ISO 8601 date"
    raise ValueError(msg)


# ── File sizes ─────────────────────────────────────────────────────────────


def format_file_size(num_bytes: int, *, binary: bool = True, precision: int = 1) -> str:
    """Format a byte count as a human-readable size with an explicit unit.

    Args:
        num_bytes: Size in bytes. Must be a non-negative integer. ``bool``
            is rejected (a stray ``True`` should never read as ``1 B``).
        binary: When ``True`` (default) step by 1024 and label KiB / MiB /
            GiB so the base is unambiguous. When ``False`` step by 1000 and
            label kB / MB / GB.
        precision: Decimal places for scaled values. Bytes are always shown
            whole (``512 B``, never ``512.0 B``).

    Returns:
        A string such as ``"0 B"``, ``"512 B"``, ``"1.5 MiB"`` or
        ``"1.5 MB"``. Always carries a unit; never a bare number.

    Raises:
        ValueError: If ``num_bytes`` is a bool, not an int, or negative.
    """
    if isinstance(num_bytes, bool) or not isinstance(num_bytes, int):
        msg = "file size must be an integer number of bytes"
        raise ValueError(msg)
    if num_bytes < 0:
        msg = "file size cannot be negative"
        raise ValueError(msg)

    base = 1024 if binary else 1000
    units = _BINARY_UNITS if binary else _DECIMAL_UNITS

    if num_bytes < base:
        return f"{num_bytes} {units[0]}"

    size = float(num_bytes)
    idx = 0
    while size >= base and idx < len(units) - 1:
        size /= base
        idx += 1
    return f"{size:.{precision}f} {units[idx]}"


# ── Localisation of type / status words ────────────────────────────────────


def localize_category(category: str | None, lang: str = DEFAULT_LANGUAGE) -> str:
    """Localise a document-type (category) code with an English fallback.

    An unknown or blank category renders as the localised "Other" word so
    the UI never shows a raw code. Any unrecognised language falls back to
    English.
    """
    language = normalize_language(lang)
    key = category if category in _CATEGORY_LABELS["en"] else CATEGORY_UNKNOWN
    table = _CATEGORY_LABELS.get(language, _CATEGORY_LABELS["en"])
    return table.get(key) or _CATEGORY_LABELS["en"][key]


def localize_status(status: str | None, lang: str = DEFAULT_LANGUAGE) -> str:
    """Localise an approval-status (CDE state) code with an English fallback.

    A blank or unknown status renders as the localised "Not set" word.
    """
    language = normalize_language(lang)
    key = status if status in _STATUS_LABELS["en"] else STATUS_UNSET
    table = _STATUS_LABELS.get(language, _STATUS_LABELS["en"])
    return table.get(key) or _STATUS_LABELS["en"][key]


# ── Counts ─────────────────────────────────────────────────────────────────


def count_by_category(items: Iterable[Any]) -> dict[str, int]:
    """Count documents by type (category).

    A blank or missing category is folded into ``other`` so the totals
    always reconcile with the record count. Returns an empty dict for an
    empty register (never raises).
    """
    counts: dict[str, int] = {}
    for item in items:
        raw = _get_field(item, "category")
        key = raw if raw in _CATEGORY_LABELS["en"] else CATEGORY_UNKNOWN
        counts[key] = counts.get(key, 0) + 1
    return counts


def count_by_status(items: Iterable[Any]) -> dict[str, int]:
    """Count documents by approval status (CDE state).

    A record with no ``cde_state`` is counted under ``unset`` so nothing is
    silently dropped. Returns an empty dict for an empty register.
    """
    counts: dict[str, int] = {}
    for item in items:
        raw = _get_field(item, "cde_state")
        key = raw if raw in APPROVAL_STATES else STATUS_UNSET
        counts[key] = counts.get(key, 0) + 1
    return counts


# ── Latest-revision selection ──────────────────────────────────────────────


def _revision_sort_key(item: Any) -> tuple[int, str, int, str]:
    """Deterministic ordering key: newest revision sorts highest.

    Preference order: the flagged current revision, then the highest
    revision code, then the highest integer version, then the most recent
    created timestamp. Every component is total-ordered so ``max`` is
    stable even on messy data.
    """
    is_current = 1 if _get_field(item, "is_current_revision") else 0
    revision_code = str(_get_field(item, "revision_code") or "")
    version = _get_field(item, "version")
    version_int = version if isinstance(version, int) and not isinstance(version, bool) else 0
    created = to_iso8601(_get_field(item, "created_at")) or ""
    return (is_current, revision_code, version_int, created)


def latest_revision(revisions: Iterable[Any]) -> Any:
    """Return the newest revision from a set of revisions of one document.

    Args:
        revisions: One or more revision rows of the same logical document.

    Returns:
        The single newest revision (see :func:`_revision_sort_key`).

    Raises:
        ValueError: If ``revisions`` is empty. "Latest of nothing" has no
            well-defined answer, so we fail loudly instead of returning
            ``None`` that a caller might dereference.
    """
    group = list(revisions)
    if not group:
        msg = "cannot pick a latest revision from an empty set"
        raise ValueError(msg)
    return max(group, key=_revision_sort_key)


def latest_revisions_by_document(
    items: Iterable[Any],
    *,
    key_field: str = "drawing_number",
) -> dict[str, Any]:
    """Group revisions by logical document and return the newest of each.

    Documents in the register are grouped by ``key_field`` (drawing number
    by default). A record with no key becomes its own single-revision group
    keyed by ``id:<id>`` so it is never merged with an unrelated record.

    Returns:
        Mapping of group key to the newest revision in that group. Empty
        input yields an empty dict (never raises).
    """
    groups: dict[str, list[Any]] = {}
    for idx, item in enumerate(items):
        raw_key = _get_field(item, key_field)
        if raw_key in (None, ""):
            ident = _get_field(item, "id", idx)
            key = f"id:{ident}"
        else:
            key = str(raw_key)
        groups.setdefault(key, []).append(item)
    return {key: latest_revision(group) for key, group in groups.items()}


# ── Approved-share rate ────────────────────────────────────────────────────


@dataclass(frozen=True)
class ApprovedShare:
    """Approved-share of a register, with the components it is built from.

    ``rate`` is a fraction in ``[0.0, 1.0]``; ``percent`` is the same value
    as a rounded percentage. Both are zero-guarded: an empty register (or
    any register with no documents) reports ``0.0`` rather than dividing by
    zero or returning NaN.
    """

    approved: int
    total: int
    approved_states: tuple[str, ...]

    @property
    def rate(self) -> float:
        """Approved documents divided by total, or 0.0 for an empty register."""
        if self.total <= 0:
            return 0.0
        return self.approved / self.total

    @property
    def percent(self) -> float:
        """The approved share as a percentage rounded to one decimal place."""
        return round(self.rate * 100.0, 1)

    def as_dict(self) -> dict[str, Any]:
        """Expose every component so a reader can re-derive the figure."""
        return {
            "approved": self.approved,
            "total": self.total,
            "not_approved": max(self.total - self.approved, 0),
            "approved_states": list(self.approved_states),
            "rate": self.rate,
            "percent": self.percent,
        }

    def explain(self, lang: str = DEFAULT_LANGUAGE) -> str:
        """One-line plain-language derivation of the approved share."""
        _ = normalize_language(lang)
        if self.total <= 0:
            return "No documents in the register, so the approved share is 0.0% (nothing to approve)."
        return (
            f"{self.approved} of {self.total} documents are approved "
            f"({self.percent}%), where approved means one of: "
            f"{', '.join(self.approved_states)}."
        )


def approved_share(
    items: Iterable[Any],
    *,
    approved_states: Iterable[str] = APPROVED_STATES,
) -> ApprovedShare:
    """Compute the approved share of a register.

    Args:
        items: Document records (mappings or objects) carrying ``cde_state``.
        approved_states: Which CDE states count as approved. Defaults to
            ``{"published"}`` (issued for use).

    Returns:
        An :class:`ApprovedShare` whose ``rate`` is zero-guarded for an
        empty register.
    """
    states = tuple(approved_states)
    approved = 0
    total = 0
    for item in items:
        total += 1
        if _get_field(item, "cde_state") in states:
            approved += 1
    return ApprovedShare(approved=approved, total=total, approved_states=states)


# ── One-line explainers ────────────────────────────────────────────────────


def explain_revision(item: Any, lang: str = DEFAULT_LANGUAGE) -> str:
    """One-line plain-language summary of a single document revision."""
    language = normalize_language(lang)
    name = _get_field(item, "name") or _get_field(item, "drawing_number") or "document"
    revision = _get_field(item, "revision_code") or "no revision recorded"
    standing = "current (latest)" if _get_field(item, "is_current_revision") else "superseded"
    status = localize_status(_get_field(item, "cde_state"), language)
    return f"{name}: revision {revision}, {standing} revision, approval status {status}."


def explain_approval_status(status: str | None, lang: str = DEFAULT_LANGUAGE) -> str:
    """One-line plain-language explanation of an approval status."""
    language = normalize_language(lang)
    key = status if status in _STATUS_LABELS["en"] else STATUS_UNSET
    label = localize_status(key, language)
    meaning = _STATUS_MEANING[key]
    return f"{label}: {meaning}"


def explain_register_coverage(items: Iterable[Any], lang: str = DEFAULT_LANGUAGE) -> str:
    """One-line plain-language summary of how well the register is covered.

    Coverage here means: how many documents the register holds, how many
    are approved, and how many are still awaiting approval. Every number is
    counted from the same records so the sentence is self-consistent, and
    an empty register produces a clear message instead of a divide by zero.
    """
    _ = normalize_language(lang)
    records = list(items)
    share = approved_share(records)
    if share.total <= 0:
        return "The register is empty, so there is nothing to cover yet."
    awaiting = share.total - share.approved
    return (
        f"Register holds {share.total} document(s): {share.approved} approved "
        f"({share.percent}%) and {awaiting} awaiting approval."
    )
