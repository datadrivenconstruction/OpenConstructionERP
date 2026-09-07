# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Red control for the upload advertised-versus-enforced gate.

A gate whose two sides are equal by construction is green forever and proves
nothing. These tests perturb one side at a time and assert the gate in
``test_upload_endpoints_advertise_what_they_enforce`` goes red, which is the
only evidence that the green run above it means anything.

Each perturbation is deliberately one-sided. The published metadata has more
than one surface - the docstring and each parameter description - and the
defect this gate was written for lived in both of them while the constant and
the refusal message were already correct, so a control that moves only the
docstring would not prove the parameter description is being read at all.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.unit.test_upload_endpoints_advertise_what_they_enforce import (
    CONTRACTS,
    UploadContract,
    _find_route,
    assert_contract_holds,
)

BIM_CAD_UPLOAD = next(c for c in CONTRACTS if c.path == "/upload-cad/")
TEMPLATE_UPLOAD = next(c for c in CONTRACTS if c.path == "/document-templates/upload")
PHOTO_ESTIMATE = next(c for c in CONTRACTS if c.path == "/photo-estimate/")


def _file_param(route: Any) -> Any:
    """The ``File(...)`` marker object behind the endpoint's ``file`` argument."""
    import inspect

    return inspect.signature(route.endpoint).parameters["file"].default


def _assert_red(contract: UploadContract, *, mentioning: str) -> None:
    with pytest.raises(AssertionError) as raised:
        assert_contract_holds(contract)
    assert mentioning in str(raised.value), (
        f"the gate failed, but not for the reason the control introduced: {raised.value}"
    )


def test_gate_is_green_before_any_perturbation() -> None:
    """The baseline, so a red below is the perturbation and not a pre-existing break."""
    for contract in CONTRACTS:
        assert_contract_holds(contract)


def test_a_format_added_to_the_parameter_description_alone_goes_red(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact defect: the ``File(...)`` description names a refused format."""
    _module, route = _find_route(BIM_CAD_UPLOAD)
    marker = _file_param(route)
    monkeypatch.setattr(
        marker,
        "description",
        "Raw CAD upload. Accepted extensions: .rvt, .ifc, .dwg, .dgn, .fbx. Mesh files go elsewhere.",
    )

    _assert_red(BIM_CAD_UPLOAD, mentioning="Advertised only: ['fbx']")


def test_a_format_added_to_the_docstring_alone_goes_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """The other published surface, moved on its own."""
    _module, route = _find_route(BIM_CAD_UPLOAD)
    monkeypatch.setattr(route, "description", "Upload a CAD file.\n\nAccepted extensions: .rvt, .ifc, .dwg, .dgn, .obj")

    _assert_red(BIM_CAD_UPLOAD, mentioning="Advertised only: ['obj']")


def test_a_format_added_to_the_enforced_set_alone_goes_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """The enforcing side, moved on its own, with the prose left untouched."""
    module, _route = _find_route(BIM_CAD_UPLOAD)
    monkeypatch.setattr(module, "_ALLOWED_CAD_EXTENSIONS", {*module._ALLOWED_CAD_EXTENSIONS, ".skp"})

    _assert_red(BIM_CAD_UPLOAD, mentioning="Enforced only: ['skp']")


def test_a_description_written_in_bare_words_goes_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """A marker the parser cannot read is a failure, never a silent pass.

    This is the vacuous-pass guard: the old wording named formats as bare
    words, and a parser that returned an empty set for it would compare empty
    against empty and stay green.
    """
    _module, route = _find_route(BIM_CAD_UPLOAD)
    monkeypatch.setattr(_file_param(route), "description", "Accepted extensions: RVT, IFC, DWG, DGN")

    _assert_red(BIM_CAD_UPLOAD, mentioning="introduces no extension")


def test_dropping_the_published_list_entirely_goes_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deleting the promise is not a way to satisfy the gate."""
    _module, route = _find_route(BIM_CAD_UPLOAD)
    monkeypatch.setattr(route, "description", "Upload a CAD file.")
    monkeypatch.setattr(_file_param(route), "description", "Raw CAD upload.")

    _assert_red(BIM_CAD_UPLOAD, mentioning="publishes no 'Accepted extensions:' list")


def test_a_stale_documented_size_cap_goes_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """The documented maximum moves with the constant or the gate fails."""
    module, _route = _find_route(TEMPLATE_UPLOAD)
    monkeypatch.setattr(module, "_CUSTOM_TEMPLATE_MAX_MB", 200)

    _assert_red(TEMPLATE_UPLOAD, mentioning="the handler enforces 200 MB")


def test_a_size_cap_promised_where_none_is_enforced_goes_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """The AI photo endpoint's original defect: a 10 MB promise, no cap in code."""
    _module, route = _find_route(PHOTO_ESTIMATE)
    monkeypatch.setattr(route, "description", "Generate a BOQ estimate from a photo.\n\nMax size: 10 MB.")

    _assert_red(PHOTO_ESTIMATE, mentioning="no size cap is enforced")


def test_an_extension_list_on_a_content_type_endpoint_goes_red(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An endpoint that never looks at the filename must not promise extensions."""
    _module, route = _find_route(PHOTO_ESTIMATE)
    monkeypatch.setattr(route, "description", "Generate a BOQ estimate.\n\nAccepted extensions: .jpg, .png")

    _assert_red(PHOTO_ESTIMATE, mentioning="does not gate uploads on the filename extension")
