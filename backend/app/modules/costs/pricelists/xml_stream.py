# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Streaming XML reading with bounded memory, for price lists of 70 MB and more.

``iterparse`` builds the whole tree as it goes unless finished elements are
dropped. Clearing an element empties it but leaves the empty shell on its
parent, which for a list of 40,000 voci is 40,000 shells; so a finished record
is also removed from its parent. Ancestors stay intact while their children
are read, which is what lets a reader take a chapter's code and title from the
stack instead of keeping its own copy.

Parsing goes through ``defusedxml``: an uploaded file is untrusted, and a DTD
with entity expansion is refused rather than expanded.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import IO
from xml.etree.ElementTree import Element

from defusedxml.ElementTree import iterparse


def local_name(tag: str) -> str:
    """The tag without its ``{namespace}``."""
    return tag.rpartition("}")[2]


def attr(el: Element, name: str, default: str = "") -> str:
    """An attribute read whether or not the schema qualifies it with a namespace."""
    value = el.get(name)
    if value is None:
        for key, val in el.attrib.items():
            if local_name(key) == name:
                return val
        return default
    return value


def child(el: Element, name: str) -> Element | None:
    """The first child with this local name, namespace ignored."""
    for sub in el:
        if local_name(sub.tag) == name:
            return sub
    return None


def children(el: Element, name: str) -> list[Element]:
    """Every child with this local name, namespace ignored."""
    return [sub for sub in el if local_name(sub.tag) == name]


def child_text(el: Element, name: str) -> str:
    sub = child(el, name)
    return (sub.text or "") if sub is not None else ""


def iter_records(
    stream: IO[bytes],
    tags: frozenset[str] | None = None,
    *,
    depth: int | None = None,
) -> Iterator[tuple[Element, list[Element]]]:
    """Yield each finished record element with its ancestors.

    A record is an element whose local name is in ``tags``, or, with ``depth``,
    any element that many levels below the root (``depth=1`` is a child of the
    root), for layouts whose record tag is not known in advance.

    The element is cleared and detached from its parent after the consumer has
    seen it, so the consumer must take what it needs before asking for the next.
    """
    stack: list[Element] = []
    for event, el in iterparse(stream, events=("start", "end"), forbid_dtd=True):
        if event == "start":
            stack.append(el)
            continue
        stack.pop()
        if depth is not None:
            if len(stack) != depth:
                continue
        elif tags is None or local_name(el.tag) not in tags:
            continue
        yield el, stack
        el.clear()
        if stack:
            try:
                stack[-1].remove(el)
            except ValueError:
                pass


__all__ = ["attr", "child", "child_text", "children", "iter_records", "local_name"]
