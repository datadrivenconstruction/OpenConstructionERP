# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data path declarations a module manifest carries.

A declaration answers, for one module, "where does my data come from, what
drives my numbers, where does it go". It is small and typed on purpose: the
manifest is read by people, and the gate in ``tests/unit/test_data_paths_declared.py``
resolves every field named here against the ORM, so a declaration cannot name
a column that does not exist.

``ModuleManifest.data_paths`` follows the ``inference`` convention: ``None``
means nobody has looked yet, ``DataPaths(reason=...)`` with no paths means
somebody looked and the module is isolated.

Field references are ``Model.field`` or ``Model.json_column.key``. A model is
looked up in the declaring module and in the module the path points at; a
prefix ``oe_<module>.`` names another module explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Importance(StrEnum):
    """How much downstream work stops when this path carries nothing."""

    CRITICAL = "critical"
    """Downstream cannot produce its main result without it (no contract value, no invoice)."""

    HIGH = "high"
    """Downstream still works but its numbers are wrong or incomplete."""

    SUPPORTING = "supporting"
    """Context, traceability or convenience."""


@dataclass(frozen=True)
class Count:
    """Number of rows on the path's entity inside the project."""


@dataclass(frozen=True)
class Sum:
    """Sum of one numeric (or decimal-string) field."""

    field: str


@dataclass(frozen=True)
class Latest:
    """Most recent value of a timestamp field."""

    field: str = "updated_at"


Measure = Count | Sum | Latest

WHERE_OPS = frozenset({"eq", "ne", "in", "not_in", "not_null", "is_null"})


@dataclass(frozen=True)
class Where:
    """One filter on the path's entity, e.g. ``Where("status", "eq", "awarded")``."""

    field: str
    op: str = "eq"
    value: str | bool | tuple[str, ...] | None = None


@dataclass(frozen=True)
class Entity:
    """A record type this module owns, shown in the centre card."""

    model: str
    label: str = ""
    route: str = ""
    measure: Measure = field(default_factory=Count)
    where: tuple[Where, ...] = ()
    scope: str = "project"


@dataclass(frozen=True)
class DataPath:
    """One link between this module and another.

    Args:
        module: The other module (``oe_tendering``).
        entity: The record type measured on this path, owned by ``module`` for
            inputs and outputs alike, or by the declaring module when the link
            is stored on our side.
        via: Where the link is stored: ``Model.fk_column``, ``Model.json_column``
            (an id array) or ``Model.json_column.key``.
        label: i18n key of the path label, ``data_paths.entity.*`` or ``data_paths.<module>.*``.
        measure: ``Count()``, ``Sum(field)`` or ``Latest(field)``.
        route: Front-end register the card opens; ``{project}`` is substituted.
        importance: :class:`Importance`; anything above supporting needs ``breaks``.
        breaks: i18n key of what stops downstream when this path is empty.
        missing: i18n key of the plain sentence the health panel shows when a
            critical path is empty (``No contract yet for the awarded tender``).
        where: Extra filters on ``entity``.
        scope: ``project`` (default) or ``global`` for shared reference data
            (cost catalogues, statutory regimes) that has no project.
    """

    module: str
    entity: str
    via: str
    label: str = ""
    measure: Measure = field(default_factory=Count)
    route: str = ""
    importance: Importance | str = Importance.SUPPORTING
    breaks: str = ""
    missing: str = ""
    where: tuple[Where, ...] = ()
    scope: str = "project"

    def __post_init__(self) -> None:
        if not isinstance(self.importance, Importance):
            object.__setattr__(self, "importance", Importance(self.importance))


@dataclass(frozen=True)
class Param:
    """A field of this module that drives numbers elsewhere.

    ``drives`` are field references or ``module:concept`` for derived outputs
    that are not a stored column (``oe_costmodel:cash_flow``).
    """

    field: str
    drives: tuple[str, ...] = ()
    label: str = ""


@dataclass(frozen=True)
class Stale:
    """Source changed after the consumer copied it.

    Stale when the newest ``copy`` stamp in the project is older than a
    ``source`` row's timestamp; the count is the number of such source rows.
    """

    source: str
    copy: str
    label: str = ""


EXTERNAL_KINDS = frozenset({"party", "file", "device"})
CHIP_TONES = frozenset({"info", "warning", "error", "success"})


