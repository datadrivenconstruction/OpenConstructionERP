"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit + guard tests for the canonical ``metadata_`` merge helper.

``merge_metadata`` (``app.core.json_merge``) is the single source of truth
for the PATCH-merges-into-metadata contract that ~30 modules rely on. These
tests pin two things:

1. ``test_merge_*`` - the pure behaviour of the helper: shallow merge,
   incoming wins, ``None`` collapses to ``{}``, inputs are never mutated.
2. ``test_no_hand_rolled_metadata_merge_idiom`` - a static guard that scans
   the live ``app/modules`` source and fails if the hand-rolled
   ``{**(<obj>.metadata_ ... or {}), **<patch>}`` merge idiom reappears
   anywhere outside the helper. Re-introducing it (instead of calling
   ``merge_metadata``) is the exact regression class this whole sweep
   removed - it is where the "PATCH silently dropped sibling keys" bugs
   came from.
"""

# Copyright 2024-2026 OpenEstimate Contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core.json_merge import merge_metadata

# ── Pure behaviour ───────────────────────────────────────────────────────


def test_merge_combines_disjoint_keys() -> None:
    assert merge_metadata({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}


def test_merge_incoming_wins_on_collision() -> None:
    # The patch must override the stored value on a shared key.
    assert merge_metadata({"a": 1, "b": 2}, {"b": 99}) == {"a": 1, "b": 99}


def test_merge_keeps_sibling_keys() -> None:
    # The whole point: a one-key patch must not wipe the rest of the column.
    existing = {"tags": ["x"], "notes": "keep me", "source": "import"}
    result = merge_metadata(existing, {"notes": "updated"})
    assert result == {"tags": ["x"], "notes": "updated", "source": "import"}


@pytest.mark.parametrize(
    ("existing", "incoming", "expected"),
    [
        (None, {"a": 1}, {"a": 1}),
        ({"a": 1}, None, {"a": 1}),
        (None, None, {}),
        ({}, {}, {}),
    ],
)
def test_merge_none_collapses_to_empty(existing, incoming, expected) -> None:
    # Neither a None column nor a None patch may ever yield None.
    out = merge_metadata(existing, incoming)
    assert out == expected
    assert isinstance(out, dict)


def test_merge_does_not_mutate_inputs() -> None:
    existing = {"a": 1}
    incoming = {"b": 2}
    merged = merge_metadata(existing, incoming)
    assert existing == {"a": 1}  # untouched
    assert incoming == {"b": 2}  # untouched
    # Result is a distinct object, not an alias of either input.
    assert merged is not existing
    assert merged is not incoming


def test_merge_is_shallow_not_deep() -> None:
    # A colliding nested dict is replaced wholesale, by design (documented).
    existing = {"nested": {"keep": 1}}
    result = merge_metadata(existing, {"nested": {"new": 2}})
    assert result == {"nested": {"new": 2}}


# ── Static regression guard ──────────────────────────────────────────────

# The hand-rolled merge idiom this sweep removed, in both its forms:
#   {**(getattr(obj, "metadata_", None) or {}), **incoming}   # quoted attr name
#   {**(obj.metadata_ or {}), **incoming}                     # dotted attr
# It is the double-splat ``{**( ... metadata_ ... or {}), **`` shape. Pinning
# the leading ``{**(`` and trailing ``or {}), **`` is specific enough to never
# trip on a legitimate fresh-build literal (``obj.metadata_ = {"k": v}`` - no
# ``{**(`` prefix) or a read (``m = obj.metadata_ or {}`` - no ``, **`` suffix).
# ``metadata_`` is matched bare (not ``\.metadata_``) so the ``getattr`` form,
# where the column name is the string ``"metadata_"``, is caught too. ``.*``
# (not ``[^()]``) is required so the nested ``getattr(...)`` parens match.
_HAND_ROLLED_MERGE_RE = re.compile(r"\{\*\*\(.*metadata_.*\bor\b\s*\{\}\)\s*,\s*\*\*")

_MODULES_DIR = Path(__file__).resolve().parents[2] / "app" / "modules"

# Files where the idiom is knowingly still present and owned by another
# workstream at the time this guard landed. Each entry is a module-relative
# POSIX path. Trim this list as those modules adopt ``merge_metadata``; an
# entry that no longer contains the idiom makes the test fail (so the
# allowlist cannot rot silently).
_KNOWN_PENDING = {
    # bim_hub merge sites - BIM workstream owns this module in the
    # v8.6.0 integration branch; refactor tracked as follow-up.
    "bim_hub/service.py",
}


def test_no_hand_rolled_metadata_merge_idiom() -> None:
    """Fail if the hand-rolled metadata merge idiom exists outside the helper.

    Every metadata PATCH-merge must go through ``merge_metadata`` so the
    shallow-merge contract is defined and tested in exactly one place.
    """
    offenders: list[str] = []
    for path in sorted(_MODULES_DIR.rglob("*.py")):
        rel = path.relative_to(_MODULES_DIR).as_posix()
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _HAND_ROLLED_MERGE_RE.search(line):
                if rel in _KNOWN_PENDING:
                    continue
                offenders.append(f"{rel}:{lineno}: {line.strip()}")

    assert not offenders, (
        "Hand-rolled metadata_ merge idiom found - use "
        "app.core.json_merge.merge_metadata instead:\n" + "\n".join(offenders)
    )


def test_known_pending_allowlist_is_not_stale() -> None:
    """Each allowlisted file must still actually contain the idiom.

    Stops the allowlist from silently masking a module that has since been
    cleaned up (or renamed) - once a pending file adopts the helper its
    entry must be removed here.
    """
    stale: list[str] = []
    for rel in sorted(_KNOWN_PENDING):
        path = _MODULES_DIR / rel
        if not path.exists():
            stale.append(f"{rel} (file no longer exists)")
            continue
        text = path.read_text(encoding="utf-8")
        if not any(_HAND_ROLLED_MERGE_RE.search(line) for line in text.splitlines()):
            stale.append(f"{rel} (no longer contains the idiom)")

    assert not stale, "Stale entries in _KNOWN_PENDING - remove them:\n" + "\n".join(stale)
