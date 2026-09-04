# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Apply / update / un-apply a partner pack onto the running installation.

Design decisions (confirmed with the product owner 2026-05-29):
  * Scope is a single global active pack (single-tenant).
  * Enabling the pack's ``default_modules`` is automatic (additive, safe).
  * Disabling the pack's ``hidden_modules`` happens ONLY with explicit
    ``confirm_disables`` - never silently turn off work-in-progress.
  * ``validation_rule_sets`` names engine rule-set identifiers, and those are
    what actually switch rules on: every project created while the pack is
    active inherits them. An entry the registry does not know is refused with
    :class:`UnknownRuleSetError` rather than ignored, because a rule set the
    engine has never heard of runs nothing and reports nothing, which is
    indistinguishable from a pack that enables nothing on purpose.
  * ``validation_rule_packs`` names the reference documents the pack ships
    under ``rule_packs/``; the engine does not execute those (see the
    partner-pack ADR). Where such an entry names a standard the engine does
    implement under a different identifier, the plan says so - unless the pack
    has since declared that identifier in ``validation_rule_sets``, in which
    case the rules already run and there is nothing to report.
  * Currency / locale / tax / CWICR are recorded as the new defaults and NEVER
    re-denominate or mutate existing projects' data.

The headline effect of an apply is that ``get_active_pack`` starts returning the
chosen pack (co-branding, logo, colours, shipped locales) immediately - the
apply service busts the discovery cache so no restart is needed.
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Sequence
from typing import Any

from fastapi import FastAPI

from app.core.module_loader import module_loader
from app.core.partner_pack.discovery import (
    get_pack_by_slug,
    reset_cache,
)
from app.core.partner_pack.manifest import PartnerPackManifest
from app.core.partner_pack.state import (
    AppliedPackState,
    clear_applied_state,
    load_applied_state,
    save_applied_state,
)

logger = logging.getLogger(__name__)


def _known_rule_sets() -> set[str]:
    """Built-in validation rule-set identifiers, best-effort.

    These are the names a rule was REGISTERED under, which is not the same list
    as the ``standard`` attribute the rule classes carry. Reading the attribute
    instead gives 28 names where the registry has 29, and five of them differ:
    ``ai_estimator``, ``rfq_issue`` and ``rfq_award`` are set names that are
    never a standard, and ``ai_takeoff`` and ``rfq`` are standards that are
    never a set name. Only the registry decides here, so only the registry is
    asked.
    """
    try:
        from app.core.validation.engine import rule_registry

        return set(rule_registry.list_rule_sets().keys())
    except Exception:  # noqa: BLE001 - validation engine optional at this layer
        return set()


def _squash(name: str) -> str:
    return "".join(c for c in name.lower() if c.isalnum())


def _near_miss_rule_set(slug: str, known: set[str]) -> str | None:
    """The built-in rule set a declared name plainly refers to, if any.

    ``validation_rule_packs`` carries two kinds of name at once: identifiers of
    built-in rule sets, and the ids of the reference documents the pack ships
    under ``rule_packs/``. A pack that ships ``rule_packs/din_276.json`` and
    declares ``din_276`` is doing the second of those, correctly, and the
    engine never executes that file. But the engine also holds four DIN 276
    rules registered as ``din276``, and until now nothing said so: the entry
    landed in the documentation-only pile behind the phrase "no built-in engine
    match", which is true of the name and false of the standard.

    So this asks a narrower question than equality. Does some built-in set name
    the same standard once the separators are dropped, or does the declared
    name begin with a set name and then break, either at a separator the way
    ``masterformat_2020`` breaks after ``masterformat``, or into digits the way
    ``din276`` would if someone wrote ``din2762018``.

    The prefix has to stop at a boundary rather than merely be a prefix. A
    minimum length was the first attempt and it was wrong in both directions:
    it let ``nbrigade_scheduling`` past on the strength of ``nbr`` being short
    while hiding the genuine ``nrm_1_cost_planning``, which is exactly the kind
    of pairing this is for. Boundaries answer both without a magic number.

    It never activates anything and is not meant to; ``validation_rule_sets``
    is the field that does. Several of the rules on the other side are error
    severity, so switching a set on can start failing bills of quantities that
    pass today; that is a decision for whoever writes the pack, and all this
    does is make sure the pairing is visible before they make it.
    """
    squashed = _squash(slug)
    by_squash = {_squash(k): k for k in known}
    if squashed in by_squash:
        return by_squash[squashed]
    lowered = slug.lower()
    for name in sorted(known):
        if lowered.startswith(f"{name}_") or lowered.startswith(f"{name}-"):
            return name
        tail = squashed[len(_squash(name)) :]
        if squashed.startswith(_squash(name)) and tail.isdigit():
            return name
    return None


