# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Upload endpoints must advertise exactly the formats and limits they enforce.

The BIM Hub CAD upload published ``CAD file (RVT, IFC, DWG, DGN, FBX, OBJ,
3DS)`` in its OpenAPI metadata long after the handler had stopped accepting the
last three. An API consumer reading the Swagger UI uploaded an FBX and got a
400 every time. The constant and the refusal message had been corrected in an
earlier pass; the two *published* surfaces, the ``File(...)`` description and
the docstring, were left behind, because nothing compared them to anything.

That is the class this module gates. For every upload endpoint listed in
``CONTRACTS`` it derives both sides from code and asserts they are equal:

* the **advertised** set is parsed out of the endpoint's own published
  metadata, the route description (its docstring) and every parameter
  description, wherever the ``Accepted extensions:`` marker introduces a
  dotted list;
* the **enforced** set is read from the constant the handler actually tests
  the uploaded extension against.

Neither side restates the other, so the assertion is not equal by
construction: adding an extension to the constant without touching the prose
fails, and naming one in the prose that the handler will refuse fails too.
``tests/unit/test_upload_contract_gate_red_control.py`` is the paired control
that perturbs each surface on its own and proves this test goes red.

The same table carries the documented size cap. A description may stay silent
about a limit, but if it names one in megabytes that number has to be the one
the handler enforces - the AI photo endpoint documented a 10 MB maximum next
to a comment reading "No upload size cap - per product policy".
"""

from __future__ import annotations

import importlib
import inspect
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest

# Introduces a comma-separated list of dotted, lower-case extensions. Parsing
# stops at the first token that is not extension-shaped, so a description is
# free to keep explaining itself after the list.
_MARKER = "Accepted extensions:"
_EXT_TOKEN = re.compile(r"\.[a-z0-9]{1,5}")
_SIZE_CLAIM = re.compile(r"(\d+)\s*MB\b")


@dataclass(frozen=True)
class UploadContract:
    """One upload endpoint, its published metadata and the code that gates it."""

    label: str
    module: str
    path: str
    #: Reads the extensions the handler accepts, without the leading dot.
    #: ``None`` when the endpoint does not gate on the extension at all, in
    #: which case it must not publish an ``Accepted extensions:`` list.
    enforced: Callable[[Any], set[str]] | None
    #: Reads the enforced maximum upload size in whole megabytes. ``None``
    #: when no cap is enforced, in which case no description may name one.
    max_mb: Callable[[Any], int] | None = None


def _undotted(extensions: object) -> set[str]:
    return {str(ext).lstrip(".").lower() for ext in extensions}  # type: ignore[union-attr]


CONTRACTS: tuple[UploadContract, ...] = (
    UploadContract(
        label="BIM Hub raw CAD upload",
        module="app.modules.bim_hub.router",
        path="/upload-cad/",
        enforced=lambda mod: _undotted(mod._ALLOWED_CAD_EXTENSIONS),
    ),
    UploadContract(
        label="Takeoff CAD quantity extract",
        module="app.modules.takeoff.router",
        path="/cad-extract/",
        enforced=lambda mod: _undotted(mod._SUPPORTED_CAD_EXTS),
    ),
    UploadContract(
        label="Takeoff CAD column analysis",
        module="app.modules.takeoff.router",
        path="/cad-columns/",
        enforced=lambda mod: _undotted(mod._SUPPORTED_CAD_EXTS),
    ),
    UploadContract(
        label="BOQ smart import",
        module="app.modules.boq.router",
        path="/boqs/{boq_id}/import/smart/",
        enforced=lambda mod: _undotted(mod._SMART_IMPORT_EXTS),
    ),
    UploadContract(
        label="Property development custom template upload",
        module="app.modules.property_dev.router",
        path="/document-templates/upload",
        enforced=lambda mod: _undotted(mod._ALLOWED_CUSTOM_TEMPLATE_EXTENSIONS),
        max_mb=lambda mod: int(mod._CUSTOM_TEMPLATE_MAX_MB),
    ),
    UploadContract(
        label="AI photo estimate",
        module="app.modules.ai.router",
        path="/photo-estimate/",
        # Gated on the request content type, not on the filename, and the
        # handler reads the body with no cap at all: it may promise neither.
        enforced=None,
        max_mb=None,
    ),
)


def _find_route(contract: UploadContract) -> Any:
    """The APIRoute object for *contract*, straight off the module's router.

    The module's own ``router`` is used rather than the assembled application
    so nothing here depends on the module loader having run.
    """
    module = importlib.import_module(contract.module)
    matches = [route for route in module.router.routes if getattr(route, "path", None) == contract.path]
    assert len(matches) == 1, f"{contract.label}: expected exactly one route at {contract.path}, found {len(matches)}"
    return module, matches[0]


def published_texts(route: Any) -> dict[str, str]:
    """Every string this endpoint publishes to OpenAPI, keyed by its surface.

    The docstring and each parameter description reach the Swagger UI, so each
    is a place a promise can be made and each has to be checked. Reading them
    off the route and the signature keeps the parser pointed at what is
    actually served rather than at the source text next to it.
    """
    texts: dict[str, str] = {}
    if route.description:
        texts["docstring"] = route.description
    for name, parameter in inspect.signature(route.endpoint).parameters.items():
        description = getattr(parameter.default, "description", None)
        if isinstance(description, str) and description:
            texts[f"parameter {name!r}"] = description
    return texts


def advertised_extensions(text: str) -> list[set[str]]:
    """One set per ``Accepted extensions:`` list found in *text*.

    Every occurrence is returned separately, not merged: two surfaces that
    disagree with each other must both be reported, and a merged union would
    hide a surface that had gone empty.
    """
    found: list[set[str]] = []
    for marker in re.finditer(re.escape(_MARKER), text):
        extensions: set[str] = set()
        for token in re.split(r"[\s,]+", text[marker.end() :]):
            candidate = token.strip().rstrip(".,;)")
            if not candidate:
                continue
            if not _EXT_TOKEN.fullmatch(candidate):
                break
            extensions.add(candidate[1:])
        found.append(extensions)
    return found


def documented_size_claims(text: str) -> list[int]:
    """Every ``N MB`` figure named in *text*."""
    return [int(match.group(1)) for match in _SIZE_CLAIM.finditer(text)]


def assert_contract_holds(contract: UploadContract) -> None:
    """The whole check for one endpoint, callable from the red control."""
    module, route = _find_route(contract)
    texts = published_texts(route)
    assert texts, f"{contract.label}: publishes no description at all"

    lists = {surface: advertised_extensions(text) for surface, text in texts.items()}
    total = sum(len(sets) for sets in lists.values())

    if contract.enforced is None:
        assert total == 0, (
            f"{contract.label}: does not gate uploads on the filename extension, yet publishes "
            f"an '{_MARKER}' list in {[s for s, sets in lists.items() if sets]}"
        )
    else:
        enforced = contract.enforced(module)
        assert enforced, f"{contract.label}: the enforced extension set is empty"
        assert total, (
            f"{contract.label}: enforces {sorted(enforced)} but publishes no '{_MARKER}' list, "
            f"so the Swagger UI says nothing a consumer can act on. Surfaces read: {sorted(texts)}"
        )
        for surface, sets in lists.items():
            for index, advertised in enumerate(sets):
                where = f"{contract.label}: {surface}" + (f" (list {index + 1})" if len(sets) > 1 else "")
                assert advertised, f"{where}: the '{_MARKER}' marker introduces no extension"
                assert advertised == enforced, (
                    f"{where} advertises {sorted(advertised)} but the handler accepts "
                    f"{sorted(enforced)}. Advertised only: {sorted(advertised - enforced)}. "
                    f"Enforced only: {sorted(enforced - advertised)}."
                )

    enforced_mb = contract.max_mb(module) if contract.max_mb is not None else None
    for surface, text in texts.items():
        for claim in documented_size_claims(text):
            assert enforced_mb is not None, (
                f"{contract.label}: {surface} promises a {claim} MB maximum, but no size cap is "
                f"enforced on this endpoint"
            )
            assert claim == enforced_mb, (
                f"{contract.label}: {surface} promises a {claim} MB maximum, the handler enforces {enforced_mb} MB"
            )


@pytest.mark.parametrize("contract", CONTRACTS, ids=lambda c: c.label)
def test_upload_endpoint_advertises_what_it_enforces(contract: UploadContract) -> None:
    """Advertised formats and limits equal the ones the handler applies."""
    assert_contract_holds(contract)


def test_the_marker_parser_reads_both_written_styles() -> None:
    """The parser is proved on the shapes the descriptions really use.

    Without this the gate could pass by reading nothing: a marker followed by
    prose the parser fails to recognise yields an empty set, and an empty set
    compared against an empty set is green. The endpoint test refuses empty
    lists for that reason; this one pins down what the parser accepts.
    """
    assert advertised_extensions("Accepted extensions: .rvt, .ifc") == [{"rvt", "ifc"}]
    # Ends on a sentence stop, then keeps talking.
    assert advertised_extensions("Accepted extensions: .rvt, .dgn. Mesh files go elsewhere.") == [{"rvt", "dgn"}]
    # Wraps across a docstring line break.
    assert advertised_extensions("Accepted extensions: .xlsx, .xls,\n    .csv\n\n    For structured input") == [
        {"xlsx", "xls", "csv"}
    ]
    # Two surfaces stay two answers.
    assert advertised_extensions("Accepted extensions: .a\nAccepted extensions: .b") == [{"a"}, {"b"}]
    # Bare words are not extensions: a description written the old way, naming
    # formats as ``RVT, IFC``, reads as an empty list and the endpoint test
    # fails on it rather than passing vacuously.
    assert advertised_extensions("Accepted extensions: RVT, IFC") == [set()]
    assert advertised_extensions("no marker here") == []


def test_size_claim_parser_finds_documented_maximums() -> None:
    """A megabyte figure is recognised however the sentence is worded."""
    assert documented_size_claims("Max size: 10 MB.") == [10]
    assert documented_size_claims("Accepts .docx up to 50 MB.") == [50]
    assert documented_size_claims("Maximum size: 50 MB.") == [50]
    assert documented_size_claims("No upload size cap is enforced here") == []
