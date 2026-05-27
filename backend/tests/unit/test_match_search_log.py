# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Unit tests for the v3-P10 :class:`MatchSearchLog` analytics row.

Pure schema-level coverage — column types, FK on-delete behaviour,
index coverage, default-value policy. The end-to-end insert behaviour
is exercised by the broader integration tests against a real DB.

This file deliberately doesn't create tables — it only reflects the
SQLAlchemy class declaration. That way it runs in <100ms and doesn't
need the rest of the model namespace registered.
"""

from __future__ import annotations

from app.modules.match_elements.models import MatchSearchLog


def test_match_search_log_table_name() -> None:
    assert MatchSearchLog.__tablename__ == "oe_match_elements_search_log"


def test_match_search_log_has_required_columns() -> None:
    """Lock the §6.5 schema — every analytics dimension MAPPING_PROCESS
    expects to query against must be a real column, not a JSON dive."""
    cols = {c.key for c in MatchSearchLog.__table__.columns}
    expected = {
        "id",
        "created_at",
        "updated_at",
        "project_id",
        "session_id",
        "group_id",
        "catalog_id",
        "collection_name",
        "core_query",
        "hard_filters",
        "soft_boosts",
        "hits_count",
        "relax_tier_used",
        "top_score",
        "top_confidence_band",
        "bge_rerank_used",
        "llm_rerank_used",
        "took_ms",
        "status",
        "metadata",
        # v2936 — user-feedback + envelope-context columns (MAPPING_PROCESS §10).
        "picked_rank",
        "picked_rate_code",
        "picked_at",
        "source_type",
        "ifc_class",
        "country",
    }
    assert expected.issubset(cols), f"missing columns: {expected - cols}"


def test_match_search_log_indexes_present() -> None:
    """The query-pattern indexes must be declared so the common
    analytics queries (project+time, catalog+time, by tier, by picked
    rank, by source_type, by country+time) don't fall back to a full
    table scan."""
    index_names = {ix.name for ix in MatchSearchLog.__table__.indexes}
    # v2934 — original four
    assert "ix_match_search_log_project_time" in index_names
    assert "ix_match_search_log_catalog_time" in index_names
    assert "ix_match_search_log_session" in index_names
    assert "ix_match_search_log_tier" in index_names
    # v2936 — feedback + envelope-context analytics
    assert "ix_match_search_log_picked_rank" in index_names
    assert "ix_match_search_log_source_type" in index_names
    assert "ix_match_search_log_country_time" in index_names


def test_match_search_log_picked_columns_are_nullable() -> None:
    """``picked_*`` lands as NULL on INSERT (search happened, user
    hasn't confirmed yet) and is backfilled by the /confirm hook.
    Columns must allow NULL or every match request 500s."""
    cols = {c.key: c for c in MatchSearchLog.__table__.columns}
    assert cols["picked_rank"].nullable is True
    assert cols["picked_rate_code"].nullable is True
    assert cols["picked_at"].nullable is True


def test_match_search_log_envelope_context_columns_are_nullable() -> None:
    """source_type / ifc_class / country are populated when the ranker
    has the envelope, NULL for ad-hoc /costs/qdrant-search probes that
    bypass the envelope construction. Must allow NULL."""
    cols = {c.key: c for c in MatchSearchLog.__table__.columns}
    assert cols["source_type"].nullable is True
    assert cols["ifc_class"].nullable is True
    assert cols["country"].nullable is True


def test_match_search_log_session_fk_set_null_on_delete() -> None:
    """When a MatchSession is deleted (e.g., user prunes archived
    sessions) the analytics rows survive — only the session_id column
    nulls out. Same for group_id."""
    fks_by_target: dict[str, object] = {}
    for c in MatchSearchLog.__table__.columns:
        for fk in c.foreign_keys:
            fks_by_target[fk.column.table.name] = fk
    session_fk = fks_by_target["oe_match_elements_session"]
    assert session_fk.ondelete == "SET NULL"
    group_fk = fks_by_target["oe_match_elements_group"]
    assert group_fk.ondelete == "SET NULL"


def test_match_search_log_project_fk_cascades_on_delete() -> None:
    """Project deletion cascades to its analytics rows — they're
    project-scoped data, no value once the project is gone."""
    project_fk = next(
        fk
        for c in MatchSearchLog.__table__.columns
        for fk in c.foreign_keys
        if fk.column.table.name == "oe_projects_project"
    )
    assert project_fk.ondelete == "CASCADE"


def test_match_search_log_default_values_match_server_default() -> None:
    """Migration server_defaults and ORM defaults must agree so a row
    inserted via raw SQL (e.g., from the migration backfill) and one
    inserted via the ORM both end up with the same defaults."""
    table = MatchSearchLog.__table__
    cols = {c.key: c for c in table.columns}
    # JSON defaults
    assert cols["hard_filters"].server_default is not None
    assert cols["soft_boosts"].server_default is not None
    assert cols["metadata"].server_default is not None
    # Counter defaults
    for key in ("hits_count", "relax_tier_used", "bge_rerank_used", "llm_rerank_used"):
        assert cols[key].server_default is not None, f"missing server_default on {key}"


def test_match_search_log_top_confidence_band_is_string() -> None:
    """``top_confidence_band`` stores 'high'/'medium'/'low' values for
    SQL-friendly aggregation. Avoid a dedicated Enum type so an
    accidental new band ('auto') doesn't require a migration."""
    col = MatchSearchLog.__table__.columns["top_confidence_band"]
    type_str = str(col.type).upper()
    assert "VARCHAR" in type_str or "STRING" in type_str


def test_match_search_log_core_query_capped_to_2000_chars() -> None:
    """Defensive cap so a noisy envelope can't blow the row size out
    proportionally with the volume of search calls."""
    col = MatchSearchLog.__table__.columns["core_query"]
    assert col.type.length == 2000


def test_match_search_log_score_is_float_nullable() -> None:
    """``top_score`` is the only float column — must allow NULL for
    the ``hits_count == 0`` case where there's no top candidate."""
    col = MatchSearchLog.__table__.columns["top_score"]
    assert col.nullable is True
    type_str = str(col.type).upper()
    assert "FLOAT" in type_str or "REAL" in type_str or "DOUBLE" in type_str


def test_match_search_log_hits_count_not_nullable() -> None:
    """``hits_count`` is the analytical anchor — never null even on
    a degraded request (zero hits is a meaningful signal)."""
    col = MatchSearchLog.__table__.columns["hits_count"]
    assert col.nullable is False


def test_match_search_log_metadata_column_aliased_to_metadata_attr() -> None:
    """SQLAlchemy reserves ``metadata`` so the ORM attribute is
    ``metadata_`` while the SQL column is ``metadata``. Lock both
    so a mass-rename can't accidentally break the migration."""
    table = MatchSearchLog.__table__
    assert "metadata" in table.columns
    # ORM attribute is ``metadata_`` per the ``"metadata"`` aliasing
    instance = MatchSearchLog.__mapper__.attrs
    assert "metadata_" in {attr.key for attr in instance}


def test_repr_is_diagnostic() -> None:
    """The ``__repr__`` is what shows up in pdb / log lines — must
    include the catalog, hit count, tier, and top score so a glance
    at a misbehaving log row tells the operator what the search was."""
    log = MatchSearchLog(
        catalog_id="DE_BERLIN",
        hits_count=10,
        relax_tier_used=1,
        top_score=0.87,
    )
    out = repr(log)
    assert "DE_BERLIN" in out
    assert "hits=10" in out
    assert "tier=1" in out
    assert "top=0.87" in out
