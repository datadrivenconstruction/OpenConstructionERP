# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure computation core for the construction interface register.

On any multi-package or multi-contractor job the real risk is not inside a work
package but between them: the handshakes where one party's work meets another's -
a duct that must pass through a structural opening, a power supply another trade
depends on, a contractual scope boundary, a shared piece of ground. Each such
handshake is an "interface": it has an owner (the party responsible for getting
it agreed), an accepter (the party that depends on it), a date it must be agreed
by, and a status running from identified to closed (with disputed and on_hold as
side states). The actions needed to close each interface are tracked alongside.

This module turns a flat list of interfaces (each with a status, a priority, a
type, an owning and accepting party, the originating work package, key dates and
its actions) into the numbers a coordinator needs: how the register splits by
status, priority and type; which interfaces are overdue (past their need-by date
and not yet settled) or in dispute; how much of the register is agreed; the open
action load; a per-work-package health view; and a single overall health score.

Everything here is a plain value object plus a set of functions. It is
``Decimal``-exact for every percentage it reports and carries no ORM, database,
FastAPI or Pydantic dependency, exactly like
:mod:`app.modules.temporary_works.register` and
:mod:`app.modules.site_prep.readiness`, so the whole core is trivially
constructed and asserted from plain values. The DB loaders that build
:class:`InterfaceRow` lists live in
:mod:`app.modules.interface_management.service`.

Guard convention: every percentage is guarded and returns ``None`` (never raises,
never a silent zero) when the base is zero - an empty register reads "undefined"
rather than "0 percent agreed" or "0 percent healthy".

Vocabulary convention: an unknown status, priority or type value never raises
here; it simply fails to match a bucket or a settled-state check, so a stray row
can never poison a whole-register rollup or make an interface look agreed.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any

# Every percentage this module reports is quantised to 2 dp, matching the
# platform-wide convention.
_PCT_Q = Decimal("0.01")
_HUNDRED = Decimal("100")


class InterfaceType(StrEnum):
    """The kind of handshake an interface represents."""

    PHYSICAL = "physical"  # two elements meet or clash in space (duct through beam)
    FUNCTIONAL = "functional"  # one system feeds or controls another (power, signal)
    CONTRACTUAL = "contractual"  # a scope boundary between two contracts / packages
    SPATIAL = "spatial"  # shared space, access or setting-out coordination
    INFORMATION = "information"  # a deliverable one party owes another (data, drawing)
    SCHEDULE = "schedule"  # a sequencing or timing dependency between packages


class InterfaceStatus(StrEnum):
    """Lifecycle status of a single interface.

    The main flow runs identified -> open -> in_progress -> agreed -> closed.
    ``disputed`` and ``on_hold`` are side states an interface can carry at any
    point and have no fixed position in the main flow.
    """

    IDENTIFIED = "identified"
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    AGREED = "agreed"
    CLOSED = "closed"
    DISPUTED = "disputed"
    ON_HOLD = "on_hold"


