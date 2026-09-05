"""IDOR (Insecure Direct Object Reference) anti-regression, v2.6.43+.

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

Route census
------------
``ROUTER_HANDLERS`` is hand maintained, which used to mean a router could
grow a handler without growing a guard and nothing would say so.
``test_object_scoped_routes_are_all_pinned`` closes that: it reads the route
decorators back out of the same ``router.py`` files and requires every route
whose path template names a specific record (``/{ncr_id}``,
``/{transmittal_id}/recipients/{recipient_id}``) to be either in
``ROUTER_HANDLERS`` or in ``_NOT_ROUTER_GATED`` with a written reason.

What it reads is decorator declarations in ``app/modules/<module>/router.py``,
which as of this sweep is where all sixteen audited modules declare all of
their routes: none of them holds a second ``APIRouter`` elsewhere in the
package, and none registers a route through ``add_api_route``. A module that
started doing either would be invisible here.

Two further things it deliberately does not cover, so nobody reads it as wider
than it is:

* Routes that take no path parameter. ``GET /?project_id=...`` and
  ``POST /`` need a project check just as much, but their scope comes from
  the query string or the body and cannot be read off the path, so no
  honest predicate over route shape catches them. Many are pinned anyway;
  they are just not *required* to be.
* Modules outside ``ROUTER_HANDLERS``. The census iterates the audited
  modules, so a brand-new module arrives with no coverage at all. Widening
  it to all of ``app/modules`` would go red immediately and is a separate
  piece of work.

Everything here stays on the AST on purpose: no import of ``create_app``, no
database, no network, which is what lets this file sit in a blocking lane and
finish in seconds.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROUTER_HANDLERS: dict[str, list[str]] = {
    "ncr": [
        "get_ncr",
        "update_ncr",
        "delete_ncr",
        # Route census (test_object_scoped_routes_are_all_pinned)
        "close_ncr",
        "create_variation_from_ncr",
    ],
    "inspections": [
        "get_inspection",
        "update_inspection",
        "delete_inspection",
        # Route census (test_object_scoped_routes_are_all_pinned)
        "complete_inspection",
        "create_defect_from_inspection",
        "create_ncr_from_inspection",
    ],
    "meetings": [
        "get_meeting",
        "update_meeting",
        "delete_meeting",
        # Route census (test_object_scoped_routes_are_all_pinned)
        "add_meeting_action",
        "check_in_attendee",
        "complete_meeting",
        "delete_meeting_action",
        "distribute_meeting_minutes",
        "export_meeting_ics",
        "export_meeting_ics_alias",
        "export_meeting_pdf",
        "export_minutes_pdf",
        "generate_meeting_minutes",
        "get_meeting_minutes",
        "issue_meeting_minutes",
        "list_attendance",
        "list_meeting_actions",
        "materialize_meeting_series",
        "record_external_attendee",
        "series_action_register",
        "update_meeting_action",
        "update_meeting_minutes",
    ],
    "punchlist": [
        "get_item",
        "update_item",
        "delete_item",
        # Route census (test_object_scoped_routes_are_all_pinned)
        "pin_to_sheet",
        "remove_photo",
        "transition_status",
        "upload_photo",
    ],
    "risk": [
        "get_risk",
        "update_risk",
        "delete_risk",
        # Route census (test_object_scoped_routes_are_all_pinned)
        "escalate_project_risks",
        "risk_similar",
        "simulate_risks",
    ],
    "takeoff": [
        "delete_document",
        # Audit B4, takeoff measurement IDOR sweep
        "list_measurements",
        "get_measurement",
        "update_measurement",
        "delete_measurement",
        "link_measurement_to_boq",
        "measurement_summary",
        "export_measurements",
        "create_measurement",
        "bulk_create_measurements",
        # Audit B5, takeoff document IDOR sweep
        "upload_document",
        "get_document",
        "extract_tables",
        "download_document",
        "analyze_document",
        # Audit B6, CAD session IDOR sweep
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
        # Route census (test_object_scoped_routes_are_all_pinned)
        "create_takeoff_from_source",
        "detect_scale",
        "list_proposals",
        "plan_read_accept",
        "plan_read_get_run",
        "plan_read_proposals",
        "recognize_document",
        "review_measurement",
        "similar_symbols",
        "update_document_page_scales",
    ],
    # v2.6.44 sweep
    "rfi": [
        "get_rfi",
        "update_rfi",
        "delete_rfi",
        # Route census (test_object_scoped_routes_are_all_pinned)
        "close_rfi",
        "create_variation_from_rfi",
        "download_rfi_attachment",
        "get_rfi_activity",
        "get_rfi_approval",
        "respond_to_rfi",
        "start_rfi_approval",
        "upload_rfi_attachment",
    ],
    "submittals": [
        "get_submittal",
        "update_submittal",
        "delete_submittal",
        # Route census (test_object_scoped_routes_are_all_pinned)
        "add_submittal_attachment",
        "approve_submittal",
        "get_submittal_approval",
        "list_submittal_attachments",
        "remove_submittal_attachment",
        "review_submittal",
        "start_submittal_approval",
        "submit_submittal",
        "upload_submittal_attachment",
        "validate_submittal",
    ],
    "correspondence": [
        "get_correspondence",
        "update_correspondence",
        "delete_correspondence",
        # Route census (test_object_scoped_routes_are_all_pinned)
        "download_attachment",
        "upload_attachment",
    ],
    "transmittals": [
        "get_transmittal",
        "update_transmittal",
        "delete_transmittal",
        # Route census (test_object_scoped_routes_are_all_pinned)
        "acknowledge_receipt",
        "add_recipient",
        "issue_transmittal",
        "remove_recipient",
        "submit_response",
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
        # Route census (test_object_scoped_routes_are_all_pinned)
        "create_markup_comment",
        "delete_markup_comment",
        "list_markup_comments",
    ],
    "changeorders": [
        "get_change_order",
        "update_change_order",
        "delete_change_order",
        # Route census (test_object_scoped_routes_are_all_pinned)
        "add_item",
        "advance_approval",
        "approve_order",
        "delete_item",
        "execute_order",
        "get_approvals",
        "publish_scenario",
        "reject_order",
        "simulate_impact",
        "start_approval_chain",
        "submit_order",
        "update_item",
    ],
    # v2.6.47 sweep
    "requirements": [
        "get_set",
        "update_set",
        "delete_set",
        # Route census (test_object_scoped_routes_are_all_pinned)
        "add_requirement",
        "attach_position",
        "bulk_add_requirements",
        "bulk_delete_requirements",
        "create_requirement_deliverable",
        # Reaches its project through the set named in the path. Was excused in
        # _NOT_ROUTER_GATED as a live gap until the guard was written.
        "create_set",
        "delete_requirement",
        "delete_requirement_deliverable",
        "detach_position",
        "export_requirements",
        "export_requirements_legacy",
        "get_project_eir_matrix",
        "get_requirement_deliverable_coverage",
        "import_from_text",
        "import_requirements_file",
        "link_requirement_to_bim",
        "link_to_position",
        "list_gates",
        "list_position_links",
        "list_requirement_deliverables",
        "requirement_similar",
        # Addressed by position rather than by set, so it resolves the project
        # through the bill the position sits in.
        "requirements_for_position",
        "run_gate",
        "update_requirement",
        "update_requirement_deliverable",
        "validate_set_against_bim_model",
    ],
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
        # Route census (test_object_scoped_routes_are_all_pinned)
        "create_document_share_link",
        "delete_bim_link",
        "delete_photo",
        "delete_sheet",
        "documents_similar",
        "get_photo",
        "get_sheet",
        "get_sheet_versions",
        "list_document_activity",
        "list_document_share_links",
        "revoke_document_share_link",
        "serve_photo_file",
        "serve_photo_thumbnail",
        "update_photo",
        "update_sheet",
    ],
    "teams": ["update_team", "delete_team"],
    # Round-6 audit, dwg_takeoff IDOR sweep. Every endpoint must funnel
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
        # Route census (test_object_scoped_routes_are_all_pinned)
        "compare_drawing_versions",
        "create_variation_from_drawing_diff",
        "download_drawing",
        "list_drawing_versions",
        "upload_drawing_revision",
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
        # Audit B5, takeoff document access helper (gates by owning project
        # or owner-user for standalone uploads).
        "_verify_takeoff_doc_access",
        # Audit B6, CAD extraction session access helper.
        "_verify_cad_session_access",
        # Round-6 audit, dwg_takeoff IDOR sweep. Each helper resolves the
        # resource's owning project_id and delegates to verify_project_access.
        "_gate_by_drawing",
        "_gate_by_annotation",
        "_gate_by_group",
        # teams.router, resolves the team's owning project and delegates to
        # verify_project_access, normalising its 404 to "Team not found" so a
        # team id cannot be probed for existence across projects.
        "_gate_team_admin",
        # requirements.router, shared export path for both the ``?format=``
        # and the ``export.{ext}`` flavours. It resolves the set's owning
        # project and calls verify_project_access before reading any row.
        "_export_dispatch",
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
        f"{module}.router.{handler} does not call verify_project_access, IDOR guard regression"
    )


@pytest.mark.parametrize(("module", "handler"), [(m, h) for m, hs in ROUTER_HANDLERS.items() for h in hs])
def test_handler_takes_session_dep(module: str, handler: str) -> None:
    """Each handler must accept a session-style param so the IDOR helper
    can do its DB lookup. Catches refactors that drop the param along
    with the verify call.

    Most modules use ``session: SessionDep``; takeoff's CAD-data
    endpoints rename it to ``db_session`` to disambiguate from the
    CAD-extraction "session" concept, those are listed in
    ``_SESSION_ARG_OVERRIDES``.
    """
    tree = _load_module_ast(module)
    fn = _find_handler(tree, handler)
    assert fn is not None
    args = _arg_names(fn)
    expected = _SESSION_ARG_OVERRIDES.get(f"{module}.{handler}", "session")
    assert expected in args, (
        f"{module}.router.{handler} no longer takes a `{expected}` arg, verify_project_access cannot run"
    )


# ── Route census: keeps ROUTER_HANDLERS from going stale ─────────────────────
#
# Everything above is hand maintained, and a hand-maintained list in a lane
# that blocks merges is worth exactly as much as the memory of whoever last
# edited the router. The census reads the real route decorators back out of
# the same router modules and fails when an object-scoped route is in neither
# ROUTER_HANDLERS nor the named exclusions, so a new handler cannot join the
# codebase without joining the guard or being argued about in writing.

_HTTP_METHOD_DECORATORS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})

# Stand-in for a route path this file cannot read statically, e.g.
# ``@router.get(SOME_CONSTANT)``. Every audited router spells its paths as
# literals today, and this exists so that stops being an assumption: a path
# the census cannot parse counts as object-scoped, so the route argues its way
# out through _NOT_ROUTER_GATED rather than disappearing from the count.
_UNREADABLE_PATH = "<path is not a string literal>"


def _decorated_routes(tree: ast.Module) -> dict[str, set[str]]:
    """Map handler name -> the ``METHOD /path`` templates it is registered under.

    One function can carry several route decorators (a few modules register
    the trailing-slash and no-slash spellings on the same handler) so the
    paths are a set rather than a single value.
    """
    routes: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            if not isinstance(func, ast.Attribute) or func.attr not in _HTTP_METHOD_DECORATORS:
                continue
            if decorator.args and isinstance(decorator.args[0], ast.Constant):
                path = str(decorator.args[0].value)
            else:
                path = _UNREADABLE_PATH
            routes.setdefault(node.name, set()).add(f"{func.attr.upper()} {path}")
    return routes


def _is_object_scoped(paths: set[str]) -> bool:
    """True when a route template names one specific record in the URL.

    ``/{ncr_id}``, ``/{meeting_id}/minutes/`` and
    ``/{transmittal_id}/recipients/{recipient_id}`` all address a single row
    the caller has to be allowed to reach, which is the shape IDOR takes. A
    template with no parameter (``GET /``, ``POST /``, ``/export/``) picks its
    scope out of the query string or the body instead, and this file does not
    claim to cover those, see the docstring for what that leaves uncovered.

    A path the census could not read is treated as object-scoped: guessing
    "probably fine" about a route nobody can see is how a gap gets in.
    """
    return any("{" in path or path.endswith(_UNREADABLE_PATH) for path in paths)


# Object-scoped routes deliberately left out of ROUTER_HANDLERS, each with the
# reason it is out. The reasons are written per route on purpose: a computed
# exclusion ("everything under /converters/", "everything the guard scan reads
# as unguarded") would quietly absorb the next route added beside it, which is
# the exact regression this census exists to catch. Removing a route from the
# codebase means removing its line here, test_exclusions_name_a_live_route
# fails on a stale entry rather than letting it shadow a future handler.
_NOT_ROUTER_GATED: dict[str, str] = {
    "meetings.materialize_meeting_series_no_slash": (
        "Underscore mirror of POST /series/{master_id}/materialize/. It awaits "
        "materialize_meeting_series, which is pinned above, so the guard runs once in the delegate."
    ),
    # takeoff's /converters/ subtree administers converter binaries on the
    # host. The ids there name software from a fixed table, not tenant rows,
    # so there is no owning project for verify_project_access to resolve.
    "takeoff.verify_converter": (
        "converter_id names an entry in the host's fixed _CONVERTER_META table, not a tenant row, "
        "so there is no owning project to check. It is gated by RequirePermission('takeoff.read'), "
        "because answering it spawns the converter binary."
    ),
    "takeoff.get_install_progress": (
        "Reports install progress for a host converter binary. Same fixed converter table, no owning project. "
        "Open to an anonymous caller by design, with the fields naming the host's own disk emptied for one, "
        "see test_an_anonymous_caller_is_not_told_where_the_server_keeps_its_files.py."
    ),
    "takeoff.install_converter": (
        "Installs a converter binary on the host, gated by RequirePermission('takeoff.create'). "
        "The id names software, not a tenant row."
    ),
    "takeoff.install_from_manifest": (
        "Installs a named component from the host manifest. component_name is a build artifact name, not an object id."
    ),
    "takeoff.uninstall_converter": (
        "Removes a converter binary from the host. Same fixed converter table, no owning project."
    ),
    "markups.delete_scale": (
        "Scale configs hang off a document and documents carry no project FK yet, so there is no "
        "project to verify. The handler reads created_by inline and answers 403 to anyone else."
    ),
    "documents.get_share_link_info": (
        "Public by design, the share token is itself the capability. Answers before any password "
        "is entered so the share page can show a filename; revoked links 404 like unknown ones."
    ),
    "documents.access_share_link_endpoint": (
        "Public by design, redeems the share token and checks the link password. Demanding "
        "project membership here would defeat the point of an external share link."
    ),
    "documents.serve_share_link_file": ("Public by design, serves the bytes behind a redeemed share token."),
    # teams.router gates one layer down instead. Every handler below hands
    # actor_id= to TeamService, which funnels through get_team_in_project /
    # _assert_team_access and answers 404 for a team in a project the caller
    # cannot reach. This file pins router-level guards, so these sit outside
    # its predicate, outside the predicate, not outside the gate.
    "teams.list_teams": "Service-layer gate: TeamService.list_teams_detailed(actor_id=...).",
    "teams.list_members": "Service-layer gate: TeamService.list_members_detailed(actor_id=...).",
    "teams.add_member": "Service-layer gate: TeamService.add_member(actor_id=...), owner or admin only.",
    "teams.update_member_role": "Service-layer gate: TeamService.update_member_role(actor_id=...).",
    "teams.remove_member": "Service-layer gate: TeamService.remove_member(actor_id=...).",
    "teams.list_team_visibility": "Service-layer gate: TeamService.list_team_visibility(actor_id=...).",
    "teams.grant_visibility": "Service-layer gate: TeamService.grant_visibility(actor_id=...).",
    "teams.revoke_visibility": "Service-layer gate: TeamService.revoke_visibility(actor_id=...).",
    "teams.describe_entity_visibility": "Service-layer gate: TeamService.describe_entity_visibility(actor_id=...).",
    "teams.set_entity_visibility": "Service-layer gate: TeamService.set_entity_visibility(actor_id=...).",
    "teams.list_restricted_entities": "Service-layer gate: TeamService.list_restricted_entities(actor_id=...).",
    "teams.get_access_matrix": "Service-layer gate: TeamService.build_access_matrix(actor_id=...).",
    "teams.validate_project_teams": "Service-layer gate: TeamService.validate_project(actor_id=...).",
}


@pytest.mark.parametrize("module", sorted(ROUTER_HANDLERS))
def test_object_scoped_routes_are_all_pinned(module: str) -> None:
    """Every object-scoped route in an audited module must be accounted for.

    Why: ROUTER_HANDLERS is hand maintained, so without this the guard covers
    whatever somebody remembered to type into it. Reading the decorators back
    out of the router makes a new handler announce itself here on the commit
    that adds it, instead of on the audit that eventually notices it.
    """
    tree = _load_module_ast(module)
    pinned = set(ROUTER_HANDLERS[module])
    unpinned: list[str] = []
    for handler, paths in sorted(_decorated_routes(tree).items()):
        if handler in pinned or f"{module}.{handler}" in _NOT_ROUTER_GATED:
            continue
        if _is_object_scoped(paths):
            unpinned.append(f"    {handler}  ({', '.join(sorted(paths))})")

    assert not unpinned, (
        f"{module}.router has {len(unpinned)} route(s) that address a specific object by id and "
        f"are not covered by the IDOR guard:\n" + "\n".join(unpinned) + "\n\n"
        f"Do one of two things in {Path(__file__).name}:\n"
        f"  1. If the handler resolves the object's owning project and awaits a guard from "
        f"_GUARD_WRAPPERS, add its name to ROUTER_HANDLERS['{module}']. That is the normal case.\n"
        f"  2. If it genuinely must not be project-gated, add '{module}.<handler>' to "
        f"_NOT_ROUTER_GATED with a reason specific to that route.\n"
        f"Do not widen _is_object_scoped to make this pass, that hides the next one too."
    )


def test_exclusions_name_a_live_route() -> None:
    """Every _NOT_ROUTER_GATED entry must still name a real route.

    Why: a stale exclusion is worse than no exclusion. It reads as a reviewed
    decision, and if the handler name is ever reused it pre-approves a route
    nobody looked at.
    """
    stale: list[str] = []
    for key in sorted(_NOT_ROUTER_GATED):
        module, _, handler = key.partition(".")
        assert module in ROUTER_HANDLERS, f"_NOT_ROUTER_GATED entry '{key}' names a module this file does not audit"
        if handler not in _decorated_routes(_load_module_ast(module)):
            stale.append(key)

    assert not stale, (
        f"_NOT_ROUTER_GATED holds {len(stale)} entr(y/ies) that no longer name a route: "
        f"{', '.join(stale)}. Delete the line, the route it excused is gone."
    )
