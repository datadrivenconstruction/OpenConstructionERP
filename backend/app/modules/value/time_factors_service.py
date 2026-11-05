# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Admin-tunable hours-saved minute factors - the thin DB layer.

The pure :mod:`app.modules.value.time_saved` engine carries a conservative seed
map of "minutes one assisted action displaces" (:data:`DEFAULT_FACTORS`). An
operator who has measured their own baseline can override any of those factors,
per tenant, in the ``oe_value_time_factor`` table. This module is the small
read / upsert layer over that table plus the resolver that turns a tenant's
sparse overrides into the full effective factor map the aggregation functions
take.

Design:

* ``resolve_effective_factors`` reads the tenant's override rows and layers them
  over the engine defaults with the pure :func:`time_saved.merge_factors`, so an
  unset pair always falls back to its documented default and a fresh install
  (no rows) behaves exactly as before this table existed.
* ``list_factors`` returns the full editable surface - every default pair plus
  any tenant-only additions - each marked with whether it is a tenant override
  or the seed default, so the admin UI can show what is tuned vs inherited.
* ``set_factors`` upserts a batch of overrides for the tenant. A value equal to
  the default (or explicitly cleared) deletes the override row rather than
  storing a redundant copy, keeping the table sparse and "reset to default"
  honest.

Minutes, never money: the values are durations of saved effort, carried as
``Decimal`` end to end and validated non-negative. ``get_session`` owns the
commit, so this layer only flushes.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.validation.quality_rules import gate_rule_set, warning_findings
from app.modules.value.models import TimeSavedFactor
from app.modules.value.time_saved import DEFAULT_FACTORS, merge_factors
from app.modules.value.validators import VALUE_RULE_SET

#: Upper bound on a single factor (minutes). A day of manual work for one action
#: is already implausible; the cap stops a fat-fingered entry from making the
#: hours-saved headline absurd. Validated in :func:`_coerce_minutes`.
MAX_FACTOR_MINUTES = Decimal("1440")


@dataclass(frozen=True)
class FactorRow:
    """One editable factor: the pair, its effective minutes, and its provenance.

    ``minutes`` is the value currently in force (the override when set, else the
    seed default). ``default_minutes`` is the seed default for the pair (``None``
    for a tenant-only pair the seed map does not define). ``is_override`` is
    ``True`` when a tenant row overrides the default - the signal the UI uses to
    show "tuned" vs "inherited" and to enable a reset.
    """

    module: str
    action: str
    minutes: Decimal
    default_minutes: Decimal | None
    is_override: bool


def _coerce_minutes(value: object) -> Decimal:
    """Coerce an incoming factor value to a valid non-negative minute Decimal.

    Accepts an int / float / Decimal / numeric string. Raises :class:`ValueError`
    (which the router maps to a 422) on a non-numeric value, a negative value, or
    one above :data:`MAX_FACTOR_MINUTES`. The result is quantized to two places
    so it matches the column and the engine's whole/2dp Decimals.
    """
    try:
        minutes = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("minutes must be a number") from exc
    if not minutes.is_finite():
        raise ValueError("minutes must be a finite number")
    if minutes < 0:
        raise ValueError("minutes must not be negative")
    if minutes > MAX_FACTOR_MINUTES:
        raise ValueError(f"minutes must not exceed {MAX_FACTOR_MINUTES}")
    return minutes.quantize(Decimal("0.01"))


async def _override_map(session: AsyncSession, tenant_id: str) -> dict[tuple[str, str], Decimal]:
    """Read the tenant's override rows as a ``(module, action) -> minutes`` map."""
    stmt = select(TimeSavedFactor).where(TimeSavedFactor.tenant_id == tenant_id)
    rows = (await session.execute(stmt)).scalars().all()
    return {(r.module, r.action): r.minutes for r in rows}


async def resolve_effective_factors(
    session: AsyncSession,
    tenant_id: str | None,
) -> dict[tuple[str, str], Decimal]:
    """The full effective minute-factor map for a tenant (overrides over defaults).

    Reads the tenant's override rows and layers them on the engine defaults via
    the pure :func:`merge_factors`. A ``None`` tenant (anonymous / unresolved)
    yields the plain defaults, never another tenant's overrides - the safe
    fallback that keeps an unauthenticated aggregation honest rather than leaking.
    """
    if tenant_id is None:
        return dict(DEFAULT_FACTORS)
    overrides = await _override_map(session, tenant_id)
    return merge_factors(overrides)