class Priority(StrEnum):
    """How urgent / important an interface is to resolve."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ActionStatus(StrEnum):
    """Lifecycle status of a single action needed to close an interface."""

    OPEN = "open"
    DONE = "done"
    CANCELLED = "cancelled"


# Canonical ordered tuples, exposed so schemas, the service and tests share one
# source of truth for the allowed vocabularies without importing the enums.
ALL_INTERFACE_TYPES: tuple[str, ...] = tuple(t.value for t in InterfaceType)
ALL_INTERFACE_STATUSES: tuple[str, ...] = tuple(s.value for s in InterfaceStatus)
ALL_PRIORITIES: tuple[str, ...] = tuple(p.value for p in Priority)
ALL_ACTION_STATUSES: tuple[str, ...] = tuple(s.value for s in ActionStatus)

# The bucket label used for interfaces whose priority, type or originating work
# package is not set. Shared across all three groupings so an "unassigned"
# bucket always means the same thing.
UNASSIGNED = "unassigned"

# An interface's handshake is settled once it is agreed or closed. Both count as
# "resolved" for the agreed percentage and the per-work-package agreed count.
_RESOLVED_STATUSES: frozenset[str] = frozenset(
    {InterfaceStatus.AGREED.value, InterfaceStatus.CLOSED.value},
)

# An interface no longer counts as overdue once its handshake is settled (agreed
# or closed) or it is explicitly paused (on_hold). On any other status a need-by
# date strictly in the past is overdue.
_OVERDUE_EXEMPT_STATUSES: frozenset[str] = frozenset(
    {
        InterfaceStatus.AGREED.value,
        InterfaceStatus.CLOSED.value,
        InterfaceStatus.ON_HOLD.value,
    },
)


def transition_problem(from_status: str, to_status: str) -> str | None:
    """Why a manual move from ``from_status`` to ``to_status`` is refused, or ``None`` when allowed.

    The one hard edge of the lifecycle: an interface is closed only once its
    handshake was agreed, so ``closed`` is reachable from ``agreed`` alone.
    Every other move (including the side states and re-opening) stays free, as
    a register is corrected by hand far more often than it is walked in order.
    """
    if to_status == from_status:
        return None
    if to_status == InterfaceStatus.CLOSED.value and from_status != InterfaceStatus.AGREED.value:
        return f"An interface can only be closed once it is agreed (it is {from_status})"
    return None


def safe_percent(numerator: int, denominator: int) -> Decimal | None:
    """Percentage ``numerator / denominator * 100`` quantised to 2 dp.

    The single guarded-division primitive every percentage in this module is
    built on: returns ``None`` when ``denominator`` is zero so "undefined" is
    represented uniformly and never as a raised ``ZeroDivisionError`` or a
    misleading ``0``.

    Args:
        numerator: Count of interfaces satisfying the condition.
        denominator: Size of the base being measured against.

    Returns:
        The 2-dp ``Decimal`` percentage, or ``None`` when ``denominator`` is 0.
    """
    if denominator == 0:
        return None
    ratio = Decimal(numerator) / Decimal(denominator) * _HUNDRED
    return ratio.quantize(_PCT_Q, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ActionRow:
    """One action needed to close an interface, as consumed by the pure functions.

    A DB-free projection of a persisted action row. ``status`` is the canonical
    string value (see :class:`ActionStatus`); an unknown value never raises here,
    it simply fails to count as open, so a stray row can never inflate the open
    action load.
    """

    status: str = "open"
    due_date: date | None = None

    @property
    def is_open(self) -> bool:
        """True when the action is still open (not done, not cancelled)."""
        return self.status == ActionStatus.OPEN.value


@dataclass(frozen=True)
class InterfaceRow:
    """One interface (handshake), as consumed by the pure functions here.

    A DB-free projection of a persisted interface row plus the actions attached
    to it. ``status``, ``priority`` and ``interface_type`` are the canonical
    string values; an unknown value never raises here, it simply fails to match a
    bucket or a settled-state check, so a stray row can never poison a rollup or
    make an interface look agreed.
    """

    id: str | None = None
    reference: str = ""
    title: str = ""
    status: str = "identified"
    priority: str | None = None
    interface_type: str | None = None
    owner_party: str | None = None
    accepter_party: str | None = None
    work_package_from: str | None = None
    need_by_date: date | None = None
    agreed_date: date | None = None
    actions: list[ActionRow] = field(default_factory=list)
    # The day the interface entered the register (its creation date). Drives the
    # ageing view; ``None`` when unknown, which lands in the ``unknown`` bucket.
    opened_on: date | None = None

    @property
    def is_resolved(self) -> bool:
        """True when the handshake is settled (agreed or closed)."""
        return self.status in _RESOLVED_STATUSES

    @property
    def is_open(self) -> bool:
        """True when the interface is not yet settled (anything but agreed/closed).

        "Open" here is the wide sense any coordinator means by an open item -
        still needing attention. That includes ``identified``, ``open``,
        ``in_progress``, ``disputed`` and ``on_hold``; only ``agreed`` and
        ``closed`` are excluded.
        """
        return self.status not in _RESOLVED_STATUSES

    @property
    def is_disputed(self) -> bool:
        """True when the interface is in dispute."""
        return self.status == InterfaceStatus.DISPUTED.value

    def to_ref(self, as_of: date | None = None) -> dict[str, Any]:
        """JSON-ready reference to this interface (dates as ISO strings).

        With ``as_of`` the reference also carries ``age_days`` (days since the
        interface was opened) and ``days_overdue`` (days past its need-by date,
        ``None`` when it is not overdue); without it both are ``None``.
        """
        return {
            "interface_id": self.id,
            "reference": self.reference,
            "title": self.title,
            "status": self.status,
            "priority": self.priority,
            "interface_type": self.interface_type,
            "owner_party": self.owner_party,
            "accepter_party": self.accepter_party,
            "work_package_from": self.work_package_from,
            "need_by_date": (self.need_by_date.isoformat() if self.need_by_date is not None else None),
            "agreed_date": (self.agreed_date.isoformat() if self.agreed_date is not None else None),
            "open_action_count": open_action_count(self),
            "age_days": age_days(self, as_of) if as_of is not None else None,
            "days_overdue": days_overdue(self, as_of) if as_of is not None else None,
        }


@dataclass(frozen=True)
class WorkPackageHealth:
    """Health rollup for one originating work package (or one grouping label)."""

    work_package: str
    total: int
    open: int
    overdue: int
    agreed: int
    health_score: Decimal | None  # None when total == 0 (guarded)

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready view of one work package's health.

        ``health_score`` stays a ``Decimal`` (or ``None``); the response schema
        serialises it to a plain decimal string so no float rounding is
        introduced at the API edge.
        """
        return {
            "work_package": self.work_package,
            "total": self.total,
            "open": self.open,
            "overdue": self.overdue,
            "agreed": self.agreed,
            "health_score": self.health_score,
        }


