"""IDOR (Insecure Direct Object Reference) anti-regression — v2.6.43+.

Pins the router-level ``verify_project_access`` calls in the single-resource
GET / PATCH / DELETE handlers across both sweeps:

v2.6.43 sweep:
    - ncr.router.{get,update,delete}_ncr
    - inspections.router.{get,update,delete}_inspection
    - meetings.router.{get,update,delete}_meeting
    - punchlist.router.{get,update,delete}_item
    - risk.router.{get,update,delete}_risk
    - takeoff.router.delete_document

v2.6.44 sweep:
    - rfi.router.{get,update,delete}_rfi
    - submittals.router.{get,update,delete}_submittal
    - correspondence.router.{get,update,delete}_correspondence
    - transmittals.router.{get,update,delete}_transmittal
    - markups.router.{get,update,delete}_markup
    - changeorders.router.{get,update,delete}_change_order

Approach: AST-inspect the handler bodies to verify each one calls
``verify_project_access`` and accepts ``session: SessionDep``. This catches
silent regressions where a refactor drops the IDOR guard without
necessarily breaking any existing test (because the routes still 200 for
the legit owner).

The actual cross-user 404 behaviour is exercised end-to-end by
``backend/tests/integration/test_idor_cross_user.py`` (added in the same
sweep). This file is the cheap static guard.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROUTER_HANDLERS: dict[str, list[str]] = {
    "ncr": ["get_ncr", "update_ncr", "delete_ncr"],
    "inspections": ["get_inspection", "update_inspection", "delete_inspection"],
    "meetings": ["get_meeting", "update_meeting", "delete_meeting"],
    "punchlist": ["get_item", "update_item", "delete_item"],
    "risk": ["get_risk", "update_risk", "delete_risk"],
    "takeoff": [
        "delete_document",
        # Audit B4 — takeoff measurement IDOR sweep
        "list_measurements",
        "get_measurement",
        "update_measurement",
        "delete_measurement",
        "link_measurement_to_boq",
        "measurement_summary",
        "export_measurements",
        "create_measurement",
        "bulk_create_measurements",
        # Audit B5 — takeoff document IDOR sweep
        "upload_document",
        "get_document",
        "extract_tables",
        "download_document",
        "analyze_document",
        # Audit B6 — CAD session IDOR sweep
        "cad_data_elements",
        "cad_data_aggregate",
        "cad_data_save",
        "cad_data_list_sessions",
        "cad_data_delete_session",
        "cad_group",
        "get_group_elements",
        "create_boq_from_cad_qto",
        "export_cad_group",
        "cad_data_describe",
        "cad_data_missingness",
        "cad_data_value_counts",
        "save_session_to_project",
    ],
    # v2.6.44 sweep
    "rfi": ["get_rfi", "update_rfi", "delete_rfi"],
    "submittals": ["get_submittal", "update_submittal", "delete_submittal"],
    "correspondence": [
        "get_correspondence",
        "update_correspondence",
        "delete_correspondence",
    ],
    "transmittals": [
        "get_transmittal",
        "update_transmittal",
        "delete_transmittal",
    ],
    "markups": [
        "get_markup",
        "update_markup",
        "delete_markup",
        # v2.6.48 sweep
        "link_to_boq",
        "get_summary",
        "export_markups",
        "update_stamp_template",
        "delete_stamp_template",
    ],
    "changeorders": [
        "get_change_order",
        "update_change_order",
        "delete_change_order",
    ],
    # v2.6.47 sweep
    "requirements": ["get_set", "update_set", "delete_set"],
    "documents": [
        "get_document",
        "download_document",
        "update_document",
        "delete_document",
        # Finding #25 - revision upload must funnel through the same
        # project-access gate as the other single-document handlers
        # (the folder-level write gate is pinned separately in
        # test_documents_revision_folder_write_gate.py).
        "upload_document_revision",
    ],
    "teams": ["update_team", "delete_team"],
    # Round-6 audit — dwg_takeoff IDOR sweep. Every endpoint must funnel
    # through ``_gate_by_drawing`` / ``_gate_by_annotation`` /
    # ``_gate_by_group`` (or call ``verify_project_access`` directly for
    # the list-by-project_id endpoints).
    "dwg_takeoff": [
        "upload_drawing",
        "list_drawings",
        "get_drawing",
        "delete_drawing",
        "get_entities",
        "get_thumbnail",
        "update_drawing_scale",
        "update_layer_visibility",
        "create_annotation",
        "list_annotations",
        "update_annotation",
        "delete_annotation",
        "link_to_boq",
        "get_pins",
        "create_entity_group",
        "list_entity_groups",
        "delete_entity_group",
    ],
}


def _load_module_ast(module: str) -> ast.Module:
    """Read the module's router.py and parse to AST."""
    here = Path(__file__).resolve()
    repo = here.parents[2]  # tests/unit/<file> -> backend/
    router = repo / "app" / "modules" / module / "router.py"
    return ast.parse(router.read_text(encoding="utf-8"), filename=str(router))


