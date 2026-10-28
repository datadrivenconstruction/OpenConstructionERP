"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The RLS readiness report names what blocks a strict tenant policy.

Row-level security stays off. Before anybody sets ``OE_RLS_ENFORCE=1`` the
administrator needs to know what that would do to the data as it is, and the
most important answer today is that the tenant is the user: the login issues no
tenant claim, so every user is a tenant of their own and enforcement would hide
a colleague's rows from everybody else.
"""

from __future__ import annotations

from app.core.rls_setup import readiness_blockers


def _table(name: str, *, null: int = 0, user_rows: int = 0) -> dict[str, object]:
    return {
        "table": name,
        "rows": 10,
        "null_tenant_rows": null,
        "tenants": 2,
        "rows_with_user_tenant": user_rows,
        "rls_enabled": False,
        "policy_installed": False,
    }


def test_tenant_values_that_are_user_ids_block_strict_mode() -> None:
    blockers = readiness_blockers(
        [_table("oe_contacts_contact", user_rows=7), _table("oe_qms_item", user_rows=3), _table("oe_eac_rule")],
        dialect="postgresql",
        users=4,
    )

    assert blockers == [
        {"code": "tenant_is_user", "rows": 10, "users": 4, "tables": ["oe_contacts_contact", "oe_qms_item"]}
    ]


def test_rows_without_a_tenant_are_named_per_table() -> None:
    blockers = readiness_blockers([_table("a", null=2), _table("b")], dialect="postgresql", users=1)

    assert blockers == [{"code": "null_tenant_rows", "table": "a", "rows": 2}]


def test_a_clean_database_has_no_blockers() -> None:
    assert readiness_blockers([_table("a"), _table("b")], dialect="postgresql", users=3) == []


def test_sqlite_is_told_that_rls_needs_postgres() -> None:
    assert readiness_blockers([_table("a", null=5)], dialect="sqlite", users=1) == [
        {"code": "not_postgres", "dialect": "sqlite"}
    ]


def test_the_report_route_is_admin_only_and_read_only() -> None:
    from app.dependencies import RequireRole
    from app.modules.admin import router as admin_router
    from app.modules.admin.rls_router import router

    assert admin_router.rls_router is router, "the admin module no longer mounts the report"
    routes = [r for r in router.routes if getattr(r, "path", "") == "/rls/readiness"]
    assert [r.methods for r in routes] == [{"GET"}]
    gates = [d.dependency for d in routes[0].dependencies]
    assert any(isinstance(g, RequireRole) and g.required == "admin" for g in gates)
