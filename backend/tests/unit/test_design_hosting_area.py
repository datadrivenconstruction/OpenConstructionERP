# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Design finds its governance host through module 1's read port, by the ``design`` subject, never by a code."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.modules.design_management.hosting import DESIGN_SUBJECT, design_host_in
from app.modules.project_governance import catalogue as cat

_MODULE = Path(__file__).resolve().parents[2] / "app" / "modules" / "design_management"


@pytest.mark.parametrize("cid", cat.CATALOGUE_IDS)
def test_every_shipped_model_hosts_design_on_one_document_of_one_area(cid: str) -> None:
    c = cat.get_catalogue(cid)
    host = design_host_in(c)
    assert host is not None, cid
    assert host.area_code in {a.code for a in c.areas}
    assert [d.code for d in c.document_types if DESIGN_SUBJECT in d.hosts] == [host.doc_type]


def test_a_model_that_tags_no_document_hosts_nothing() -> None:
    c = cat.get_catalogue("neutral")
    bare = c.model_copy(update={"document_types": tuple(d.model_copy(update={"hosts": ()}) for d in c.document_types)})
    assert design_host_in(bare) is None


def test_the_module_keeps_no_resolver_of_its_own() -> None:
    """The port is module 1's; a local copy of the lookup would drift from the validator."""
    tree = ast.parse((_MODULE / "hosting.py").read_text(encoding="utf-8"))
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not names & {"areas", "document_types"}