def _find_handler(tree: ast.Module, name: str) -> ast.AsyncFunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    return None


def _arg_names(fn: ast.AsyncFunctionDef) -> list[str]:
    return [a.arg for a in fn.args.args]


# Wrappers that themselves call verify_project_access. Adding a name here
# is a deliberate audit decision: the wrapper must do an equivalent or
# stricter project-scope check before the handler mutates state.
_GUARD_WRAPPERS = frozenset(
    {
        "verify_project_access",
        "_authorize_stamp_mutation",
        # documents.router replaced raw verify_project_access with a strict
        # superset that *also* checks folder ACLs (v2.9.42 refactor).
        "_verify_project_membership_or_404",
        # Audit B5 — takeoff document access helper (gates by owning project
        # or owner-user for standalone uploads).
        "_verify_takeoff_doc_access",
        # Audit B6 — CAD extraction session access helper.
        "_verify_cad_session_access",
        # Round-6 audit — dwg_takeoff IDOR sweep. Each helper resolves the
        # resource's owning project_id and delegates to verify_project_access.
        "_gate_by_drawing",
        "_gate_by_annotation",
        "_gate_by_group",
    }
)


# Handlers that don't use the canonical `session` arg name. Each entry
# maps "module.handler" -> the actual session-parameter name. Most
# routers use `session: SessionDep` but some (notably takeoff's CAD
# subsystem) use `db_session` to disambiguate from CAD-session objects.
_SESSION_ARG_OVERRIDES: dict[str, str] = {
    "takeoff.cad_data_elements": "db_session",
    "takeoff.cad_data_aggregate": "db_session",
    "takeoff.cad_data_save": "db_session",
    "takeoff.cad_data_list_sessions": "db_session",
    "takeoff.cad_data_delete_session": "db_session",
    "takeoff.cad_group": "db_session",
    "takeoff.get_group_elements": "db_session",
    "takeoff.create_boq_from_cad_qto": "db_session",
    "takeoff.export_cad_group": "db_session",
    "takeoff.cad_data_describe": "db_session",
    "takeoff.cad_data_missingness": "db_session",
    "takeoff.cad_data_value_counts": "db_session",
    "takeoff.save_session_to_project": "db_session",
}


def _calls_verify_project_access(fn: ast.AsyncFunctionDef) -> bool:
    """True if any await expression in the body calls a recognised guard."""
    for node in ast.walk(fn):
        if isinstance(node, ast.Await):
            inner = node.value
            if isinstance(inner, ast.Call):
                func = inner.func
                if isinstance(func, ast.Name) and func.id in _GUARD_WRAPPERS:
                    return True
                if isinstance(func, ast.Attribute) and func.attr in _GUARD_WRAPPERS:
                    return True
    return False


@pytest.mark.parametrize(("module", "handler"), [(m, h) for m, hs in ROUTER_HANDLERS.items() for h in hs])
def test_handler_calls_verify_project_access(module: str, handler: str) -> None:
    """Each handler must `await verify_project_access(...)` somewhere in its body.

    Why: dropping this call silently re-opens IDOR (the route would still
    200 for legit owners, so e2e suites that only test the happy path
    wouldn't catch the regression).
    """
    tree = _load_module_ast(module)
    fn = _find_handler(tree, handler)
    assert fn is not None, f"handler {module}.router.{handler} not found"
    assert _calls_verify_project_access(fn), (
        f"{module}.router.{handler} does not call verify_project_access — IDOR guard regression"
    )


@pytest.mark.parametrize(("module", "handler"), [(m, h) for m, hs in ROUTER_HANDLERS.items() for h in hs])
def test_handler_takes_session_dep(module: str, handler: str) -> None:
    """Each handler must accept a session-style param so the IDOR helper
    can do its DB lookup. Catches refactors that drop the param along
    with the verify call.

    Most modules use ``session: SessionDep``; takeoff's CAD-data
    endpoints rename it to ``db_session`` to disambiguate from the
    CAD-extraction "session" concept — those are listed in
    ``_SESSION_ARG_OVERRIDES``.
    """
    tree = _load_module_ast(module)
    fn = _find_handler(tree, handler)
    assert fn is not None
    args = _arg_names(fn)
    expected = _SESSION_ARG_OVERRIDES.get(f"{module}.{handler}", "session")
    assert expected in args, (
        f"{module}.router.{handler} no longer takes a `{expected}` arg — verify_project_access cannot run"
    )
