"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠DB-free tests for the schema-driven backup scope derivation.

Builds a synthetic SQLAlchemy schema (no app import, no database) and checks the
fixpoint reproduces the ownership rules: user columns, project_id by name, FK
children, OR'd predicates, friendly keys, users root, and skipping of reference
and unmapped tables.
"""

from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Integer, MetaData, String, Table

from app.modules.backup.graph_scope import (
    PROJECTS_TABLE,
    USERS_TABLE,
    derive_backup_graph,
)

FRIENDLY = {
    USERS_TABLE: "users",
    PROJECTS_TABLE: "projects",
    "oe_boq_boq": "boqs",
    "oe_boq_position": "positions",
    "oe_schedule_schedule": "schedules",
}


def _schema() -> MetaData:
    md = MetaData()
    Table(USERS_TABLE, md, Column("id", String, primary_key=True))
    Table(
        PROJECTS_TABLE,
        md,
        Column("id", String, primary_key=True),
        Column("owner_id", String),
    )
    # child by project_id name (no declared FK, the common convention)
    Table(
        "oe_boq_boq",
        md,
        Column("id", String, primary_key=True),
        Column("project_id", String),
    )
    # grandchild by a real FK to boqs
    Table(
        "oe_boq_position",
        md,
        Column("id", String, primary_key=True),
        Column("boq_id", String, ForeignKey("oe_boq_boq.id")),
    )
    # two ownership paths -> both predicates OR'd
    Table(
        "oe_schedule_schedule",
        md,
        Column("id", String, primary_key=True),
        Column("created_by", String),
        Column("project_id", String),
    )
    # user-owned but no friendly key -> keys off its own table name
    Table(
        "oe_ai_settings",
        md,
        Column("id", String, primary_key=True),
        Column("user_id", String),
    )
    # reference/global table -> excluded
    Table(
        "oe_costs_catalog",
        md,
        Column("id", Integer, primary_key=True),
        Column("name", String),
    )
    # association table with an FK into scope but no mapped class -> skipped
    Table(
        "oe_link_secondary",
        md,
        Column("boq_id", String, ForeignKey("oe_boq_boq.id")),
        Column("tag", String),
    )
    return md


def _derive():
    md = _schema()
    mapped = {t for t in md.tables if t != "oe_link_secondary"}
    return derive_backup_graph(md, mapped, friendly_keys=FRIENDLY)


def test_membership_covers_user_owned_and_excludes_reference() -> None:
    graph = _derive()
    keys = {key for key, _ in graph.table_defs}
    assert {"users", "projects", "boqs", "positions", "schedules", "oe_ai_settings"} <= keys
    # reference table and the unmapped association table are out
    assert "oe_costs_catalog" not in keys
    assert "oe_link_secondary" not in graph.key_for_table.values()
    assert all(name != "oe_link_secondary" for _, name in graph.table_defs)


def test_predicates_follow_ownership_paths() -> None:
    graph = _derive()
    assert graph.scope["users"] == [("self",)]
    assert graph.scope["projects"] == [("eq", "owner_id")]
    assert graph.scope["boqs"] == [("in", "project_id", "projects")]
    assert graph.scope["positions"] == [("in", "boq_id", "boqs")]
    assert graph.scope["oe_ai_settings"] == [("eq", "user_id")]


def test_multiple_ownership_paths_are_ored() -> None:
    graph = _derive()
    # created_by (eq) and project_id (in projects) are both retained
    assert graph.scope["schedules"] == [
        ("eq", "created_by"),
        ("in", "project_id", "projects"),
    ]


def test_users_row_is_first_and_keyed() -> None:
    graph = _derive()
    assert graph.table_defs[0] == ("users", USERS_TABLE)
    assert graph.key_for_table[USERS_TABLE] == "users"


def test_predicate_parents_are_in_key_space() -> None:
    graph = _derive()
    # every "in" predicate must reference a key that exists in the scope map
    valid_keys = set(graph.scope)
    for key, predicates in graph.scope.items():
        for predicate in predicates:
            if predicate[0] == "in":
                assert predicate[2] in valid_keys, (key, predicate)


def test_table_defs_order_parents_before_children() -> None:
    graph = _derive()
    position = {key: i for i, (key, _name) in enumerate(graph.table_defs)}
    # the users root leads so its rows exist before any owner reference resolves
    assert graph.table_defs[0][0] == "users"
    # a restore inserts in this order, so every "in" parent must come first
    for key, predicates in graph.scope.items():
        for predicate in predicates:
            if predicate[0] == "in":
                parent = predicate[2]
                assert position[parent] < position[key], (parent, "must precede", key)