@dataclass(frozen=True)
class InterfaceRegister:
    """Whole-project interface rollup: counts, agreement, overdue, disputes, health."""

    as_of: date
    total: int
    per_status: dict[str, int]
    per_priority: dict[str, int]
    per_type: dict[str, int]
    agreed_pct: Decimal | None  # None when total == 0 (guarded)
    overall_health_score: Decimal | None  # None when total == 0 (guarded)
    total_open_actions: int
    is_healthy: bool
    overdue: list[InterfaceRow] = field(default_factory=list)
    disputed: list[InterfaceRow] = field(default_factory=list)
    work_packages: list[WorkPackageHealth] = field(default_factory=list)
    open_count: int = 0
    overdue_count: int = 0
    ageing: dict[str, int] = field(default_factory=dict)
    overdue_ageing: dict[str, int] = field(default_factory=dict)
    average_open_age_days: Decimal | None = None  # None when no open interface has an age
    oldest_open_age_days: int | None = None
    max_days_overdue: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready view of the whole register.

        ``agreed_pct`` and ``overall_health_score`` are left as ``Decimal`` (or
        ``None``); the response schema serialises them to plain decimal strings
        so no float rounding is introduced at the API edge.
        """
        return {
            "as_of": self.as_of.isoformat(),
            "total": self.total,
            "per_status": dict(self.per_status),
            "per_priority": dict(self.per_priority),
            "per_type": dict(self.per_type),
            "agreed_pct": self.agreed_pct,
            "overall_health_score": self.overall_health_score,
            "total_open_actions": self.total_open_actions,
            "is_healthy": self.is_healthy,
            "overdue": [i.to_ref(self.as_of) for i in self.overdue],
            "disputed": [i.to_ref(self.as_of) for i in self.disputed],
            "work_packages": [w.to_dict() for w in self.work_packages],
            "open_count": self.open_count,
            "overdue_count": self.overdue_count,
            "ageing": dict(self.ageing),
            "overdue_ageing": dict(self.overdue_ageing),
            "average_open_age_days": self.average_open_age_days,
            "oldest_open_age_days": self.oldest_open_age_days,
            "max_days_overdue": self.max_days_overdue,
        }


# -- Per-interface predicates ------------------------------------------------


def can_be_overdue(status: str) -> bool:
    """Whether an interface on this status can be overdue at all.

    A settled handshake (agreed, closed) and a deliberately paused one
    (on_hold) never count as overdue however far past their need-by date they
    sit. Exposed because a caller that has to choose a status before it holds a
    row - the demo seeder deciding which interfaces land on the overdue tile -
    would otherwise restate the exemption set and drift out of step with it.
    """
    return status not in _OVERDUE_EXEMPT_STATUSES


def is_overdue(interface: InterfaceRow, as_of: date) -> bool:
    """True when the interface is past its need-by date and not yet settled.

    An interface with no need-by date is never overdue. An interface that is
    agreed, closed or on_hold is never overdue (its handshake is settled or
    deliberately paused). On any other status a need-by date strictly before
    ``as_of`` is overdue; the need-by date falling exactly on ``as_of`` is not.
    """
    if interface.need_by_date is None:
        return False
    if not can_be_overdue(interface.status):
        return False
    return interface.need_by_date < as_of


def age_days(interface: InterfaceRow, as_of: date) -> int | None:
    """Whole days the interface has been on the register at ``as_of``.

    ``None`` when the opening date is unknown. An opening date after ``as_of``
    (a register read as of a day before the row existed) reads as 0, never
    negative.
    """
    if interface.opened_on is None:
        return None
    return max((as_of - interface.opened_on).days, 0)


def days_overdue(interface: InterfaceRow, as_of: date) -> int | None:
    """Whole days past the need-by date, or ``None`` when the interface is not overdue."""
    if interface.need_by_date is None or not is_overdue(interface, as_of):
        return None
    return (as_of - interface.need_by_date).days


def open_action_count(interface: InterfaceRow) -> int:
    """Number of still-open actions on the interface (done/cancelled excluded)."""
    return sum(1 for action in interface.actions if action.is_open)


# -- Collections -------------------------------------------------------------


def overdue_interfaces(interfaces: Iterable[InterfaceRow], as_of: date) -> list[InterfaceRow]:
    """Interfaces past their need-by date and not yet settled, in input order."""
    return [interface for interface in interfaces if is_overdue(interface, as_of)]


def disputed_interfaces(interfaces: Iterable[InterfaceRow]) -> list[InterfaceRow]:
    """Interfaces whose status is ``disputed``, in input order."""
    return [interface for interface in interfaces if interface.is_disputed]


def total_open_actions(interfaces: Iterable[InterfaceRow]) -> int:
    """Total number of open actions across every interface."""
    return sum(open_action_count(interface) for interface in interfaces)


# -- Counts ------------------------------------------------------------------


def status_counts(interfaces: Iterable[InterfaceRow]) -> dict[str, int]:
    """Count interfaces by status, zero-filling every known status in canonical order."""
    counts: dict[str, int] = dict.fromkeys(ALL_INTERFACE_STATUSES, 0)
    for interface in interfaces:
        if interface.status in counts:
            counts[interface.status] += 1
        else:  # defensive: an unknown status still shows up so nothing is lost
            counts[interface.status] = counts.get(interface.status, 0) + 1
    return counts


def priority_counts(interfaces: Iterable[InterfaceRow]) -> dict[str, int]:
    """Count interfaces by priority, zero-filling every priority plus unassigned.

    An interface with no priority set is counted under :data:`UNASSIGNED`; an
    out-of-vocabulary priority value is still counted (defensively) rather than
    dropped, so the per-priority counts always sum to the total.
    """
    counts: dict[str, int] = dict.fromkeys(ALL_PRIORITIES, 0)
    counts[UNASSIGNED] = 0
    for interface in interfaces:
        key = interface.priority if interface.priority is not None else UNASSIGNED
        if key in counts:
            counts[key] += 1
        else:  # defensive: an unknown priority still shows up so nothing is lost
            counts[key] = counts.get(key, 0) + 1
    return counts


def type_counts(interfaces: Iterable[InterfaceRow]) -> dict[str, int]:
    """Count interfaces by type, zero-filling every type plus unassigned.

    An interface with no type set is counted under :data:`UNASSIGNED`; an
    out-of-vocabulary type value is still counted (defensively) rather than
    dropped, so the per-type counts always sum to the total.
    """
    counts: dict[str, int] = dict.fromkeys(ALL_INTERFACE_TYPES, 0)
    counts[UNASSIGNED] = 0
    for interface in interfaces:
        key = interface.interface_type if interface.interface_type is not None else UNASSIGNED
        if key in counts:
            counts[key] += 1
        else:  # defensive: an unknown type still shows up so nothing is lost
            counts[key] = counts.get(key, 0) + 1
    return counts


# -- Agreement and health ----------------------------------------------------


def resolved_count(interfaces: Iterable[InterfaceRow]) -> int:
    """Number of interfaces whose handshake is settled (agreed or closed)."""
    return sum(1 for interface in interfaces if interface.is_resolved)


def agreed_pct(interfaces: Iterable[InterfaceRow]) -> Decimal | None:
    """Settled interfaces as a percentage of all interfaces, guarded to ``None``.

    ``(agreed + closed) / total * 100`` quantised to 2 dp, or ``None`` when the
    register is empty.
    """
    materialised = list(interfaces)
    return safe_percent(resolved_count(materialised), len(materialised))


def overall_health_score(interfaces: Iterable[InterfaceRow], as_of: date) -> Decimal | None:
    """Share of interfaces that are not overdue, as a percentage, guarded to ``None``.

    ``(total - overdue) / total * 100`` quantised to 2 dp, or ``None`` when the
    register is empty. A register with nothing overdue scores 100; one where
    every interface is overdue scores 0.
    """
    materialised = list(interfaces)
    total = len(materialised)
    overdue = sum(1 for interface in materialised if is_overdue(interface, as_of))
    return safe_percent(total - overdue, total)


def is_healthy(interfaces: Iterable[InterfaceRow], as_of: date) -> bool:
    """True when nothing is overdue and nothing is in dispute.

    The honest single-flag summary of the register: an interface past its
    need-by date, or one in dispute, both mean the register needs attention.
    Vacuously true for an empty register - there is nothing to be unhealthy.
    """
    materialised = list(interfaces)
    has_overdue = any(is_overdue(interface, as_of) for interface in materialised)
    has_disputed = any(interface.is_disputed for interface in materialised)
    return not has_overdue and not has_disputed


# -- Per-work-package health -------------------------------------------------


def _work_package_key(interface: InterfaceRow) -> str:
    """The grouping label for an interface: its originating work package or unassigned.

    A ``None`` or blank (whitespace-only) ``work_package_from`` groups under
    :data:`UNASSIGNED` so every interface lands in exactly one bucket and the
    per-work-package totals always sum to the register total.
    """
    work_package = interface.work_package_from
    if work_package is None:
        return UNASSIGNED
    stripped = work_package.strip()
    return stripped if stripped else UNASSIGNED


def _ordered_work_packages(interfaces: list[InterfaceRow]) -> list[str]:
    """Present work-package labels: named packages sorted, then unassigned last.

    Work-package names are free text with no canonical order, so named packages
    are sorted alphabetically for a stable, testable output; the ``unassigned``
    bucket, when present, is always appended last.
    """
    keys = {_work_package_key(interface) for interface in interfaces}
    ordered = sorted(key for key in keys if key != UNASSIGNED)
    if UNASSIGNED in keys:
        ordered.append(UNASSIGNED)
    return ordered


def _work_package_health(interfaces: list[InterfaceRow], label: str, as_of: date) -> WorkPackageHealth:
    """Build a :class:`WorkPackageHealth` for an already-filtered interface list.

    ``open`` counts interfaces not yet settled (see :attr:`InterfaceRow.is_open`),
    ``agreed`` counts settled interfaces (agreed or closed), and ``health_score``
    is the share not overdue, guarded to ``None`` for an empty group.
    """
    total = len(interfaces)
    overdue = sum(1 for interface in interfaces if is_overdue(interface, as_of))
    return WorkPackageHealth(
        work_package=label,
        total=total,
        open=sum(1 for interface in interfaces if interface.is_open),
        overdue=overdue,
        agreed=sum(1 for interface in interfaces if interface.is_resolved),
        health_score=safe_percent(total - overdue, total),
    )


def work_package_health(interfaces: Iterable[InterfaceRow], as_of: date) -> list[WorkPackageHealth]:
    """Per-work-package health, one entry per originating work package present."""
    materialised = list(interfaces)
    return [
        _work_package_health(
            [interface for interface in materialised if _work_package_key(interface) == label],
            label,
            as_of,
        )
        for label in _ordered_work_packages(materialised)
    ]


# -- Ageing ------------------------------------------------------------------

# Age bands for the open interfaces (days since opened) and for the overdue ones
# (days past need-by). Each band is (label, lowest day, highest day or None for
# open-ended); the bands of one tuple are contiguous and do not overlap, so every
# value lands in exactly one band.
AGEING_BUCKETS: tuple[tuple[str, int, int | None], ...] = (
    ("0_7", 0, 7),
    ("8_30", 8, 30),
    ("31_60", 31, 60),
    ("61_90", 61, 90),
    ("over_90", 91, None),
)
OVERDUE_BUCKETS: tuple[tuple[str, int, int | None], ...] = (
    ("1_7", 1, 7),
    ("8_30", 8, 30),
    ("31_60", 31, 60),
    ("over_60", 61, None),
)
# Open interfaces whose opening date is unknown are counted here, so the ageing
# counts always sum to the number of open interfaces.
UNKNOWN_AGE = "unknown"


def _bucket(value: int, buckets: tuple[tuple[str, int, int | None], ...]) -> str:
    """The label of the band ``value`` falls in (the first band when below all of them)."""
    for label, low, high in buckets:
        if value >= low and (high is None or value <= high):
            return label
    return buckets[0][0]


def open_ageing(interfaces: Iterable[InterfaceRow], as_of: date) -> dict[str, int]:
    """Count the open (unsettled) interfaces by how long they have been on the register.

    Zero-fills every band plus :data:`UNKNOWN_AGE`, so the result always has the
    same keys and sums to the number of open interfaces.
    """
    counts: dict[str, int] = {label: 0 for label, _low, _high in AGEING_BUCKETS}
    counts[UNKNOWN_AGE] = 0
    for interface in interfaces:
        if not interface.is_open:
            continue
        age = age_days(interface, as_of)
        key = UNKNOWN_AGE if age is None else _bucket(age, AGEING_BUCKETS)
        counts[key] += 1
    return counts


def overdue_ageing(interfaces: Iterable[InterfaceRow], as_of: date) -> dict[str, int]:
    """Count the overdue interfaces by days past their need-by date (zero-filled)."""
    counts: dict[str, int] = {label: 0 for label, _low, _high in OVERDUE_BUCKETS}
    for interface in interfaces:
        late = days_overdue(interface, as_of)
        if late is not None:
            counts[_bucket(late, OVERDUE_BUCKETS)] += 1
    return counts


def _open_ages(interfaces: Iterable[InterfaceRow], as_of: date) -> list[int]:
    """Ages of the open interfaces whose opening date is known."""
    return [a for a in (age_days(i, as_of) for i in interfaces if i.is_open) if a is not None]


def average_open_age(interfaces: Iterable[InterfaceRow], as_of: date) -> Decimal | None:
    """Mean age in days of the open interfaces with a known age, 2 dp, ``None`` when there are none."""
    ages = _open_ages(interfaces, as_of)
    if not ages:
        return None
    return (Decimal(sum(ages)) / Decimal(len(ages))).quantize(_PCT_Q, rounding=ROUND_HALF_UP)


def oldest_open_age(interfaces: Iterable[InterfaceRow], as_of: date) -> int | None:
    """Age in days of the oldest open interface, ``None`` when no open interface has an age."""
    ages = _open_ages(interfaces, as_of)
    return max(ages) if ages else None


def max_days_overdue(interfaces: Iterable[InterfaceRow], as_of: date) -> int | None:
    """The most days any interface is past its need-by date, ``None`` when none is overdue."""
    late = [d for d in (days_overdue(i, as_of) for i in interfaces) if d is not None]
    return max(late) if late else None


# -- Report assembly ---------------------------------------------------------


def build_report(interfaces: Iterable[InterfaceRow], as_of: date) -> InterfaceRegister:
    """Assemble the full interface register rollup in a single pass.

    Computes the per-status, per-priority and per-type counts, the agreed
    percentage, the overall health score, the total open action load, the
    overdue and disputed lists, the per-work-package health view, the single
    ``is_healthy`` flag (nothing overdue and nothing in dispute), and the ageing
    view: open interfaces by days on the register, overdue interfaces by days
    past need-by, the mean and oldest open age and the worst lateness.

    Args:
        interfaces: The register interfaces with their actions.
        as_of: The date the overdue checks and health score are evaluated
            against.

    Returns:
        An :class:`InterfaceRegister` value object.
    """
    materialised = list(interfaces)
    total = len(materialised)
    overdue = overdue_interfaces(materialised, as_of)
    disputed = disputed_interfaces(materialised)
    return InterfaceRegister(
        as_of=as_of,
        total=total,
        per_status=status_counts(materialised),
        per_priority=priority_counts(materialised),
        per_type=type_counts(materialised),
        agreed_pct=safe_percent(resolved_count(materialised), total),
        overall_health_score=safe_percent(total - len(overdue), total),
        total_open_actions=total_open_actions(materialised),
        is_healthy=not overdue and not disputed,
        overdue=overdue,
        disputed=disputed,
        work_packages=work_package_health(materialised, as_of),
        open_count=sum(1 for interface in materialised if interface.is_open),
        overdue_count=len(overdue),
        ageing=open_ageing(materialised, as_of),
        overdue_ageing=overdue_ageing(materialised, as_of),
        average_open_age_days=average_open_age(materialised, as_of),
        oldest_open_age_days=oldest_open_age(materialised, as_of),
        max_days_overdue=max_days_overdue(materialised, as_of),
    )
