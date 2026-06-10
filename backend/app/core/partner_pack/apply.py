"""Apply / update / un-apply a partner pack onto the running installation.

Design decisions (confirmed with the product owner 2026-05-29):
  * Scope is a single global active pack (single-tenant).
  * Enabling the pack's ``default_modules`` is automatic (additive, safe).
  * Disabling the pack's ``hidden_modules`` happens ONLY with explicit
    ``confirm_disables`` - never silently turn off work-in-progress.
  * ``validation_rule_packs`` that match a built-in rule set are reported as
    active; the rest are flagged documentation-only (the pack JSON files are
    not executed by the engine - see the partner-pack ADR).
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
    """Built-in validation rule-set identifiers, best-effort."""
    try:
        from app.core.validation.engine import rule_registry

        return set(rule_registry.list_rule_sets().keys())
    except Exception:  # noqa: BLE001 - validation engine optional at this layer
        return set()


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


def _plan(m: PartnerPackManifest) -> dict[str, Any]:
    """Compute the field-by-field effect plan for applying pack ``m`` (no mutation)."""
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
    if m.default_currency:
        warnings.append(
            f"Default currency {m.default_currency} applies to NEW projects only; existing projects keep their currency."
        )
    if m.default_tax_template:
        warnings.append(
            f"Default tax template '{m.default_tax_template}' is recorded for reference (no automatic tax resolver yet)."
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
        "cwicr_regions": list(m.cwicr_regions or []),
        "default_tax_template": m.default_tax_template,
        "demo_project": _pack_demo_info(m.slug),
        "warnings": warnings,
    }


def build_preview(slug: str) -> dict[str, Any]:
    """Dry-run: what would applying this pack change? Raises ValueError if unknown."""
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

    Raises ValueError if the pack is not installed.
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
