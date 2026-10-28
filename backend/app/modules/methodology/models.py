# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Estimating-methodology ORM models.

These tables persist the data-driven country/industry estimating templates that
the pure cascade engine (:mod:`app.modules.methodology.cascade`) computes
against, plus the first-class analytical dimensions and funding sources that a
methodology activates.

Tables:
    oe_methodology - a methodology/template: hierarchy levels, dimension scheme,
        column preset, base/composite mapping, serialized cascade steps, VAT.
    oe_analytic_dimension - an analytical dimension definition (tree or flat),
        e.g. CBS "Главы" (a 2-level tree), section-type / stage / funding (flat).
    oe_analytic_dimension_value - one value within a dimension (self-referencing
        ``parent_id`` for tree dimensions).
    oe_position_dimension_value - links a BOQ position to one value per
        dimension (the M:N tagging of positions by dimension).
    oe_funding_source - funding-source master list.

Conventions (match app.modules.boq.models):
    * ``id`` is a UUID primary key inherited from :class:`app.database.Base`,
      which also supplies ``created_at`` / ``updated_at``.
    * Cross-module identifiers (``project_id``, ``position_id``, contractor /
      contract ids on the BOQ position) are plain ``String(36)`` columns
      resolved at the service layer, NOT hard foreign keys, mirroring
      ``Position.wbs_id`` / ``cost_code_id``. Same-module relationships
      (dimension -> value, position-dimension-value -> dimension / value) DO use
      real foreign keys.
    * Money / rate values (VAT rate, cascade step rates/amounts inside the JSON
      blob) are stored as strings like ``BOQMarkup.percentage`` so SQLite native
      Numeric precision loss and JS ``Number`` digit loss never apply; the
      service layer coerces to ``Decimal`` for arithmetic.
    * Flexible configuration (hierarchy levels, dimension scheme, base mapping,
      composites, cascade steps) is stored as JSON; ``metadata_`` is the
      module-extensible blob present on every table.
    * Every new column is nullable or carries a ``server_default`` so the
      additive Alembic migration is valid on existing rows.