def _rule_set_severities(names: Sequence[str]) -> dict[str, dict[str, int]]:
    """How many rules of each severity each named rule set holds.

    The admin deciding whether to apply a pack needs this before the button,
    not after: switching on a set that carries error-severity rules starts
    blocking bills of quantities that pass today. Best-effort - a registry that
    cannot be read yields an empty mapping rather than a wrong one.

    Args:
        names: Rule-set identifiers, assumed already resolved.

    Returns:
        ``{set_name: {"error": n, "warning": n, "info": n}}``, omitting
        severities with no rules.
    """
    try:
        from app.core.validation.engine import rule_registry
    except Exception:  # noqa: BLE001 - validation engine optional at this layer
        return {}

    out: dict[str, dict[str, int]] = {}
    for name in names:
        counts: dict[str, int] = {}
        try:
            for entry in rule_registry.list_rules(rule_set=name):
                rule = rule_registry.get_rule(entry.get("rule_id", ""))
                if rule is None:
                    continue
                key = str(rule.severity)
                counts[key] = counts.get(key, 0) + 1
        except Exception as exc:  # noqa: BLE001 - introspection must not break a plan
            logger.debug("Could not count severities for rule set %s: %s", name, exc)
        out[name] = counts
    return out


class UnknownRuleSetError(ValueError):
    """A pack named a validation rule set the engine does not register.

    Raised at apply time, where the registry is populated and the answer means
    something. It is deliberately fatal: a rule set the engine has never heard
    of activates nothing and reports nothing, which is indistinguishable from a
    pack that chose to activate nothing. Refusing is the only way the two stay
    distinguishable.
    """


#: The rule set every project validates against when nothing else is asked for.
#: Mirrors ``ProjectCreate.validation_rule_sets`` and
#: ``Settings.default_validation_rule_sets``.
_BASELINE_RULE_SET = "boq_quality"


def resolve_declared_rule_sets(m: PartnerPackManifest, *, strict: bool = False) -> list[str]:
    """The pack's ``validation_rule_sets`` that the engine actually registers.

    Args:
        m: The pack manifest.
        strict: When true, an entry the registry does not know raises instead
            of being dropped. Apply and preview use ``strict``; project
            creation does not, because a project must never fail to be created
            over a pack's mistake.

    Returns:
        The declared identifiers that resolve, in the order declared.

    Raises:
        UnknownRuleSetError: In strict mode, when an entry does not resolve, or
            when the registry reads back empty so nothing could be resolved
            against it.
    """
    declared = list(m.validation_rule_sets or [])
    if not declared:
        return []

    known = _known_rule_sets()
    if not known:
        if not strict:
            return []
        raise UnknownRuleSetError(
            f"Pack '{m.slug}' declares validation rule sets {declared}, but the validation "
            "registry came back empty, so none of them could be verified. Applying now would "
            "switch nothing on and say nothing about it."
        )

    unknown = [name for name in declared if name not in known]
    if unknown and strict:
        hints = []
        for name in unknown:
            neighbour = _near_miss_rule_set(name, known)
            hints.append(f"{name!r}" + (f" (did you mean {neighbour!r}?)" if neighbour else ""))
        raise UnknownRuleSetError(
            f"Pack '{m.slug}' declares validation rule set(s) the engine does not register: "
            f"{', '.join(hints)}. A rule set the registry does not know runs no rules and "
            "raises no error, so it would look exactly like a pack that enables nothing. "
            "A rule set owned by a module (the formwork rules, for one) is absent whenever "
            "that module is disabled, because the loader only imports the validators of the "
            "modules it loads: enable the module and apply again, or drop the entry."
        )
    if unknown:
        logger.warning(
            "Pack %s declares validation rule set(s) the engine does not register: %s; ignoring them",
            m.slug,
            ", ".join(unknown),
        )
    return [name for name in declared if name in known]


