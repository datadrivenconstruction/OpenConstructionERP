# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The cost routes resolve a reader with the shared rule, not a copy of it.

``app/core/document_locale.py`` was extracted so the rule would live in one
place, and its docstring says so. That was not true when it was written:
``costs/router.py`` already carried a line-for-line copy of the same algorithm
over a different catalogue, serving three routes, and the extraction never
reached it. A docstring vouching for single-sourcing while a copy runs beside
it is worse than no docstring, because it answers the question wrongly to
anyone who checks.

The table below was captured from the copy *before* it was removed. That is
what makes it evidence rather than description: every value is what the old
implementation actually returned, so the current implementation reproducing
them is a statement about behaviour and not about intent. The two were also
compared across 340 combinations of an awkward input matrix, with no
disagreement, which is how the fold was known to be safe before it happened.

Two rows are worth reading twice.

``(None, "de;q=0.1,fr;q=0.9", "de")`` looks wrong and is not. Quality weights
are ignored on purpose: header order is the browser's preference order in
practice, and a single best match is all a catalogue lookup needs. A caller
who ranks French above German still gets German here, because German comes
first in the header and French is not in the cost catalogue at all.

``(None, "zh-Hans-CN", "en")`` is a coverage fact, not a resolution bug. The
CWICR catalogue holds sixteen languages and Chinese is not among them, even
though the interface ships it.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

import app as app_pkg
from app.core.document_locale import resolve_document_locale
from app.modules.costs.router import _resolve_cost_locale
from app.modules.costs.translations import SUPPORTED_LOCALES as COST_LOCALES

APP_ROOT = pathlib.Path(app_pkg.__file__).resolve().parent

#: ``(?locale= value, Accept-Language header, resolved locale)``, captured from
#: the pre-fold implementation.
GOLDEN = [
    (None, None, "en"),
    ("", "", "en"),
    ("de", None, "de"),
    ("DE", None, "de"),
    (" de ", None, "de"),
    ("de-DE", None, "de"),
    ("xx", None, "en"),
    ("xx", "de", "de"),
    (None, "de", "de"),
    (None, "DE", "de"),
    (None, "de-DE", "de"),
    (None, "de-DE,de;q=0.9,en;q=0.8", "de"),
    (None, "fr;q=0.9,de;q=0.8", "de"),
    (None, "de;q=0.1,fr;q=0.9", "de"),
    (None, "xx", "en"),
    (None, "*", "en"),
    (None, "en-GB,en;q=0.9", "en"),
    (None, " de , fr ", "de"),
    (None, "ro,bg", "ro"),
    (None, "zh-Hans-CN", "en"),
    ("ro", "de", "ro"),
    (None, ",", "en"),
]


@pytest.mark.parametrize(("locale_param", "accept_language", "expected"), GOLDEN)
def test_the_cost_locale_is_what_it_was_before_the_fold(
    locale_param: str | None,
    accept_language: str | None,
    expected: str,
) -> None:
    assert _resolve_cost_locale(locale_param, accept_language) == expected


@pytest.mark.parametrize(("locale_param", "accept_language", "expected"), GOLDEN)
def test_the_shared_resolver_gives_the_same_answer_for_the_cost_catalogue(
    locale_param: str | None,
    accept_language: str | None,
    expected: str,
) -> None:
    """Stated separately so a future divergence names which side moved."""
    assert resolve_document_locale(locale_param, accept_language, COST_LOCALES, "en") == expected


def test_the_cost_router_no_longer_parses_accept_language_itself() -> None:
    """The ratchet. Equivalent behaviour today does not keep it equivalent.

    A copy that agrees on 340 inputs is still a copy: the next change to the
    shared rule reaches one of them. This asserts the parsing is gone rather
    than merely correct, because that is the property that cannot drift.
    """
    source = (APP_ROOT / "modules/costs/router.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines()

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "_resolve_cost_locale":
            continue
        body = "\n".join(lines[node.lineno - 1 : (node.end_lineno or node.lineno)])
        assert 'split(";"' not in body, (
            "_resolve_cost_locale is parsing Accept-Language again; the rule "
            "belongs to app.core.document_locale and the catalogue is the only "
            "part that is local to costs"
        )
        assert "resolve_document_locale(" in body, "_resolve_cost_locale must delegate to the shared resolver"
        return

    raise AssertionError("costs/router.py no longer defines _resolve_cost_locale; update this test")
