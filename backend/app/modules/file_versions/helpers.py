# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Helpers for wiring upload paths into the version-chain service.

Epic C — Document Versioning Unification (deep coordination)
============================================================

The version-chain key is ``(project_id, file_kind, canonical_name)``.
Each kind has its own "name" attribute on its ORM row (``Document.name``,
``ProjectPhoto.filename``, ``Sheet.sheet_number``, ``BIMModel.name`` …)
and a single helper here keeps the upload paths consistent so a
re-upload always lands in the same chain.

Rules
-----
* Whitespace is stripped (matches ``FileVersionService._canonicalize``).
* Case is preserved so ``Plan.pdf`` and ``PLAN.PDF`` form distinct chains
  — the file manager renders both literally and a forced-lowercase rule
  would silently merge them.
* Sheets without a ``sheet_number`` fall back to a deterministic
  composite (``page-NN of source.pdf``) so a multi-page split still
  produces N stable chain keys.
* Photos use ``filename``; BIM models use ``name``; documents use
  ``name``.

The helper accepts either an ORM object (preferred — the upload path
just hands its freshly-created row over) or a raw ``str``. The raw
form is useful in tests and in the CDE cross-link path where only the
filename is known.
"""

from __future__ import annotations

from typing import Any


def _strip(name: str) -> str:
    return (name or "").strip()


def canonical_name_for(file_kind: str, entity: Any) -> str:
    """Return the chain-key ``canonical_name`` for a file-kind row.

    Args:
        file_kind: One of ``document``, ``photo``, ``sheet``, ``bim_model``,
            ``dwg_drawing``, ``takeoff``, ``report``, ``markup``.
        entity: Either the freshly-created ORM row for that kind, OR a
            raw filename string. The raw-string fallback exists so the
            upload paths can pre-compute the chain key before the row
            exists (rare) and so the CDE / transmittal cross-links can
            re-derive it from a filename.

    Returns:
        Canonical name (whitespace-stripped, case-preserving). Never
        empty — falls back to ``"untitled"`` so the chain key always
        has a non-trivial value.

    Raises:
        ValueError: When ``file_kind`` is not a recognised kind. The
            upload paths already pass a constant so this is mostly a
            guard against typos at call sites.
    """
    if isinstance(entity, str):
        return _strip(entity) or "untitled"

    if file_kind == "document":
        # Document.name is the user-visible filename (sanitized at
        # upload time). Re-uploads with the same name roll into the
        # same chain.
        return _strip(getattr(entity, "name", "") or "") or "untitled"

    if file_kind == "photo":
        # ProjectPhoto.filename — the on-disk name, sanitized at upload.
        return _strip(getattr(entity, "filename", "") or "") or "untitled"

    if file_kind == "sheet":
        # Sheet rows belong to a parent document and have either a
        # detected ``sheet_number`` (A-201, S-100, …) or fall back to
        # ``page-NN``. We compose with the document_id so two PDFs in
        # the same project that both have an A-201 don't merge into
        # one chain.
        sheet_number = _strip(getattr(entity, "sheet_number", "") or "")
        page_number = getattr(entity, "page_number", None)
        document_id = _strip(str(getattr(entity, "document_id", "") or ""))
        if sheet_number:
            label = sheet_number
        elif page_number is not None:
            label = f"page-{int(page_number):03d}"
        else:
            label = "page-001"
        if document_id:
            return f"{document_id}:{label}"
        return label

    if file_kind == "bim_model":
        return _strip(getattr(entity, "name", "") or "") or "untitled"

    if file_kind in ("dwg_drawing", "takeoff", "report", "markup"):
        # These kinds reuse Document/Photo storage at the moment, but
        # may grow their own tables. Accept either ``name`` or
        # ``filename`` so the helper survives a future schema split.
        name = getattr(entity, "name", None) or getattr(entity, "filename", None) or ""
        return _strip(name) or "untitled"

    raise ValueError(f"Unknown file_kind for canonical_name_for: {file_kind!r}")


__all__ = ["canonical_name_for"]