def inherited_rule_sets(
    declared: Sequence[str] | None,
    pack: PartnerPackManifest | None,
) -> list[str]:
    """The rule sets a project should carry, given the pack active at creation.

    Additive and order-preserving: whatever the caller asked for comes first
    and is never dropped, then the active pack's sets are appended. A pack
    widens what a project validates against; it never narrows it.

    Unresolvable pack entries are skipped rather than raising - a project must
    be creatable even when a pack is wrong, and writing an identifier the
    engine does not know would only move the silence downstream.

    Args:
        declared: The rule sets the caller asked for.
        pack: The pack active at creation time, or ``None``.

    Returns:
        The de-duplicated union, never empty.
    """
    out: list[str] = []
    seen: set[str] = set()
    for name in declared or []:
        cleaned = str(name).strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            out.append(cleaned)
    # An empty caller list means "validate against nothing", which is never
    # what someone who omitted the field meant, and the rest of the platform
    # already reads it as the baseline (``project.validation_rule_sets or
    # ["boq_quality"]`` in the BOQ router, ``_rule_sets_for`` in the validation
    # seeder). Seed it here so a pack widens the baseline instead of replacing
    # it: inheriting NRM must not cost a project its universal BOQ hygiene.
    if not out:
        out.append(_BASELINE_RULE_SET)
        seen.add(_BASELINE_RULE_SET)
    if pack is not None:
        for name in resolve_declared_rule_sets(pack):
            if name not in seen:
                seen.add(name)
                out.append(name)
    return out


def _module_exists(name: str) -> bool:
    try:
        return name in module_loader._manifests  # noqa: SLF001 - same package boundary
    except Exception:  # noqa: BLE001
        return False


def _pack_demo_info(slug: str) -> dict[str, Any] | None:
    """The flagship country demo project this pack installs, if any.

    Used by both the dry-run preview (so the admin sees what data will be
    seeded) and the apply effects. Returns ``None`` for packs without a mapped
    demo. Import is local + fail-soft so a demo-registry hiccup never breaks
    pack discovery.
    """
    try:
        from app.core.demo_projects import DEMO_CATALOG, PACK_DEMO_PROJECT
    except Exception:  # pragma: no cover - demo registry optional
        return None
    demo_id = PACK_DEMO_PROJECT.get(slug)
    if not demo_id:
        return None
    info: dict[str, Any] = {"demo_id": demo_id}
    entry = next((c for c in DEMO_CATALOG if c.get("demo_id") == demo_id), None)
    if entry:
        for k in ("name", "currency", "positions", "region", "classification_standard"):
            if k in entry:
                info[k] = entry[k]
    return info


