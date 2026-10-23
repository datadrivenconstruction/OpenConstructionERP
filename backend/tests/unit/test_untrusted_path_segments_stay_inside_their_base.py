"""Untrusted names that reach the filesystem never escape their base directory."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.storage import resolve_within


@pytest.mark.parametrize(
    "parts",
    [
        ("..", "etc", "passwd"),
        ("a", "..", "..", "x"),
        ("/etc/passwd",),
        ("\\windows\\system32",),
        ("C:evil",),
        ("ok", ""),
        ("nul\x00byte",),
    ],
)
def test_resolve_within_rejects_escapes(tmp_path: Path, parts: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        resolve_within(tmp_path, *parts)


def test_resolve_within_accepts_a_plain_descendant(tmp_path: Path) -> None:
    assert resolve_within(tmp_path, "a", "b.txt") == (tmp_path / "a" / "b.txt").resolve()


@pytest.mark.parametrize(
    "arc",
    [
        "attachments/bim/C:/x.ifc",
        "attachments/bim/../../x.ifc",
        "attachments/dwg/d1/C:evil.dwg",
        "attachments/documents/..\\..\\x/y.pdf",
    ],
)
def test_bundle_attachment_targets_cannot_escape(arc: str) -> None:
    from app.modules.projects.bundle_import import _target_path_for_attachment

    assert _target_path_for_attachment(arc, "11111111-1111-1111-1111-111111111111", {}) is None


def test_bundle_attachment_target_lands_under_its_base() -> None:
    from app.modules.documents.service import UPLOAD_BASE
    from app.modules.projects.bundle_import import _target_path_for_attachment

    target = _target_path_for_attachment("attachments/documents/d1/plan.pdf", "p1", {})
    assert target is not None
    Path(target).relative_to(UPLOAD_BASE.resolve())


@pytest.mark.parametrize("locale", ["../../../etc/passwd", "/etc/passwd", "..\\x", "zz"])
def test_cost_translations_ignore_unknown_locales(locale: str) -> None:
    from app.modules.costs.translations import load_translations

    assert load_translations(locale) == {}


def test_property_dev_loaders_fall_back_on_traversal_codes() -> None:
    from app.modules.property_dev import document_templates as dt

    assert dt._load_locale("../../../../etc/passwd") == dt._load_locale("en")
    assert dt._load_clauses("../../x", "../en") == dt._load_clauses("NONE", "en")


@pytest.mark.parametrize("doc_type", ["../../etc/cron", "/abs/path", "..\\..\\x"])
def test_text_template_basename_sanitises_the_doc_type_fallback(doc_type: str) -> None:
    from app.modules.property_dev.router import _resolve_safe_text_filename

    name = _resolve_safe_text_filename("///", doc_type, "text/plain")
    assert "/" not in name
    assert "\\" not in name
    assert ".." not in name.rsplit(".", 1)[0]