@dataclass(frozen=True)
class External:
    """Where data enters from outside the platform: a party or a file, drawn as a dashed card.

    Args:
        kind: ``party`` (a person or company), ``file`` (an import format) or ``device``.
        label: i18n key of the card title (``Surveyor``, ``LandXML, CSV point files``).
        role: Party role from ``ROLE_ZONES`` when ``kind`` is ``party``.
    """

    kind: str
    label: str
    role: str = ""


@dataclass(frozen=True)
class Duty:
    """What one role does in this module, in one plain sentence (i18n key)."""

    role: str
    label: str


@dataclass(frozen=True)
class Chip:
    """A live status chip on the module's card, e.g. "2 open" or "14 uncertain".

    Counted like an :class:`Entity` (project-scoped rows of ``model`` matching ``where``);
    the chip shows only when the count is above zero, so an empty chip never adds noise.
    """

    model: str
    label: str
    where: tuple[Where, ...] = ()
    tone: str = "info"


@dataclass(frozen=True)
class DataPaths:
    """Everything one module declares about its data paths.

    Args:
        entities: Record types shown in the centre card (3-6 is readable).
        inputs: Paths that bring data in.
        outputs: Paths that carry data out.
        parameters: Fields that drive numbers downstream.
        stale: Freshness rules.
        why: i18n key, one sentence: why this module's data matters.
        roles: Party roles that create or consume this module's data
            (vocabulary in ``app.modules.dataflow.parties.ROLE_ZONES``).
        duties: One sentence per role: what that role does here.
        external: Sources outside the platform (parties, files) that feed this module.
        chips: Live status chips shown on the module's card.
        reason: Required when nothing else is declared: why the module is isolated.
    """

    entities: tuple[Entity, ...] = ()
    inputs: tuple[DataPath, ...] = ()
    outputs: tuple[DataPath, ...] = ()
    parameters: tuple[Param, ...] = ()
    stale: tuple[Stale, ...] = ()
    why: str = ""
    roles: tuple[str, ...] = ()
    duties: tuple[Duty, ...] = ()
    external: tuple[External, ...] = ()
    chips: tuple[Chip, ...] = ()
    reason: str = ""

    MAX_PATHS = 12

    def paths(self) -> tuple[tuple[str, DataPath], ...]:
        """Inputs and outputs with their direction, in declaration order."""
        return tuple(("in", p) for p in self.inputs) + tuple(("out", p) for p in self.outputs)

    def gaps(self) -> list[str]:
        """What this declaration is missing; collected, never raised (see InferenceDeclaration.gaps)."""
        missing: list[str] = []
        if not (self.entities or self.inputs or self.outputs) and not self.reason.strip():
            missing.append("an isolated module has to say in `reason` why nothing flows in or out")
        if len(self.inputs) + len(self.outputs) > self.MAX_PATHS:
            missing.append(f"more than {self.MAX_PATHS} paths: the drawer stops being readable")
        if (self.inputs or self.outputs) and not self.why.strip():
            missing.append("`why` has to give the one sentence a user reads first")
        for duty in self.duties:
            if duty.role not in self.roles:
                missing.append(f"duty for role {duty.role!r} that is not in `roles`")
        for ext in self.external:
            if ext.kind not in EXTERNAL_KINDS:
                missing.append(f"external source kind {ext.kind!r} is not one of {sorted(EXTERNAL_KINDS)}")
        for chip in self.chips:
            if chip.tone not in CHIP_TONES:
                missing.append(f"chip {chip.label!r} tone {chip.tone!r} is not one of {sorted(CHIP_TONES)}")
            for cond in chip.where:
                if cond.op not in WHERE_OPS:
                    missing.append(f"chip {chip.label!r} filter op {cond.op!r} is not one of {sorted(WHERE_OPS)}")
        for _direction, path in self.paths():
            if path.importance is not Importance.SUPPORTING and not path.breaks.strip():
                missing.append(f"{path.module}.{path.entity} is {path.importance} but `breaks` says nothing")
            if path.scope not in ("project", "global"):
                missing.append(f"{path.module}.{path.entity} has unknown scope {path.scope!r}")
            for cond in path.where:
                if cond.op not in WHERE_OPS:
                    missing.append(
                        f"{path.module}.{path.entity} filter op {cond.op!r} is not one of {sorted(WHERE_OPS)}"
                    )
        return missing


__all__ = [
    "Chip",
    "Count",
    "DataPath",
    "DataPaths",
    "Duty",
    "Entity",
    "External",
    "Importance",
    "Latest",
    "Measure",
    "Param",
    "Stale",
    "Sum",
    "Where",
]