"""

import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class Methodology(Base):
    """A data-driven estimating methodology / country (or industry) template.

    A methodology bundles everything that distinguishes one estimating
    tradition from another: which typed hierarchy levels a BOQ uses, which
    analytical dimensions are active, the column preset, how leaf resource
    types roll into the named bases / composites the cascade consumes, the
    ordered markup cascade itself, VAT handling, and currency / decimals.

    ``scope`` separates platform built-ins (``builtin``), project-local clones
    (``project``, scoped by ``project_id``), and pack-shipped templates
    (``pack``). The international flat method remains the existing BOQMarkup
    path and is represented here only when a project explicitly opts in.
    """

    __tablename__ = "oe_methodology"
    __table_args__ = (
        Index("ix_methodology_scope_country", "scope", "country_code"),
        Index("ix_methodology_project_id", "project_id"),
    )

    # Stable machine identifier (e.g. "uzbekistan", "germany", "railway").
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    # 'builtin' | 'project' | 'pack' - where this methodology originates.
    scope: Mapped[str] = mapped_column(String(20), nullable=False, server_default="builtin")
    # Cross-module project reference (plain string per convention); set only for
    # project-scoped clones, NULL for built-ins and packs.
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, server_default="")
    decimals: Mapped[int] = mapped_column(Integer, nullable=False, server_default="2")

    # Typed hierarchy level definitions, ordered:
    # ``[{"key": "section", "label": "Section", "order": 0}, ...]``.
    hierarchy_levels: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    # Active analytical-dimension scheme, e.g. a list of dimension keys / defs.
    dimension_scheme: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    # Named column preset (GAEB / ONORM / CSI / NRM2 / ...); NULL = default.
    column_preset: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Maps each leaf base token the cascade consumes to the resource types that
    # feed it: ``{"labor": ["labor"], "machinery": ["equipment_machinery"], ...}``.
    base_mapping: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    # Named composites built from base tokens, e.g.
    # ``{"SMR": ["labor", "machinery", "materials"]}``.
    composites: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    # Ordered, serialized ``MarkupStep`` dicts consumed by ``compute_cascade``:
    # ``[{"key", "label", "category", "kind", "rate", "amount", "base": [...]}]``.
    # Rates / amounts are stored as strings (Decimal-safe) like BOQMarkup money.
    cascade_steps: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    # Catalogue fact, not the rate in force. A Decimal-string percent (e.g.
    # "12" = 12 %) recording what the country's standard rate was when this
    # methodology was minted; NULL = VAT handled as a cascade step or not at
    # all. Nothing prices from this column: the cascade's ``tax`` step is what
    # computes, and a project stating its own ``default_vat_rate`` replaces
    # that step. Read ``EffectiveVat`` on the API response for the rate a
    # given project is actually charged, and do not seed a reader from here.
    vat_rate: Mapped[str | None] = mapped_column(String(50), nullable=True)

    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    is_editable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<Methodology {self.slug} ({self.scope})>"


class AnalyticDimension(Base):
    """An analytical dimension a position can be tagged by, with rollup.

    A dimension is either a ``tree`` (values nest via ``parent_id`` - e.g. the
    CBS "Главы" 2-level chapter tree) or ``flat`` (a simple reference list -
    e.g. section-type, stage, funding source). Dimensions belong to a
    methodology (``methodology_slug``) and/or a project (``project_id``); both
    are plain cross-module references resolved at the service layer.
    """

    __tablename__ = "oe_analytic_dimension"
    __table_args__ = (
        Index("ix_analytic_dimension_project_id", "project_id"),
        Index("ix_analytic_dimension_methodology", "methodology_slug"),
    )

    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    methodology_slug: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    # 'tree' | 'flat'.
    kind: Mapped[str] = mapped_column(String(20), nullable=False, server_default="flat")
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships (same-module).
    values: Mapped[list["AnalyticDimensionValue"]] = relationship(
        back_populates="dimension",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="AnalyticDimensionValue.sort_order",
    )

    def __repr__(self) -> str:
        return f"<AnalyticDimension {self.key} ({self.kind})>"


class AnalyticDimensionValue(Base):
    """A single value within an :class:`AnalyticDimension`.

    For ``tree`` dimensions values nest through ``parent_id`` (a same-module
    self-reference); for ``flat`` dimensions ``parent_id`` stays NULL. ``code``
    is the machine value (e.g. a CBS chapter number) and ``label`` the display
    text.
    """

    __tablename__ = "oe_analytic_dimension_value"
    __table_args__ = (
        Index("ix_analytic_dim_value_dimension", "dimension_id"),
        Index("ix_analytic_dim_value_parent", "parent_id"),
    )

    dimension_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_analytic_dimension.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_analytic_dimension_value.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships (same-module).
    dimension: Mapped[AnalyticDimension] = relationship(back_populates="values")
    children: Mapped[list["AnalyticDimensionValue"]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    parent: Mapped["AnalyticDimensionValue | None"] = relationship(
        back_populates="children",
        remote_side="AnalyticDimensionValue.id",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<AnalyticDimensionValue {self.code} - {self.label[:40]}>"


class PositionDimensionValue(Base):
    """Tags a BOQ position with one value of one analytical dimension.

    The M:N join between a position and dimension values. A position carries at
    most one value per dimension (enforced by the unique constraint on
    ``(position_id, dimension_id)``). ``position_id`` is a plain cross-module
    reference to ``oe_boq_position`` per convention; the dimension and value
    references are same-module foreign keys.
    """

    __tablename__ = "oe_position_dimension_value"
    __table_args__ = (
        UniqueConstraint(
            "position_id",
            "dimension_id",
            name="uq_position_dimension_value_position_dimension",
        ),
        Index("ix_position_dimension_value_position", "position_id"),
        Index("ix_position_dimension_value_dimension", "dimension_id"),
        Index("ix_position_dimension_value_value", "value_id"),
    )

    # Cross-module reference to oe_boq_position (plain string per convention).
    position_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    dimension_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_analytic_dimension.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    value_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_analytic_dimension_value.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    def __repr__(self) -> str:
        return f"<PositionDimensionValue pos={self.position_id} dim={self.dimension_id}>"


class FundingSource(Base):
    """A funding-source master entry (e.g. a budget line, grant, or investor).

    Funding sources are project-scoped reference data the BOQ position links to
    via ``Position.funding_source_id``. ``project_id`` is a plain cross-module
    reference resolved at the service layer.
    """

    __tablename__ = "oe_funding_source"
    __table_args__ = (Index("ix_funding_source_project_id", "project_id"),)

    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<FundingSource {self.code} ({self.name})>"
