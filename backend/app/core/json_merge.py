# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Canonical shallow-merge helper for the ``metadata_`` JSON column.

Almost every module stores a free-form ``metadata_`` JSON dict on its ORM
rows. The HTTP contract for these resources is a PATCH that *merges* into the
stored metadata - a request that touches one key (``{"tags": [...]}``) must
keep every sibling key already on the row (internal notes, source
provenance, audit breadcrumbs, etc.).

The bug this guards against (and which recurred across ~30 modules - see the
"json_overwrite-on-PATCH" audit) is the naive::

    obj.metadata_ = incoming            # WRONG - drops every other key

or its accidental variants where ``model_dump(exclude_unset=True)`` is fed
straight into ``update_fields`` so the ORM column is *replaced* rather than
merged. The correct behaviour is a shallow merge with the incoming payload
winning on key collisions::

    obj.metadata_ = {**(obj.metadata_ or {}), **incoming}

That idiom was hand-rolled in ~54 places, each an opportunity to get the
``or {}`` guard or the override order subtly wrong. ``merge_metadata`` is the
single source of truth so the merge is written once and tested once.

Note on depth: this is a *shallow* merge by design. A nested dict on a
colliding key is replaced wholesale, not deep-merged. Deep-merging JSON of
arbitrary shape is ambiguous (how do you merge lists? null out a leaf?) and
no caller relies on it; keeping the contract shallow keeps it predictable.

Usage::

    from app.core.json_merge import merge_metadata

    fields["metadata_"] = merge_metadata(getattr(obj, "metadata_", None), incoming)
"""

# Copyright 2024-2026 OpenEstimate Contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from typing import Any

__all__ = ["merge_metadata"]


def merge_metadata(existing: dict[str, Any] | None, incoming: dict[str, Any] | None) -> dict[str, Any]:
    """Shallow-merge an incoming metadata patch onto the stored value.

    Returns a *new* dict ``{**(existing or {}), **(incoming or {})}`` so the
    stored ``metadata_`` keeps every key the patch did not mention while the
    incoming payload wins on any key it does provide. Neither argument is
    mutated.

    Both arguments are treated as optional: a ``None`` existing column (a row
    created before the field was populated) or a ``None`` patch (no metadata
    in this request) collapses to an empty dict, never to ``None``. Callers
    that must distinguish "patch omitted metadata" from "patch cleared
    metadata" should keep that branch at the call site and only delegate the
    dict-on-dict merge here.

    Args:
        existing: The metadata currently on the row (may be ``None``).
        incoming: The metadata patch from the request (may be ``None``).

    Returns:
        A fresh merged dict; the inputs are left untouched.
    """
    return {**(existing or {}), **(incoming or {})}
