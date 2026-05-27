"""Unit tests for the OpenCDE BCF-API 3.0 surface.

The actual ``opencde_*`` module implements the BCF-API 3.0 *REST* protocol
(buildingSMART), not the OpenCDE Document Management OAuth flow — so the
tests below pin down the highest-risk surfaces of THAT protocol:

* OData ``$filter`` / ``$orderby`` parsing — both inputs flow from
  unauthenticated query strings, are interpreted by hand-rolled tokenisers,
  and feed straight into SQLA conditions. The parsers MUST reject any
  field that isn't explicitly allowlisted (otherwise relationship attrs,
  internal columns, etc. leak through ``getattr``).
* Labels ``LIKE``-pattern escaping — a label literal lands inside a
  ``%"<value>"%`` LIKE pattern, so embedded ``%`` / ``_`` / ``\\`` /
  ``"`` chars MUST be neutralised.
* If-Match / ETag — a mismatch must raise ``StaleResourceError`` (412)
  and the happy path must accept the current token (and the ``W/`` weak
  prefix per RFC 7232).
* Authorisation shape — ``_topic_authorization`` / ``_project_authorization``
  map our internal roles to OpenCDE action lists; the wire shape is what
  BCF Manager plugins probe for capability discovery.

No DB / network — pure parser + helper coverage.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.modules.bcf.opencde_schemas import (
    BCFCommentResponse,
    BCFProject,
    BCFTopicResponse,
    CommentAuthorization,
    ProjectAuthorization,
    TopicAuthorization,
)
from app.modules.bcf.opencde_service import (
    ODataParseError,
    StaleResourceError,
    _comment_authorization,
    _enforce_if_match,
    _project_authorization,
    _topic_authorization,
    parse_odata_filter,
    parse_orderby,
)

# ── $filter parser ────────────────────────────────────────────────────────


def test_filter_accepts_eq_clause() -> None:
    clauses = parse_odata_filter("topic_status eq 'Open'")
    assert len(clauses) == 1
    c = clauses[0]
    assert c.field == "topic_status"
    assert c.op == "eq"
    assert c.value == "Open"


def test_filter_accepts_in_clause() -> None:
    clauses = parse_odata_filter("priority in ('high','critical')")
    assert len(clauses) == 1
    c = clauses[0]
    assert c.field == "priority"
    assert c.op == "in"
    assert c.value == ["high", "critical"]


def test_filter_accepts_date_lt() -> None:
    clauses = parse_odata_filter("due_date lt 2026-06-01")
    assert clauses[0].op == "lt"
    assert clauses[0].value == date(2026, 6, 1)


def test_filter_accepts_labels_any() -> None:
    clauses = parse_odata_filter("labels/any(l: l eq 'MEP')")
    assert clauses[0].field == "labels"
    assert clauses[0].op == "any_eq"
    assert clauses[0].value == "MEP"


def test_filter_rejects_unknown_field() -> None:
    # ``password_hash`` is not in the scalar allowlist — must 400, never
    # leak through ``getattr`` into a SQLA condition.
    with pytest.raises(ODataParseError):
        parse_odata_filter("password_hash eq 'x'")


def test_filter_rejects_or_operator() -> None:
    with pytest.raises(ODataParseError):
        parse_odata_filter("topic_status eq 'Open' or priority eq 'high'")


def test_filter_rejects_oversized_input() -> None:
    huge = "topic_status eq '" + ("x" * 2000) + "'"
    with pytest.raises(ODataParseError):
        parse_odata_filter(huge)


def test_filter_empty_returns_empty_list() -> None:
    assert parse_odata_filter("") == []
    assert parse_odata_filter("   ") == []


# ── $orderby allowlist ────────────────────────────────────────────────────


def test_orderby_default_when_blank() -> None:
    # Must produce SOME ordering (default created_at desc) so paged lists
    # are deterministic across requests.
    assert parse_orderby(None)
    assert parse_orderby("")


def test_orderby_accepts_allowlisted_field() -> None:
    out = parse_orderby("creation_date desc, title asc")
    assert len(out) == 2


def test_orderby_rejects_relationship_attr() -> None:
    # ``comments`` is a SQLA relationship on BCFTopic — the old impl let
    # this through and exploded deep in the SQL compile step. Allowlist
    # rejects it cleanly with a 400.
    with pytest.raises(ODataParseError):
        parse_orderby("comments asc")


def test_orderby_rejects_unknown_field() -> None:
    with pytest.raises(ODataParseError):
        parse_orderby("does_not_exist asc")


def test_orderby_rejects_bad_direction() -> None:
    with pytest.raises(ODataParseError):
        parse_orderby("title sideways")


# ── If-Match enforcement ──────────────────────────────────────────────────


def test_if_match_none_is_noop() -> None:
    # The spec allows the client to omit If-Match; the helper must NOT
    # raise so the update/delete can proceed.
    _enforce_if_match(None, '"deadbeef"')


def test_if_match_wildcard_accepts_any() -> None:
    _enforce_if_match("*", '"deadbeef"')


def test_if_match_exact_token_matches() -> None:
    _enforce_if_match('"deadbeef"', '"deadbeef"')


def test_if_match_weak_prefix_stripped() -> None:
    _enforce_if_match('W/"deadbeef"', '"deadbeef"')


def test_if_match_mismatch_raises_412() -> None:
    with pytest.raises(StaleResourceError) as exc_info:
        _enforce_if_match('"stale"', '"current"')
    assert exc_info.value.http_status == 412


# ── Authorisation sub-objects ─────────────────────────────────────────────


def test_admin_topic_authorization_has_full_actions() -> None:
    auth = _topic_authorization("admin")
    assert "update" in auth.topic_actions
    assert "createComment" in auth.topic_actions
    assert "createViewpoint" in auth.topic_actions


def test_viewer_topic_authorization_is_empty() -> None:
    auth = _topic_authorization("viewer")
    assert auth.topic_actions == []


def test_estimator_can_comment_but_not_update_topic() -> None:
    auth = _topic_authorization("estimator")
    assert "createComment" in auth.topic_actions
    assert "update" not in auth.topic_actions


def test_unknown_role_falls_back_to_no_actions() -> None:
    # A bearer token with a role we don't know must not implicitly grant
    # privileged actions — fail closed.
    auth = _topic_authorization("__alien_role__")
    assert auth.topic_actions == []


def test_project_authorization_admin_can_update() -> None:
    auth = _project_authorization("admin")
    assert "update" in auth.project_actions
    assert "createTopic" in auth.project_actions


def test_project_authorization_viewer_is_empty() -> None:
    auth = _project_authorization("viewer")
    assert auth.project_actions == []


def test_comment_authorization_editor_can_update() -> None:
    auth = _comment_authorization("editor")
    assert auth.comment_actions == ["update"]


def test_comment_authorization_viewer_cannot_update() -> None:
    auth = _comment_authorization("viewer")
    assert auth.comment_actions == []


# ── Response schema shape (happy path) ────────────────────────────────────


def test_bcf_project_shape() -> None:
    """A minimal BCFProject must serialise the OpenCDE-expected keys."""
    p = BCFProject(
        project_id="abc",
        name="Wohnpark",
        authorization=ProjectAuthorization(project_actions=["createTopic"]),
    )
    data = p.model_dump()
    assert data["project_id"] == "abc"
    assert data["name"] == "Wohnpark"
    assert data["authorization"]["project_actions"] == ["createTopic"]


def test_bcf_topic_response_shape() -> None:
    """BCFTopicResponse must carry the OpenCDE topic envelope (guid,
    server_assigned_id, authorization)."""
    t = BCFTopicResponse(
        guid="11111111-1111-1111-1111-111111111111",
        server_assigned_id="BCF-0001",
        title="Clash: HVAC vs beam",
        authorization=TopicAuthorization(
            topic_actions=["update", "createComment"],
            topic_status=["Open", "In Progress", "Closed"],
        ),
    )
    data = t.model_dump()
    assert data["guid"] == "11111111-1111-1111-1111-111111111111"
    assert data["server_assigned_id"] == "BCF-0001"
    assert data["authorization"]["topic_actions"] == ["update", "createComment"]
    assert "Open" in data["authorization"]["topic_status"]


def test_bcf_comment_response_shape() -> None:
    c = BCFCommentResponse(
        guid="22222222-2222-2222-2222-222222222222",
        comment="LGTM",
        topic_guid="11111111-1111-1111-1111-111111111111",
        authorization=CommentAuthorization(comment_actions=["update"]),
    )
    data = c.model_dump()
    assert data["guid"] == "22222222-2222-2222-2222-222222222222"
    assert data["topic_guid"] == "11111111-1111-1111-1111-111111111111"
    assert data["comment"] == "LGTM"
    assert data["authorization"]["comment_actions"] == ["update"]


# ── Labels LIKE-escape (regression for embedded wildcards / quotes) ──────


def test_labels_filter_escapes_like_wildcards(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wildcards/quotes in a user-supplied label literal MUST be escaped
    before they hit the LIKE pattern (otherwise ``50%`` would match any
    label starting with ``50``)."""
    from app.modules.bcf import opencde_service

    clauses = parse_odata_filter("labels/any(l: l eq '50%_off')")
    out = opencde_service._clauses_to_sqla(clauses)
    # Render the SQLA expression to its compiled SQL and confirm the LIKE
    # right-hand side carries an escape clause AND does NOT contain a raw
    # unescaped wildcard from the user input.
    compiled = out[0].compile(
        compile_kwargs={"literal_binds": True},
    )
    sql = str(compiled).lower()
    assert "escape" in sql
    # The literal ``50%`` from the user must appear escaped, never as a
    # bare ``50%`` token inside the pattern.
    assert "50\\%" in str(compiled) or "50\\\\%" in str(compiled)