def _plan(m: PartnerPackManifest, *, strict_rule_sets: bool = True) -> dict[str, Any]:
    """Compute the field-by-field effect plan for applying pack ``m`` (no mutation).

    Args:
        m: The pack manifest.
        strict_rule_sets: Whether an unresolvable ``validation_rule_sets``
            entry raises. Left on for both preview and apply so the admin sees
            the refusal before the button as well as after it.

    Returns:
        The effect plan.

    Raises:
        UnknownRuleSetError: When ``strict_rule_sets`` and the pack names a
            rule set the engine does not register.
    """
    default_modules = list(m.default_modules or [])
    hidden_modules = list(m.hidden_modules or [])
    rule_packs = list(m.validation_rule_packs or [])

    to_enable = [x for x in default_modules if _module_exists(x)]
    enable_missing = [x for x in default_modules if not _module_exists(x)]
    to_disable = [x for x in hidden_modules if _module_exists(x)]
    disable_missing = [x for x in hidden_modules if not _module_exists(x)]

    known = _known_rule_sets()
    rules_active = [r for r in rule_packs if r in known]
    rules_docs_only = [r for r in rule_packs if r not in known]
    # A near miss is only worth reporting while the pack has not yet declared
    # the engine identifier next to it. Once it has, the rules run and the
    # document id is doing its own job.
    rule_sets = resolve_declared_rule_sets(m, strict=strict_rule_sets)
    near_misses = {
        r: match for r in rules_docs_only if (match := _near_miss_rule_set(r, known)) and match not in rule_sets
    }

    warnings: list[str] = []
    if enable_missing:
        warnings.append(
            f"{len(enable_missing)} module(s) the pack wants enabled are not installed: {', '.join(enable_missing)}"
        )
    if disable_missing:
        warnings.append(
            f"{len(disable_missing)} module(s) the pack wants hidden are not installed: {', '.join(disable_missing)}"
        )
    if rules_docs_only:
        warnings.append(
            f"{len(rules_docs_only)} validation rule pack(s) are documentation-only (no built-in engine match): {', '.join(rules_docs_only)}"
        )
    if near_misses:
        pairs = ", ".join(f"{declared} -> {builtin}" for declared, builtin in sorted(near_misses.items()))
        warnings.append(
            f"{len(near_misses)} of those name a standard the engine does implement, under a different "
            f"identifier ({pairs}). Nothing was switched on: add the engine identifier to "
            "validation_rule_sets if those rules should run, and read them first, because some of "
            "them are error severity and will fail bills of quantities that pass today."
        )
    if rule_sets:
        counts = _rule_set_severities(rule_sets)
        n_errors = sum(c.get("error", 0) for c in counts.values())
        warnings.append(
            f"Validation rule set(s) {', '.join(rule_sets)} will be switched on for every project "
            f"created from here on while this pack is active ({n_errors} error-severity rule(s) "
            "among them will block a bill of quantities that fails them - a bill carrying no "
            "classification codes fails one per line). Existing projects keep the rule sets they "
            "already carry, and so does this pack's demo project, which ships its own."
        )
    if m.default_currency:
        warnings.append(
            f"Default currency {m.default_currency} applies to NEW projects only; existing projects keep their currency."
        )
    if m.default_tax_template:
        warnings.append(
            f"Default tax template '{m.default_tax_template}' is recorded for reference (no automatic tax resolver yet)."
        )
    if m.default_methodology:
        warnings.append(
            f"Estimating methodology '{m.default_methodology}' will be activated on the pack's demo "
            "project and seeded on new projects created while the pack is active."
        )
    if m.cwicr_regions:
        warnings.append(
            f"CWICR regions {', '.join(m.cwicr_regions)} are recorded; cost data is not downloaded automatically."
        )

    return {
        "branding": {
            "partner_name": m.partner_name,
            "powered_by": m.effective_powered_by,
            "primary_color": m.branding.primary_color,
            "accent_color": m.branding.accent_color,
        },
        "modules_to_enable": to_enable,
        "modules_to_enable_missing": enable_missing,
        "modules_to_disable": to_disable,
        "modules_to_disable_missing": disable_missing,
        "default_currency": m.default_currency,
        "default_locale": m.default_locale,
        "additional_locales": list(m.additional_locales.keys()),
        "rule_packs_active": rules_active,
        "rule_packs_documentation_only": rules_docs_only,
        "rule_packs_engine_equivalent": near_misses,
        "rule_sets_enabled": rule_sets,
        "rule_sets_severities": _rule_set_severities(rule_sets),
        "cwicr_regions": list(m.cwicr_regions or []),
        "default_tax_template": m.default_tax_template,
        "default_methodology": m.default_methodology,
        "demo_project": _pack_demo_info(m.slug),
        "warnings": warnings,
    }


