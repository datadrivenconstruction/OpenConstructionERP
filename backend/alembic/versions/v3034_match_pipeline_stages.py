# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Match-elements visible pipeline — stage state + prompt template tables.

Adds two tables that back the seven-stage UI the estimator interacts
with on /match-elements:

* ``oe_match_elements_stage`` — one row per (session, stage) tuple.
  Stages are ``convert``, ``load``, ``schema``, ``filter``, ``group``,
  ``match``, ``rollup``. Tracks pending → running → done | error per
  stage so the UI renders a vertical timeline with status pills,
  output previews, and "Re-run from here" controls.

* ``oe_match_elements_prompt_template`` — user-editable LLM prompt
  templates that drive the three LLM-augmented stages (schema header
  classifier, filter building-or-not classifier, match cost agent).
  System prompts are seeded by this migration from the n8n workflow
  the project ported from; users fork them into private rows when
  they want to tune wording.

Revision ID: v3034_match_pipeline_stages
Revises: v3033_audit_log
Created: 2026-05-15
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3034_match_pipeline_stages"
down_revision: Union[str, Sequence[str], None] = "v3033_audit_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── System prompt seeds ──────────────────────────────────────────────────
# Ported verbatim from the n8n workflow
# n8n_6_Construction_Price_Estimation_with_LLM_for_Revt_and_IFC.json
# (DataDrivenConstruction cad2data repo). The wording is preserved so the
# behaviour matches the upstream pipeline; users can fork + edit.

