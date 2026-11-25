"""Checks a resource change must pass before it is written across a region.

A change to one resource rewrites every work item that uses it, so it is
checked first and the findings travel with the preview. Blocking findings
stop the apply; the rest are shown to the person who confirms it.

Codes:

* ``resource.change.nothing_to_change`` (blocking): neither name nor price moves.
* ``resource.change.empty_name`` (blocking): a rename to blank text.
* ``resource.change.key_collision`` (blocking): a codeless resource renamed to
  the name of another resource in the same region. Codeless resources are
  identified by name, so the two would merge silently.
* ``resource.change.unreadable_lines`` (warning): some work items carry the
  resource on a line with no usable quantity; those items are left alone.
* ``resource.change.zero_price`` (warning): the new price is 0, which leaves
  the resource unpriced.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ChangeIssue:
    """One finding of :func:`check_resource_change`."""

    code: str
    blocking: bool
    detail: str = ""


def check_resource_change(
    *,
    old_name: str,
    new_name: str,
    old_price: Decimal,
    new_price: Decimal,
    old_key: str,
    new_key: str,
    existing_keys: set[str],
    unreadable_items: int,
) -> list[ChangeIssue]:
    """Validate a proposed resource change.

    Args:
        old_name: Current resource name on the price sheet.
        new_name: Proposed name (equal to ``old_name`` when unchanged).
        old_price: Current sheet price.
        new_price: Proposed price.
        old_key: Current resource key.
        new_key: Key the resource would carry after the change.
        existing_keys: Other resource keys of the region.
        unreadable_items: Work items whose matching line has no usable quantity.

    Returns:
        The findings, blocking ones first.
    """
    issues: list[ChangeIssue] = []
    if not new_name.strip():
        issues.append(ChangeIssue("resource.change.empty_name", True))
    if new_name == old_name and new_price == old_price:
        issues.append(ChangeIssue("resource.change.nothing_to_change", True))
    if new_key != old_key and new_key in existing_keys:
        issues.append(ChangeIssue("resource.change.key_collision", True, new_key))
    if unreadable_items:
        issues.append(ChangeIssue("resource.change.unreadable_lines", False, str(unreadable_items)))
    if new_price == 0 and old_price != 0:
        issues.append(ChangeIssue("resource.change.zero_price", False))
    issues.sort(key=lambda i: not i.blocking)
    return issues