def build_preview(slug: str) -> dict[str, Any]:
    """Dry-run: what would applying this pack change?

    Args:
        slug: The installed pack's slug.

    Returns:
        The preview payload, including the effect plan.

    Raises:
        ValueError: If no pack is installed under ``slug``.
        UnknownRuleSetError: If the pack names a rule set the engine does not
            register. The preview refuses for the same reason the apply does -
            an admin must not be shown a plan the apply will reject.
    """
    m = get_pack_by_slug(slug)
    if not m:
        raise ValueError(f"Pack '{slug}' is not installed")
    plan = _plan(m)
    return {
        "slug": m.slug,
        "partner_name": m.partner_name,
        "pack_version": m.pack_version,
        "will_disable_modules": bool(plan["modules_to_disable"]),
        "will_install_demo": bool(plan.get("demo_project")),
        "plan": plan,
    }


async def apply_pack(
    slug: str,
    *,
    confirm_disables: bool = False,
    install_demo: bool = True,
    actor: str | None = None,
    app: FastAPI | None = None,
) -> dict[str, Any]:
    """Apply a pack: enable modules, record defaults, co-brand. Idempotent.

    When ``install_demo`` is true (default) and the pack maps to a flagship
    country demo project, that project is also installed so the workspace
    immediately reflects the partner's region, currency and classification with
    realistic data. This is the same project the first-boot ``OE_PARTNER_PACK``
    auto-install seeds (see ``app/main.py``); doing it here makes the in-app
    "Apply pack" action self-contained instead of env-only. The install is
    idempotent (``install_demo_project`` dedupes by ``demo_id``) and fail-soft
    (a demo error never aborts the apply).

    Raises:
        ValueError: If the pack is not installed.
        UnknownRuleSetError: If the pack declares a validation rule set the
            engine does not register. Nothing is applied in that case: a pack
            whose rules would silently not run is not a pack we install.
        PackStateWriteError: If the applied-pack record could not be written.
            The modules this call enabled stay enabled - enabling is additive
            and safe - but the pack is NOT active, so this must not come back
            as ``applied: True``. It used to: the write was logged and
            swallowed, and a full data disk turned "apply" into a report with
            no installation behind it.
    """
    m = get_pack_by_slug(slug)
    if not m:
        raise ValueError(f"Pack '{slug}' is not installed")

    plan = _plan(m)
    effects: dict[str, Any] = {"modules_enabled": [], "modules_disabled": [], "modules_failed": []}

    # Enable the pack's default modules (additive - always safe).
    for name in plan["modules_to_enable"]:
        try:
            if app is not None:
                await module_loader.enable_module(name, app)
            effects["modules_enabled"].append(name)
        except Exception as exc:  # noqa: BLE001 - keep applying the rest
            effects["modules_failed"].append({"name": name, "action": "enable", "error": str(exc)})

    # Disable hidden modules only when explicitly confirmed.
    skipped_disables: list[str] = []
    if confirm_disables:
        for name in plan["modules_to_disable"]:
            try:
                if app is not None:
                    await module_loader.disable_module(name, app)
                effects["modules_disabled"].append(name)
            except Exception as exc:  # noqa: BLE001 - e.g. core module / dependents
                effects["modules_failed"].append({"name": name, "action": "disable", "error": str(exc)})
    else:
        skipped_disables = list(plan["modules_to_disable"])

    # Install the pack's flagship country demo project (idempotent, fail-soft).
    # Independent session so a demo failure never rolls back the module changes.
    if install_demo:
        try:
            from app.core.demo_projects import PACK_DEMO_PROJECT, install_demo_project
            from app.database import async_session_factory

            demo_id = PACK_DEMO_PROJECT.get(m.slug)
            if demo_id:
                async with async_session_factory() as demo_session:
                    demo_res = await install_demo_project(demo_session, demo_id, partner_pack=m.slug)
                    # Activate the pack's estimating methodology on the demo
                    # project in the same transaction so it opens with the
                    # partner's cascade (bases + markup steps), not the flat
                    # international default. Builtin template slug only; an
                    # unknown slug is skipped with a warning. Fail-soft.
                    _meth_effect = await _activate_pack_methodology(demo_session, m, demo_res.get("project_id"))
                    if _meth_effect:
                        effects["methodology"] = _meth_effect
                    await demo_session.commit()
                effects["demo_project"] = {
                    "demo_id": demo_id,
                    "project_id": demo_res.get("project_id"),
                    "project_name": demo_res.get("project_name"),
                    "already_installed": bool(demo_res.get("already_installed")),
                }
                logger.info(
                    "Partner-pack apply: demo project '%s' %s for pack %s",
                    demo_id,
                    "already present" if demo_res.get("already_installed") else "installed",
                    m.slug,
                )

                # Run the rich per-module enrichment (photos, takeoff, clash,
                # carbon, qms, variations, costmodel, moc, markups, catalog, BIM
                # grouping) over the freshly installed project. Without this an
                # in-app pack apply opens with those modules empty, since
                # install_demo_project only seeds BOQ / budget / schedule /
                # tender / BIM model / PDFs. Fail-soft: enrichment errors never
                # abort the apply, and each seeder isolates itself per session.
                try:
                    from app.core.demo_enrichment import enrich_projects

                    _pid_raw = demo_res.get("project_id")
                    if _pid_raw:
                        _pid = _pid_raw if isinstance(_pid_raw, uuid.UUID) else uuid.UUID(str(_pid_raw))
                        await enrich_projects([_pid])
                except Exception as enrich_exc:  # noqa: BLE001 - enrichment never aborts apply
                    logger.warning("Partner-pack apply: demo enrichment failed: %s", enrich_exc)
        except Exception as exc:  # noqa: BLE001 - a demo failure must not abort the apply
            effects["demo_project_failed"] = {"error": str(exc)}
            logger.warning("Partner-pack apply: demo project install failed: %s", exc)

    state = AppliedPackState(
        slug=m.slug,
        pack_version=m.pack_version,
        manifest_snapshot=m.to_public_dict(),
        effects=effects,
        applied_by=actor,
    )
    save_applied_state(state)
    # Make co-branding / locale / active-pack resolution take effect immediately.
    reset_cache()

    logger.info("Partner pack applied: %s v%s by %s", m.slug, m.pack_version, actor or "system")
    return {
        "applied": True,
        "slug": m.slug,
        "pack_version": m.pack_version,
        "effects": effects,
        "skipped_disables": skipped_disables,
        "warnings": plan["warnings"],
        "plan": plan,
    }


