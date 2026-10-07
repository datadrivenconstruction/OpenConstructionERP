"""Index confirmed ownership filters on assembly, pipeline and webhook lists.

The webhook access query ORs created_by with project_id, so both arms need an
index. v44 covered different tables; v3181 already covers cost catalog owners.
Fresh installs and the boot-time plain-index healer use the model declarations.
This revision covers explicit Alembic upgrades of populated installations.

Concurrent builds avoid blocking writes. Existing equivalent indexes are left
alone, regardless of name. Only indexes created and marked by this migration
are removed on downgrade; pre-existing user/model indexes are never adopted.
If interrupted between concurrent creation and its comment, the unmarked index
is conservatively preserved. Invalid existing indexes fail with a named repair
error rather than silently reporting successful coverage.

Revision ID: v58_owner_list_indexes
Revises: v57_cost_usage_currency
"""

import sqlalchemy as sa
from alembic import op

revision = "v58_owner_list_indexes"
down_revision = "v57_cost_usage_currency"
branch_labels = None
depends_on = None

_MARKER = "created by alembic v58_owner_list_indexes"
_INDEXES = (
    ("oe_assemblies_assembly", "ix_oe_assemblies_assembly_owner_id", "owner_id"),
    ("oe_pipeline", "ix_oe_pipeline_created_by", "created_by"),
    ("oe_webhook_leads_source", "ix_oe_webhook_leads_source_created_by", "created_by"),
    ("oe_webhook_leads_source", "ix_oe_webhook_leads_source_project_id", "project_id"),
)


def _state(bind, name):
    return bind.execute(
        sa.text(
            "SELECT i.indisvalid, obj_description(i.indexrelid, 'pg_class') FROM pg_index i WHERE i.indexrelid = to_regclass(:name)"
        ),
        {"name": name},
    ).first()


def upgrade() -> None:
    bind = op.get_bind()
    for table, name, column in _INDEXES:
        inspector = sa.inspect(bind)
        if not inspector.has_table(table):
            continue
        covered = False
        for index in inspector.get_indexes(table):
            same_name = index["name"] == name
            usable = index["column_names"][:1] == [column] and not index.get("dialect_options", {}).get(
                "postgresql_where"
            )
            if same_name or usable:
                state = _state(bind, index["name"])
                if state is not None and not state[0]:
                    raise RuntimeError(f"Invalid index {index['name']}; repair it before retrying {revision}")
                if same_name and not usable:
                    raise RuntimeError(f"Index name {name} is already used for a different definition")
                covered = True
        if covered:
            continue
        with op.get_context().autocommit_block():
            op.create_index(name, table, [column], postgresql_concurrently=True)
            quoted = bind.dialect.identifier_preparer.quote(name)
            op.execute(sa.text(f"COMMENT ON INDEX {quoted} IS '{_MARKER}'"))


def downgrade() -> None:
    bind = op.get_bind()
    for table, name, column in reversed(_INDEXES):
        inspector = sa.inspect(bind)
        if not inspector.has_table(table):
            continue
        index = next((entry for entry in inspector.get_indexes(table) if entry["name"] == name), None)
        if index is None or index["column_names"] != [column]:
            continue
        state = _state(bind, name)
        if state is not None and state[1] == _MARKER:
            with op.get_context().autocommit_block():
                op.drop_index(name, table_name=table, postgresql_concurrently=True)
