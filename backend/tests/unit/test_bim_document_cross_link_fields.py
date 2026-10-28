"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A cross-link has to be built out of fields the model it writes actually has.

``_generate_pdf_in_background`` passed ``created_by`` to ``Document``, which has
no such column - ``Base`` carries id, created_at and updated_at and nothing
else. SQLAlchemy's declarative constructor answers an unknown keyword with
``TypeError``, so the row was never attempted, let alone written. The block sat
under ``except Exception`` and logged "PDF sheets -> Document linkage failed",
wording that reads like the database refusing a row. It had refused nothing. The
sheets PDF of every converted model has been missing from the documents hub for
as long as the code has existed, and the only trace was a log line that pointed
at the wrong half of the system.

This is checked by walking the router's syntax rather than by exercising the
path, on purpose. ``_generate_pdf_in_background`` returns early unless a
converter binary is installed, so no test that can run on a clean machine ever
reaches the constructor - which is exactly why the defect survived. Reading the
call sites out of the AST also means a cross-link added later is covered the day
it is written, and it covers the ones whose keyword values are variables, which
a grep for a call shape cannot see.

Sibling guard to ``tests/modules/bim_hub/test_cad_upload_cross_link.py``,
which covers the other half of the same lesson on the one cross-link a test can
execute: what a write that fails for real does to the session around it.
"""

from __future__ import annotations

import ast
import pathlib

from sqlalchemy import inspect as sa_inspect

from app.modules.bim_hub import router as bim_router
from app.modules.documents.models import Document

#: Where ``Document`` is imported from. Only imports naming this module bind an
#: alias, so a ``Document`` from somewhere else does not pull its constructions
#: into the check. Names are matched without scope, so a file that bound the
#: same name to two different classes would conflate them - the BIM router does
#: not, and a test that started failing on the wrong class would say which line.
_DOCUMENT_MODULE = "app.modules.documents.models"


def _router_tree() -> ast.Module:
    source = pathlib.Path(bim_router.__file__).read_text(encoding="utf-8")
    return ast.parse(source)


def _document_aliases(tree: ast.Module) -> set[str]:
    """Every local name bound to ``documents.models.Document`` in the router.

    The two cross-links import it under different names - one plain, one as
    ``DocModel`` - and both imports are inside the function that uses them.
    """
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == _DOCUMENT_MODULE:
            aliases |= {alias.asname or alias.name for alias in node.names if alias.name == "Document"}
    return aliases


def _document_constructions(tree: ast.Module, aliases: set[str]) -> list[tuple[int, list[str]]]:
    """``(line number, keyword names)`` for every ``Document(...)`` in the router."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id in aliases):
            continue
        found.append((node.lineno, [kw.arg for kw in node.keywords if kw.arg is not None]))
    return found


def _document_fields() -> set[str]:
    """Attribute names the declarative constructor accepts.

    Mapper attributes, not column names: the metadata column is mapped as
    ``metadata_`` because ``metadata`` is taken by the declarative base, and a
    check against column names would call the correct keyword wrong.
    """
    return set(sa_inspect(Document).mapper.attrs.keys())


def test_the_router_still_builds_documents_and_this_test_still_finds_them() -> None:
    """The denominator, asserted before anything is concluded from it.

    A rename or a refactor that moves these constructions out of the router
    leaves the check below iterating over an empty list and passing for the
    wrong reason.
    """
    tree = _router_tree()
    aliases = _document_aliases(tree)
    assert aliases, f"no import of Document from {_DOCUMENT_MODULE} found in the BIM router"

    constructions = _document_constructions(tree, aliases)
    assert len(constructions) >= 2, (
        f"expected the CAD upload and the sheets-PDF cross-links, found {len(constructions)}: {constructions}"
    )


def test_every_bim_cross_link_names_fields_document_has() -> None:
    """The defect: one keyword that no column is behind, on every call."""
    tree = _router_tree()
    constructions = _document_constructions(tree, _document_aliases(tree))
    fields = _document_fields()

    unknown = {lineno: sorted(set(keywords) - fields) for lineno, keywords in constructions if set(keywords) - fields}
    assert not unknown, (
        f"{pathlib.Path(bim_router.__file__).name} builds a Document out of keywords it does not have: "
        f"{unknown}. SQLAlchemy answers these with TypeError before the row is attempted, and the "
        f"cross-link's own except clause is what turns that into a log line about the database."
    )


def test_created_by_is_still_not_a_document_field() -> None:
    """Pins the premise the test above rests on.

    If ``Document`` ever gains a ``created_by`` column the check above starts
    accepting the keyword that was wrong, and this says so out loud rather than
    letting the guard quietly stop guarding.
    """
    assert "created_by" not in _document_fields(), (
        "Document now has a created_by column - re-read the BIM cross-links before trusting the guard above"
    )
    assert "uploaded_by" in _document_fields()


def _required_document_fields() -> set[str]:
    """Attributes with no value unless the caller supplies one.

    A column that is ``nullable=False`` and carries neither a Python-side
    ``default`` nor a ``server_default`` has to come from the constructor call.
    Everything else on ``Document`` fills itself in, which is why the block that
    passes the fewest keywords still writes a valid row. Keyed by mapper
    attribute rather than column name, so ``metadata`` is reported as the
    ``metadata_`` the caller would actually have to pass.
    """
    mapper = sa_inspect(Document).mapper
    return {
        mapper.get_property_by_column(column).key
        for column in mapper.columns
        if not column.nullable and not column.primary_key and column.default is None and column.server_default is None
    }


def test_every_bim_cross_link_supplies_what_document_cannot_default() -> None:
    """The other half of the keyword question, and the one no run can answer.

    ``test_every_bim_cross_link_names_fields_document_has`` asks whether the
    constructor accepts the keywords. That is not the same as whether
    PostgreSQL accepts the row. The sheets-PDF cross-link has never executed its
    INSERT even once - the ``created_by`` TypeError stopped it before the
    database was involved, and reaching it at all needs a converter binary - so
    a required column it happens not to pass would turn one silent failure into
    another rather than into a document. Asked of the syntax because there is no
    run to ask.
    """
    tree = _router_tree()
    constructions = _document_constructions(tree, _document_aliases(tree))
    required = _required_document_fields()
    assert required, (
        "every Document column now defaults itself, so this test compares against an empty set and "
        "passes no matter what the router builds - re-read the model before trusting it again"
    )

    missing = {
        lineno: sorted(required - set(keywords)) for lineno, keywords in constructions if required - set(keywords)
    }
    assert not missing, (
        f"{pathlib.Path(bim_router.__file__).name} builds a Document without a column that has no default: "
        f"{missing}. The constructor takes it, PostgreSQL does not, and the failure lands in an except clause "
        f"nobody is reading."
    )
