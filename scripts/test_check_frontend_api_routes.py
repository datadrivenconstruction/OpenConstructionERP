#!/usr/bin/env python3
"""Tests for the frontend API route guard.

The guard earns its place only if it goes red on the four ways a call misses
its route, so each verdict has a case that must produce it next to a case that
must not. Several cases are real misses the first sweep found, reduced to one
line: a path without the slash its route declares, a literal segment that a
looser matcher lets fall through to a sibling ``{param}``, an id substitution
that must not stand for a word the backend spells out, and a query-string tail
glued to a word that must not be read as an open prefix.

Run::

    python -m pytest scripts/test_check_frontend_api_routes.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_frontend_api_routes.py"

_spec = importlib.util.spec_from_file_location("check_frontend_api_routes", SCRIPT_PATH)
guard = importlib.util.module_from_spec(_spec)
# dataclasses resolves annotations through sys.modules, so register first.
sys.modules[_spec.name] = guard
_spec.loader.exec_module(guard)

ROUTES = [
    ("/api/v1/rfq-bidding/", frozenset({"GET", "POST"})),
    ("/api/v1/rfq-bidding/{rfq_id}", frozenset({"GET", "PATCH", "DELETE"})),
    ("/api/v1/rfq-bidding/{rfq_id}/issue/", frozenset({"POST"})),
    ("/api/v1/rfq-bidding/bids/", frozenset({"GET", "POST"})),
    ("/api/v1/workflows/{workflow_id}", frozenset({"GET"})),
    ("/api/v1/workflows/requests/", frozenset({"GET"})),
    ("/api/v1/documents/{document_id}/download", frozenset({"GET"})),
    ("/api/v1/documents/photos/{photo_id}/file/", frozenset({"GET"})),
    ("/api/v1/moc/{entry_id}/approve", frozenset({"POST"})),
    ("/api/v1/reports/{report_id}/export.{fmt}", frozenset({"GET"})),
    ("/api/system/status", frozenset({"GET"})),
    ("/api/v1/foo/", frozenset({"GET", "POST"})),
    ("/api/v1/foo/{foo_id}/", frozenset({"GET"})),
    ("/api/v1/bar/", frozenset({"GET", "POST"})),
    ("/api/v1/baz/{baz_id}/", frozenset({"GET"})),
    ("/api/v1/qq/", frozenset({"GET"})),
    ("/api/v1/rfi/archive/", frozenset({"GET"})),
    ("/api/v1/saved-queries/", frozenset({"GET", "POST"})),
    ("/api/v1/saved-queries/{query_id}", frozenset({"GET", "PATCH", "DELETE"})),
    ("/api/v1/share/{token}/file", frozenset({"GET"})),
]
# Every route but the share link reads only the bearer header, as in the app.
BEARER = frozenset(p for p, _ in ROUTES if "/share/" not in p)
TABLE = guard.RouteTable(ROUTES, BEARER)


def verdicts(source: str) -> list[tuple[str, str]]:
    calls, _ = guard.extract_calls(source, "features/x/api.ts")
    for call in calls:
        guard.classify(call, TABLE)
    return [(c.verdict, c.display) for c in calls]


def only(source: str) -> str:
    found = verdicts(source)
    assert len(found) == 1, found
    return found[0][0]


class TestSlash:
    def test_missing_trailing_slash_is_refused(self) -> None:
        assert only("apiPost(`/v1/rfq-bidding/${id}/issue`);") == "SLASH"

    def test_the_declared_slash_passes(self) -> None:
        assert only("apiPost(`/v1/rfq-bidding/${id}/issue/`);") == "OK"

    def test_a_query_tail_glued_to_a_word_still_ends_the_path(self) -> None:
        assert only("apiGet(`/v1/rfq-bidding/bids${qs ? `?${qs}` : ''}`);") == "SLASH"
        assert only("apiGet(`/v1/rfq-bidding/bids/${qs ? `?${qs}` : ''}`);") == "OK"


class TestMissing:
    def test_an_unknown_segment_is_refused(self) -> None:
        assert only("apiGet('/v1/rfq-bidding/nothing/here/');") == "MISSING"

    def test_an_id_does_not_stand_for_a_spelled_out_segment(self) -> None:
        # /documents/${d.id}/file must not match /documents/photos/{photo_id}/file/.
        assert only("apiGet(`/v1/documents/${d.id}/file`);") == "MISSING"
        assert only("apiGet(`/v1/documents/${d.id}/download`);") == "OK"

    def test_an_item_call_does_not_pass_on_the_list_route(self) -> None:
        # /x/${id} was also read as /x/, so the list route answered for the item.
        assert only("apiGet(`/v1/foo/${id}`);") == "SLASH"
        assert only("apiGet(`/v1/foo/${id}/`);") == "OK"
        assert only("apiGet(`/v1/bar/${id}`);") == "MISSING"
        assert only("apiPost(`/v1/bar/${id}`);") == "MISSING"
        assert only("apiGet(`/v1/bar/`);") == "OK"

    def test_an_id_named_after_a_query_is_still_a_segment(self) -> None:
        assert only("apiDelete(`/v1/saved-queries/${encodeURIComponent(queryId)}`);") == "OK"
        assert only("apiGet(`/v1/saved-queries/${subqueryType}`);") == "OK"
        # A bare ${query} still reads as a query string that ends the path.
        assert only("apiGet(`/v1/saved-queries/${query}`);") == "OK"

    def test_a_non_id_substitution_may_be_a_verb(self) -> None:
        assert only("apiPost(`/v1/moc/${id}/${action}`);") == "OK"

    def test_a_parameter_inside_a_segment(self) -> None:
        assert only("apiGet(`/v1/reports/${reportId}/export.${format}`);") == "OK"
        assert only("apiGet(`/v1/reports/${reportId}/export.xlsx`);") == "OK"
        assert only("apiGet(`/v1/reports/${reportId}/report.xlsx`);") == "MISSING"


class TestMethod:
    def test_a_path_served_under_other_methods_is_refused(self) -> None:
        assert only("apiDelete(`/v1/rfq-bidding/${id}/issue/`);") == "METHOD"

    def test_a_word_the_backend_spells_out_does_not_fall_through_to_a_param(self) -> None:
        # GET /workflows/requests would otherwise pass as GET /workflows/{workflow_id}.
        assert only("apiGet('/v1/workflows/requests');") == "SLASH"


class TestAuth:
    def test_a_link_to_a_bearer_only_route_is_refused(self) -> None:
        # The browser opens an href itself and sends no Authorization header.
        assert only("<a href={`/api/v1/documents/${d.id}/download`}>x</a>") == "AUTH"
        assert only("window.open(`/api/v1/documents/${d.id}/download`);") == "AUTH"
        assert only("fetch(`/api/v1/documents/${d.id}/download`);") == "OK"

    def test_a_link_to_a_route_that_takes_its_token_in_the_url_passes(self) -> None:
        assert only("<a href={`/api/v1/share/${token}/file`}>x</a>") == "OK"

    def test_the_bearer_walk_follows_nested_dependencies(self) -> None:
        class Dep:
            def __init__(self, call, deps=(), query=()):
                self.call, self.dependencies = call, list(deps)
                self.query_params = [type("P", (), {"name": q})() for q in query]

        def get_current_user_payload() -> None: ...
        def require_permission() -> None: ...

        secured = type("R", (), {"dependant": Dep(None, [Dep(require_permission, [Dep(get_current_user_payload)])])})
        public = type("R", (), {"dependant": Dep(None, [Dep(require_permission)])})
        linkable = type("R", (), {"dependant": Dep(None, [Dep(get_current_user_payload)], query=["token"])})
        assert guard._reads_only_the_bearer_header(secured) is True
        assert guard._reads_only_the_bearer_header(public) is False
        assert guard._reads_only_the_bearer_header(linkable) is False


class TestPrefix:
    def test_raw_fetch_of_an_unprefixed_path_is_refused(self) -> None:
        assert only("fetch(`/v1/rfq-bidding/${id}`);") == "PREFIX"
        assert only("fetch(`/api/v1/rfq-bidding/${id}`);") == "OK"

    def test_request_helpers_add_the_prefix_themselves(self) -> None:
        assert only("apiGet('/system/status');") == "OK"


class TestReading:
    def test_same_file_constants_and_url_helpers_are_resolved(self) -> None:
        src = (
            "const BASE = '/v1/rfq-bidding';\n"
            "const ITEM = (id: string) => `${BASE}/${encodeURIComponent(id)}`;\n"
            "apiPost(`${ITEM(rfqId)}/issue`);\n"
        )
        assert ("SLASH", "/v1/rfq-bidding/{encodeURIComponent(id)}/issue") in verdicts(src)

    def test_a_stored_base_is_checked_as_a_prefix(self) -> None:
        assert verdicts("const BASE = '/v1/rfq-bidding';") == [("OK", "/v1/rfq-bidding")]
        assert verdicts("const BASE = '/v1/rfq-bidding-typo';") == [("MISSING", "/v1/rfq-bidding-typo")]

    def test_comments_and_string_tests_are_not_requests(self) -> None:
        assert verdicts("// apiGet('/v1/nowhere/')\n/* '/v1/nowhere/' */") == []
        assert verdicts("if (url.includes('/api/v1/nowhere/')) {}") == []

    def test_both_branches_of_a_ternary_are_the_calls_argument(self) -> None:
        assert verdicts("apiGet(flag ? `/v1/qq/` : `/v1/qq`);") == [("OK", "/v1/qq/"), ("SLASH", "/v1/qq")]
        assert ("SLASH", "/v1/rfi/archive") in verdicts("apiGet(isArchive ? `/v1/rfi/archive` : `/v1/qq/`);")

    def test_a_url_stored_in_a_local_is_checked_where_it_is_sent(self) -> None:
        assert only("const url = `/v1/baz/${id}`;\nreturn apiGet(url);") == "SLASH"
        assert only("const url = `/v1/baz/${id}/`;\nreturn apiGet(url);") == "OK"
        # The next declaration of the same name starts a new scope.
        src = "const url = `/v1/baz/${id}/`;\napiGet(url);\nconst url = `/v1/qq/`;\napiDelete(url);"
        assert verdicts(src) == [("OK", "/v1/baz/{id}/"), ("METHOD", "/v1/qq/")]

    def test_a_local_does_not_bind_to_a_parameter_of_a_later_function(self) -> None:
        # Without the top-level boundary the literal would reach this apiDelete
        # and read as METHOD, although the two ``url`` names are unrelated.
        src = "const url = `/v1/baz/${id}/`;\n\nfunction send(url: string) {\n  return apiDelete(url);\n}"
        assert only(src) == "OK"

    def test_a_long_type_argument_keeps_the_method(self) -> None:
        generic = "<{ " + " ".join(f"f{i}: string;" for i in range(20)) + " cb: () => void }>"
        assert only(f"apiDelete{generic}(`/v1/qq/`);") == "METHOD"
        assert only(f"apiGet{generic}(`/v1/qq/`);") == "OK"

    def test_a_concatenated_base_is_a_prefix(self) -> None:
        assert only("apiGet('/v1/baz/' + id + '/');") == "OK"
        assert only("apiGet('/v1/nope/' + id);") == "MISSING"

    def test_an_imported_base_is_counted_not_dropped(self) -> None:
        calls, skipped = guard.extract_calls("apiGet(`${API_ROOT}/v1/x/`);", "f.ts")
        assert calls == []
        assert skipped == 1


def test_the_lifespan_aliases_are_read_from_main() -> None:
    mounts = guard._lifespan_mounts(REPO_ROOT / "backend" / "app" / "main.py")
    prefixes = {prefix for _, _, prefix in mounts}
    assert "/api/v1/variations" in prefixes
    assert "/api/v1/coordination" in prefixes
    assert all(module.startswith("app.") for module, _, _ in mounts)


@pytest.mark.parametrize("key", sorted(guard.ALLOWED))
def test_every_allowed_entry_carries_a_reason(key: str) -> None:
    assert len(guard.ALLOWED[key]) > 40
    assert " @ " in key