async def _activate_pack_methodology(
    session: Any, m: PartnerPackManifest, project_id_raw: Any
) -> dict[str, Any] | None:
    """Set the pack's ``default_methodology`` as a project's active methodology.

    Writes ``metadata_['methodology_slug']`` directly (the same pointer
    :func:`app.modules.methodology.service.set_active_methodology` maintains) on
    the given project inside the caller's transaction, so a ``commit`` by the
    caller persists it atomically with the demo install. Only a known built-in
    template slug is honoured; an unknown slug is logged and skipped. Returns an
    effect dict ``{"slug", "project_id"}`` or ``None`` when nothing was set.
    Fully fail-soft: any error is swallowed so methodology never aborts an apply.
    """
    meth_slug = getattr(m, "default_methodology", None)
    if not meth_slug or not project_id_raw:
        return None
    try:
        # Pure data module (no DB/Pydantic/FastAPI import) - safe and cheap.
        from app.modules.methodology.templates import TEMPLATES_BY_SLUG

        if meth_slug not in TEMPLATES_BY_SLUG:
            logger.warning(
                "Pack %s default_methodology '%s' is not a known template; skipped",
                m.slug,
                meth_slug,
            )
            return None
        from app.modules.projects.models import Project

        pid = project_id_raw if isinstance(project_id_raw, uuid.UUID) else uuid.UUID(str(project_id_raw))
        proj = await session.get(Project, pid)
        if proj is None:
            return None
        md = dict(proj.metadata_ or {})
        md["methodology_slug"] = meth_slug
        proj.metadata_ = md
        logger.info("Partner-pack apply: methodology '%s' activated on demo project %s", meth_slug, pid)
        return {"slug": meth_slug, "project_id": str(pid)}
    except Exception as exc:  # noqa: BLE001 - methodology never aborts an apply
        logger.warning("Partner-pack apply: methodology activation failed: %s", exc)
        return None


