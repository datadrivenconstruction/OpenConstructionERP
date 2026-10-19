# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The ETA canonical serialization, which is what gets hashed and signed.

Specified at https://sdk.invoicing.eta.gov.eg/document-serialization-approach/
and pinned in the tests to the SDK's own sample: ``one-doc.json`` must
serialize byte for byte to ``one-doc-serialized.json.txt``, and the SHA-256 of
that string is the ``messageDigest`` inside the signature of ``one-doc-I.json``.

The algorithm, for JSON:

* walk the document object recursively, in document order;
* every property name is upper-cased and wrapped in double quotes;
* every simple value is wrapped in double quotes, taken exactly as it is in the
  input: ``947.00`` stays ``947.00`` and must never become ``947`` or ``947.0``;
* an array is written as its name, then its name again before every element;
* the ``signatures`` member is not part of what is signed.

The one trap is the second point. Parsing JSON into floats and printing them
back loses the literal, and a hash over ``947.0`` is a hash over a document
that was never sent. So numbers are parsed into :class:`NumberLiteral`, which
keeps the source text, and are written back from it.

Strings are written as their decoded value. The SDK does not say how an escaped
quote or backslash inside a JSON string is treated, so the advisory rule warns
about text that contains one; the builder never produces it on its own.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

SIGNATURES_KEY = "signatures"


class NumberLiteral(str):
    """A JSON number kept as the exact text it was written with."""

    __slots__ = ()


class EtaSerializationError(ValueError):
    """The text is not one JSON object the serializer can walk."""


def _pairs(pairs: list[tuple[str, Any]]) -> list[tuple[str, Any]]:
    # Kept as a list of pairs rather than a dict: document order is part of the
    # hash, and a duplicate key would silently collapse in a dict.
    return pairs


def parse_preserving(text: str) -> list[tuple[str, Any]]:
    """Parse one JSON document keeping key order, duplicates and number literals.

    Raises:
        EtaSerializationError: the text is not JSON, or is not one object.
    """
    try:
        tree = json.loads(
            text.lstrip("﻿"),
            object_pairs_hook=_pairs,
            parse_float=NumberLiteral,
            parse_int=NumberLiteral,
        )
    except json.JSONDecodeError as exc:
        raise EtaSerializationError(f"The document is not valid JSON: {exc.msg} at line {exc.lineno}") from exc
    if not isinstance(tree, list) or (tree and not isinstance(tree[0], tuple)):
        raise EtaSerializationError("The document must be one JSON object, not an array or a value.")
    return tree


def _simple(value: Any) -> str:
    if value is True:
        return '"true"'
    if value is False:
        return '"false"'
    if value is None:
        # Not used by the SDK samples. Written as JSON writes it, which is the
        # reading of "taken as it is in the input" that changes nothing.
        return '"null"'
    return f'"{value}"'


def _is_object(value: Any) -> bool:
    # A parsed object is a non-empty list of (name, value) tuples; a JSON array
    # parses to a list of anything else. Empty, the two cannot be told apart and
    # serialize the same way.
    return isinstance(value, list) and bool(value) and all(isinstance(item, tuple) and len(item) == 2 for item in value)


def _serialize_object(pairs: list[tuple[str, Any]], out: list[str]) -> None:
    for name, value in pairs:
        upper = f'"{name.upper()}"'
        if isinstance(value, list) and not _is_object(value):
            # A JSON array: the name once for the array, then before each element.
            out.append(upper)
            for element in value:
                out.append(upper)
                _serialize_value(element, out)
        else:
            out.append(upper)
            _serialize_value(value, out)


def _serialize_value(value: Any, out: list[str]) -> None:
    if _is_object(value):
        _serialize_object(value, out)
    elif isinstance(value, list) and not value:
        # An empty object ``{}`` and an empty array ``[]`` both parse to an
        # empty list of pairs; neither contributes anything.
        return
    else:
        out.append(_simple(value))


def serialize_tree(tree: list[tuple[str, Any]], *, include_signatures: bool = False) -> str:
    """The canonical string of an already parsed document."""
    out: list[str] = []
    pairs = tree if include_signatures else [(k, v) for k, v in tree if k != SIGNATURES_KEY]
    _serialize_object(pairs, out)
    return "".join(out)


def canonical_string(document_text: str) -> str:
    """The canonical string ETA hashes for one document, signatures excluded."""
    return serialize_tree(parse_preserving(document_text))


def canonical_bytes(document_text: str) -> bytes:
    """The canonical string as the UTF-8 bytes that are hashed."""
    return canonical_string(document_text).encode("utf-8")


def document_digest(document_text: str) -> bytes:
    """SHA-256 of the canonical bytes: the value inside the signature."""
    return hashlib.sha256(canonical_bytes(document_text)).digest()


__all__ = [
    "SIGNATURES_KEY",
    "EtaSerializationError",
    "NumberLiteral",
    "canonical_bytes",
    "canonical_string",
    "document_digest",
    "parse_preserving",
    "serialize_tree",
]
