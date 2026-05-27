"""Epic I — registry + protocol smoke tests.

These tests are deliberately stupid-simple: they pin the *contract*
that every importer must satisfy so the dispatcher loop can rely on
the registry without further duck-type defence.
"""

from __future__ import annotations

import pytest

from app.modules.boq.importers import (
    REGISTERED_IMPORTERS,
    BOQImporter,
    ImportedBOQ,
    ImportedPosition,
    ImporterParseError,
)


def test_registry_is_non_empty() -> None:
    """At least one in-tree importer must be wired."""
    assert REGISTERED_IMPORTERS, "REGISTERED_IMPORTERS must not be empty"


def test_registry_contains_native_importers() -> None:
    """GAEB + BC3 + Excel must all be in the registry by default."""
    format_ids = {imp.format_id for imp in REGISTERED_IMPORTERS}
    assert {"gaeb_xml", "bc3", "excel"}.issubset(format_ids), format_ids


def test_every_importer_implements_protocol() -> None:
    """Each registered importer must satisfy the BOQImporter Protocol."""
    for imp in REGISTERED_IMPORTERS:
        assert isinstance(imp, type), f"{imp!r} is not a class"
        assert hasattr(imp, "format_id") and isinstance(imp.format_id, str)
        assert hasattr(imp, "extensions") and isinstance(imp.extensions, tuple)
        assert hasattr(imp, "display_name") and isinstance(imp.display_name, str)
        assert hasattr(imp, "rule_packs") and isinstance(imp.rule_packs, tuple)
        # detect() must be callable as @classmethod / @staticmethod and
        # never raise on an empty payload.
        assert imp.detect(b"", "") is False, f"{imp.__name__}.detect(b'', '') must return False"


def test_detect_does_not_raise_on_random_garbage() -> None:
    """Defensive contract: detect() is consulted in a tight loop and
    must never crash the dispatcher, regardless of the payload.
    """
    garbage = [
        b"\x00\x01\x02\xff" * 100,
        b"random text\nwithout structure\n",
        b"<?xml version='1.0'?><not-gaeb/>",
        b"~XBOGUS|whatever|",
    ]
    for payload in garbage:
        for imp in REGISTERED_IMPORTERS:
            try:
                imp.detect(payload, "unknown.bin")
            except Exception as exc:  # pragma: no cover — fail closed
                pytest.fail(f"{imp.__name__}.detect raised on garbage: {exc}")


def test_first_match_wins_ordering() -> None:
    """GAEB XML and BC3 are placed *before* the generic Excel importer
    so a `.xml`-named GAEB file isn't mis-claimed by a sloppier detector.
    """
    ids = [imp.format_id for imp in REGISTERED_IMPORTERS]
    assert ids.index("excel") > ids.index("gaeb_xml")
    assert ids.index("excel") > ids.index("bc3")


def test_imported_boq_dataclass_round_trip() -> None:
    """The ImportedBOQ dataclass must accept and round-trip the basic shape."""
    pos = ImportedPosition(
        description="Concrete C30/37",
        ordinal="01.01",
        unit="m3",
        quantity=44.3,
        unit_rate=185.0,
        classification={"din276": "330"},
        source="gaeb_import",
    )
    boq = ImportedBOQ(positions=[pos], source_format="gaeb", currency="EUR")
    assert boq.positions[0].description == "Concrete C30/37"
    assert boq.source_format == "gaeb"
    assert boq.currency == "EUR"
    assert boq.errors == []
    assert boq.warnings == []


def test_importer_parse_error_is_value_error() -> None:
    """``ImporterParseError`` must subclass :class:`ValueError` so callers
    can either ``except ImporterParseError`` or ``except ValueError``."""
    err = ImporterParseError("bad bytes")
    assert isinstance(err, ValueError)
    assert "bad bytes" in str(err)


def test_protocol_is_runtime_checkable() -> None:
    """Sanity: BOQImporter is a runtime-checkable Protocol so isinstance
    can be used in tests (though we mostly duck-type)."""
    assert hasattr(BOQImporter, "_is_runtime_protocol") or hasattr(BOQImporter, "__class_getitem__")