async def list_factors(session: AsyncSession, tenant_id: str | None) -> list[FactorRow]:
    """List every editable factor for a tenant, marking overrides vs defaults.

    The surface is the union of the seed defaults and any tenant-only override
    pairs, so the UI can edit a known action even when the tenant has not tuned
    it yet, and can also see an override the tenant added for an action outside
    the seed map. Sorted by ``(module, action)`` for a stable display order.
    """
    overrides = await _override_map(session, tenant_id) if tenant_id is not None else {}

    keys = set(DEFAULT_FACTORS) | set(overrides)
    rows: list[FactorRow] = []
    for module, action in sorted(keys):
        default = DEFAULT_FACTORS.get((module, action))
        override = overrides.get((module, action))
        rows.append(
            FactorRow(
                module=module,
                action=action,
                minutes=override if override is not None else default,  # type: ignore[arg-type]
                default_minutes=default,
                is_override=override is not None,
            )
        )
    return rows


async def set_factors(
    session: AsyncSession,
    tenant_id: str,
    updates: list[tuple[str, str, object]],
    *,
    warnings_out: list[dict] | None = None,
) -> list[FactorRow]:
    """Upsert a batch of the tenant's factor overrides and return the new surface.

    Each update is ``(module, action, minutes)``. A value that equals the seed
    default for the pair deletes the override row (so the pair cleanly reverts to
    inheriting the default and the table stays sparse); any other valid value is
    written as an override, updating the existing row in place rather than
    duplicating it. ``minutes`` is validated by :func:`_coerce_minutes` (non
    -negative, finite, capped); an invalid value raises :class:`ValueError`
    before anything is written, so a bad batch is rejected atomically. Returns the
    full :func:`list_factors` surface after the change. The ``value`` rule set then runs over the
    batch: an error it introduces answers a coded 422 and writes nothing, warnings are appended to
    ``warnings_out`` when given.
    """
    # Validate and normalise the whole batch first, so one bad row rejects the
    # entire request before any mutation (all-or-nothing).
    coerced: list[tuple[str, str, Decimal]] = []
    for module, action, raw in updates:
        mod = (module or "").strip()
        act = (action or "").strip()
        if not mod or not act:
            raise ValueError("module and action are required")
        coerced.append((mod, act, _coerce_minutes(raw)))

    existing = {
        (r.module, r.action): r
        for r in (
            await session.execute(select(TimeSavedFactor).where(TimeSavedFactor.tenant_id == tenant_id))
        ).scalars()
    }

    batch = [
        {
            "module": mod,
            "action": act,
            "minutes": minutes,
            "default_minutes": DEFAULT_FACTORS.get((mod, act)),
            "known": (mod, act) in DEFAULT_FACTORS or (mod, act) in existing,
        }
        for mod, act, minutes in coerced
    ]
    stored = [
        {**r, "minutes": existing[(r["module"], r["action"])].minutes}
        for r in batch
        if (r["module"], r["action"]) in existing
    ]
    report = await gate_rule_set(
        rule_set=VALUE_RULE_SET,
        data={"factors": batch},
        target_type="time_factors",
        target_id=tenant_id,
        project_id=None,
        operation="update",
        subject="set of time factors",
        before={"factors": stored},
        error="value_rules_failed",
    )
    if warnings_out is not None:
        warnings_out.extend(warning_findings(report))

    for mod, act, minutes in coerced:
        default = DEFAULT_FACTORS.get((mod, act))
        row = existing.get((mod, act))
        if default is not None and minutes == default:
            # Reverting to the default: drop any override so the pair inherits.
            if row is not None:
                await session.delete(row)
            continue
        if row is None:
            row = TimeSavedFactor(tenant_id=tenant_id, module=mod, action=act, minutes=minutes)
            session.add(row)
            existing[(mod, act)] = row
        else:
            row.minutes = minutes

    await session.flush()
    return await list_factors(session, tenant_id)