_SYSTEM_PROMPTS = [
    {
        "key": "schema.header_aggregation",
        "name": "Header aggregation (sum / mean / first)",
        "description": (
            "Classifies each detected column as a quantity to SUM across rows, "
            "a numeric attribute to AVERAGE, or a discrete label whose FIRST "
            "value is representative. Used by the Schema stage to plan rollups."
        ),
        "system_prompt": (
            "You are a construction quantity surveyor. Your task is to classify "
            "data columns from a CAD/BIM export so a downstream estimator can "
            "roll them up into BoQ rows. Reply with a strict JSON array."
        ),
        "user_template": (
            "Columns detected in this CAD/BIM export:\n\n{columns}\n\n"
            "Sample row (first record):\n{sample}\n\n"
            "Classify each column as one of:\n"
            "  - SUM   (quantitative — area, volume, count, length...)\n"
            "  - MEAN  (continuous attribute — temperature, dimension scalar...)\n"
            "  - FIRST (discrete label — material name, family name, level...)\n\n"
            "Return JSON: "
            "[{{\"column\":\"<name>\",\"agg\":\"SUM|MEAN|FIRST\","
            "\"why\":\"<one-sentence rationale>\"}}]"
        ),
    },
    {
        "key": "filter.building_classifier",
        "name": "Building vs non-building filter",
        "description": (
            "Decides per element whether it is a real construction product "
            "(estimable) or a CAD scaffolding artefact (drafting helper, "
            "annotation, grid, void) that must be filtered out before "
            "grouping."
        ),
        "system_prompt": (
            "You are a senior BIM coordinator. Decide whether each element "
            "row represents a real building product that should appear in "
            "the bill of quantities, or an artefact (annotation, grid, void, "
            "reference plane) that must be excluded. Reply with JSON only."
        ),
        "user_template": (
            "Element rows:\n\n{rows}\n\n"
            "For each row, output: "
            "{{\"element_id\":\"<id>\","
            "\"is_building_product\":true|false,"
            "\"trade\":\"architectural|structural|mep|civil|spatial|other\","
            "\"why\":\"<short rationale>\"}}\n\n"
            "Return a JSON array."
        ),
    },
    {
        "key": "group.key_picker",
        "name": "Group-by key picker",
        "description": (
            "Recommends the per-format group_by keys to use. RVT models "
            "should usually group by Type / Type Name (collapses identical "
            "instances); IFC models group by IfcEntity + PredefinedType; "
            "DWG groups by Layer + Block name."
        ),
        "system_prompt": (
            "You are a construction estimation engineer. Recommend the "
            "group-by attribute keys to use when collapsing many BIM "
            "elements into estimable BoQ rows. The fewer rows the BoQ "
            "has while still being correct, the better — but never collapse "
            "two distinct cost products into the same group."
        ),
        "user_template": (
            "Source format: {source_format}\n"
            "Available attribute keys (with sample value counts):\n\n"
            "{attribute_summary}\n\n"
            "Return a JSON object with: "
            "{{\"group_by\":[\"<key1>\",\"<key2>\",...],"
            "\"why\":\"<rationale>\"}}\n\n"
            "Defaults to fall back on if no clear winner:\n"
            "  - RVT: [\"category\", \"type_name\"]\n"
            "  - IFC: [\"ifc_class\", \"predefined_type\"]\n"
            "  - DWG: [\"layer\", \"block_name\"]"
        ),
    },
    {
        "key": "match.cost_agent",
        "name": "AI cost agent",
        "description": (
            "Picks the best cost-database row for a single match group from "
            "a shortlist of vector-search candidates. Used by the Match "
            "stage to break ties and to apply the construction-knowledge "
            "context (material grade, mounting type, exposure class) that "
            "raw vector similarity misses."
        ),
        "system_prompt": (
            "You are an AI cost agent for a construction estimator. You "
            "receive one group of BIM elements and a shortlist of cost-"
            "database candidates retrieved by vector search. Pick the best "
            "match, or say \"NO_MATCH\" when nothing in the shortlist is "
            "a real fit. Never invent a code that is not in the shortlist."
        ),
        "user_template": (
            "Group:\n"
            "  Label: {group_label}\n"
            "  IFC class / category: {ifc_class}\n"
            "  Material: {material}\n"
            "  Sample dimensions: {dimensions}\n"
            "  Element count: {element_count}\n"
            "  Rolled-up quantity: {quantity} {unit}\n\n"
            "Candidates (from CWICR vector search):\n{candidates}\n\n"
            "Return JSON: "
            "{{\"picked_code\":\"<code>|NO_MATCH\","
            "\"confidence\":<0..1>,"
            "\"why\":\"<one-sentence rationale>\"}}"
        ),
    },
]


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── 1. oe_match_elements_stage ───────────────────────────────────
    if not _has_table(inspector, "oe_match_elements_stage"):
        op.create_table(
            "oe_match_elements_stage",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "session_id",
                sa.String(length=36),
                sa.ForeignKey(
                    "oe_match_elements_session.id", ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("stage_name", sa.String(length=32), nullable=False),
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default="pending",
            ),
            sa.Column(
                "inputs", sa.JSON(), nullable=False, server_default="{}",
            ),
            sa.Column(
                "output", sa.JSON(), nullable=False, server_default="{}",
            ),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("took_ms", sa.Integer(), nullable=True),
            sa.Column(
                "prompt_template_id", sa.String(length=36), nullable=True,
            ),
            sa.Column("llm_provider", sa.String(length=64), nullable=True),
            sa.Column(
                "started_at", sa.DateTime(timezone=True), nullable=True,
            ),
            sa.Column(
                "finished_at", sa.DateTime(timezone=True), nullable=True,
            ),
            sa.UniqueConstraint(
                "session_id", "stage_name", name="uq_match_stage_session_name",
            ),
        )
        op.create_index(
            "ix_match_stage_session",
            "oe_match_elements_stage",
            ["session_id"],
        )
        op.create_index(
            "ix_match_stage_status",
            "oe_match_elements_stage",
            ["status"],
        )

    # ── 2. oe_match_elements_prompt_template ─────────────────────────
    if not _has_table(inspector, "oe_match_elements_prompt_template"):
        op.create_table(
            "oe_match_elements_prompt_template",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("key", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "system_prompt",
                sa.Text(),
                nullable=False,
                server_default="",
            ),
            sa.Column("user_template", sa.Text(), nullable=False),
            sa.Column(
                "allowed_providers", sa.String(length=512), nullable=True,
            ),
            sa.Column(
                "version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
            sa.Column(
                "is_system",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("created_by", sa.String(length=36), nullable=True),
            sa.Column(
                "forked_from_id", sa.String(length=36), nullable=True,
            ),
            sa.Column(
                "metadata", sa.JSON(), nullable=False, server_default="{}",
            ),
            sa.UniqueConstraint(
                "key", "name", "created_by",
                name="uq_match_prompt_owner_name",
            ),
        )
        op.create_index(
            "ix_match_prompt_key_version",
            "oe_match_elements_prompt_template",
            ["key", "version"],
        )
        op.create_index(
            "ix_match_prompt_creator",
            "oe_match_elements_prompt_template",
            ["created_by"],
        )

    # ── 3. Seed system prompts ───────────────────────────────────────
    # Idempotent — skip rows that already exist.
    inspector = sa.inspect(bind)
    if not _has_table(inspector, "oe_match_elements_prompt_template"):
        return
    now = datetime.now(UTC)
    for spec in _SYSTEM_PROMPTS:
        existing = bind.execute(
            sa.text(
                "SELECT id FROM oe_match_elements_prompt_template "
                "WHERE key = :k AND name = :n AND created_by IS NULL LIMIT 1"
            ).bindparams(k=spec["key"], n=spec["name"])
        ).fetchone()
        if existing:
            continue
        bind.execute(
            sa.text(
                "INSERT INTO oe_match_elements_prompt_template "
                "(id, created_at, updated_at, key, name, description, "
                "system_prompt, user_template, allowed_providers, "
                "version, is_system, created_by, forked_from_id, metadata) "
                "VALUES (:id, :ts, :ts, :k, :n, :d, :sp, :ut, NULL, "
                "1, 1, NULL, NULL, :meta)"
            ).bindparams(
                id=str(uuid.uuid4()),
                ts=now,
                k=spec["key"],
                n=spec["name"],
                d=spec["description"],
                sp=spec["system_prompt"],
                ut=spec["user_template"],
                meta=json.dumps({"source": "n8n_workflow_v6"}),
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_table(inspector, "oe_match_elements_stage"):
        for idx in ("ix_match_stage_session", "ix_match_stage_status"):
            try:
                op.drop_index(idx, table_name="oe_match_elements_stage")
            except Exception:  # noqa: BLE001 — idempotent drop
                pass
        op.drop_table("oe_match_elements_stage")
    if _has_table(inspector, "oe_match_elements_prompt_template"):
        for idx in (
            "ix_match_prompt_key_version",
            "ix_match_prompt_creator",
        ):
            try:
                op.drop_index(
                    idx, table_name="oe_match_elements_prompt_template",
                )
            except Exception:  # noqa: BLE001 — idempotent drop
                pass
        op.drop_table("oe_match_elements_prompt_template")