async def _untag_pack_projects(slug: str) -> int:
    """Release every project scoped to ``slug`` back into the general pool.

    Activation tags the pack's demo projects (and any project created while the
    pack is active) with ``metadata_["partner_pack"] = slug`` so the workspace
    shows only that pack's projects. Deactivation removes the tag so the
    projects become visible again under the normal (un-scoped) listing. The
    projects themselves are never deleted - only un-associated from the pack.

    Runs in its own session and is fail-soft: a failure is logged and reported
    as ``0`` untagged so it never aborts the rest of the un-apply.
    """
    try:
        from sqlalchemy import select

        from app.database import async_session_factory
        from app.modules.projects.models import Project

        untagged = 0
        async with async_session_factory() as session:
            rows = (
                (await session.execute(select(Project).where(Project.metadata_["partner_pack"].as_string() == slug)))
                .scalars()
                .all()
            )
            for proj in rows:
                md = dict(proj.metadata_ or {})
                if md.pop("partner_pack", None) is not None:
                    proj.metadata_ = md
                    untagged += 1
            if untagged:
                await session.commit()
        return untagged
    except Exception as exc:  # noqa: BLE001 - un-tagging must never abort un-apply
        logger.warning("Un-apply: could not untag projects for pack '%s': %s", slug, exc)
        return 0


async def unapply(*, app: FastAPI | None = None) -> dict[str, Any]:
    """Reverse an apply: restore modules, release scoped projects, drop co-branding."""
    state = load_applied_state()
    if not state:
        return {"applied": False, "restored_modules": [], "untagged_projects": 0}

    restored: list[str] = []
    # Re-enable anything the apply disabled. We do NOT disable modules the apply
    # enabled - enabling is additive and the user may now depend on them.
    for name in state.effects.get("modules_disabled", []):
        try:
            if app is not None:
                await module_loader.enable_module(name, app)
            restored.append(name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Un-apply could not restore module '%s': %s", name, exc)

    # Release the pack's scoped projects back to the general workspace.
    untagged = await _untag_pack_projects(state.slug)

    clear_applied_state()
    reset_cache()
    logger.info(
        "Partner pack un-applied (was %s); restored %d module(s), untagged %d project(s)",
        state.slug,
        len(restored),
        untagged,
    )
    return {"applied": False, "restored_modules": restored, "untagged_projects": untagged}


def get_applied_info() -> dict[str, Any]:
    """Current applied-pack status + whether an update is available."""
    state = load_applied_state()
    if not state:
        env = os.environ.get("OE_PARTNER_PACK", "").strip()
        return {
            "applied": bool(env),
            "source": "env" if env else None,
            "slug": env or None,
        }
    current = get_pack_by_slug(state.slug)
    return {
        "applied": True,
        "source": "in-app",
        "slug": state.slug,
        "pack_version": state.pack_version,
        "applied_at": state.applied_at,
        "applied_by": state.applied_by,
        "installed": current is not None,
        "available_version": current.pack_version if current else None,
        "update_available": bool(current and current.pack_version != state.pack_version),
    }
