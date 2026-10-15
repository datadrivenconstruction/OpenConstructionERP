# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo delivery model for the demo estate, run by ``app.core.demo_enrichment``.

Each demo project gets the catalogue its country (or the active pack) resolves
to and the decision an owner would actually work through: three forms of that
catalogue compared on its default scores, the leading form proposed with a
rationale, the allocation matrix confirmed from the catalogue defaults with one
reasoned deviation (ground conditions shared on a geotechnical baseline), three
risks seeded into the register, the package plan of the leading form derived
and linked to the project's first contract when there is one, and two
owner-furnished items, each with its procurement route.

Nothing here assumes a form, a risk category or a party the pinned catalogue
may lack: the forms compared are taken from the catalogue, and a step whose
codes are missing is left out.

The decision is proposed last, so its record carries the matrix and the plan,
and it stays ``proposed``: approval happens at the governance gate, or by hand
on a project without gates, never in a seeder. A project that cannot take a
proposal (it uses gates and its governance model names no frame document for
the decision, or its catalogue has fewer than two forms) gets everything but
the proposal, and the result says so: ``ok`` is false and ``no_decision``
lists the project with the reason, so an integration seed can fail on it. A
project without a governance model uses no gates and takes the proposal like
any other.

Dates. A project still before the gate that starts construction (read through
the governance port, never from a catalogue id or a name) is told as a
pre-construction story: nothing delivered, owner-furnished items needed after
the start of construction, the main package needed at award. Any other project
keeps the running-project story. Offsets are days from the seed day.

The plant register seeds after this module, because its routes read the
package plan. So the one demo item that both lists hold comes in a second
step, :func:`link_demo_plant_items`, which the demo run calls after the plant
register has seeded: it has the register record that the owner supplies one of
its plant items, and the register asks this module for the owner-furnished
item. The link is never written from here, so the two lists cannot disagree.
Without the register, or where the register refuses, nothing is linked. The
two items seeded here stay unlinked and show their own figures.

A demo project of the active pack may bring its own story (``demo_module_story``)
that replaces, key by key, the preferred forms, the rationales, the owner capability,
the seeded risk categories, the ground-conditions rationale, the two owner-furnished
items, the plant item the owner supplies and the award and start offsets. A key that
is absent or malformed keeps its default, said at info; whether a form or a risk
category exists is still asked of the pinned catalogue.

Only projects carrying the demo marker are touched; a project whose model
already compares forms is skipped, so a re-run never duplicates. A model that
is pinned and still empty is filled on the catalogue it pins. Runs after the governance,
contracts and risk seeders, whose rows it reads and links.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Preferred forms to compare, where the pinned catalogue has them; topped up from the catalogue's own order.
DEMO_FORMS = ("design_bid_build_single", "design_build", "cm_at_risk")
COMPARED = 3
CHOSEN = "design_build"
SEEDED_RISKS = ("design_errors", "ground_conditions", "price_escalation")

# Milestones of the pre-construction story, in days from the seed day (the shared demo timeline).
AWARD = 165
START = 190

# The demo plant item the owner supplies (the register's seed code): medium voltage switchgear, still
# before its order when the register has seeded, so its route can be set.
DEMO_PLANT_ITEM = "PL-002"
DEMO_PLANT_ROUTE = "framework"

OWNER_CAPABILITY: dict[str, Any] = {
    "owner_has_design_team": False,
    "owner_has_cm_capacity": False,
    "public_client": False,
    "funding_source": "equity and bank loan",
}
GROUND_RATIONALE = "Shared on a geotechnical baseline report: the owner carries ground worse than the baseline."

# The two owner-furnished items: (code, description, kind, installed by, lead time days, route).
OFI_FIRST: dict[str, Any] = {
    "description": "Main low-voltage switchboard and transformer, owner's framework supplier",
    "item_kind": "equipment",
    "lead_time_days": 90,
}
OFI_SECOND: dict[str, Any] = {
    "description": "Reception furniture from the owner's existing stock, installed by the owner",
    "item_kind": "material",
}
_OFI_KINDS = frozenset({"equipment", "material", "design", "service", "utility"})

RATIONALE_CHOSEN = (
    "Design and build scores highest: the owner has no in-house design team, wants one point of "
    "responsibility and a fixed price at award, and accepts less control over design detail."
)
RATIONALE_LEADING = (
    "This form scores highest on the owner's weighted criteria. The comparison, the risk allocation "
    "and the package plan it leads to are part of this record."
)


def _text(value: Any, locale: str) -> str | None:
    """A non-empty string out of a plain string or a language map, else None."""
    from app.modules.project_governance.public import story_text

    out = story_text(value, locale)
    return out if isinstance(out, str) and out.strip() else None


def _ofi_from_story(raw: Any, locale: str, *, lead: bool) -> dict[str, Any] | None:
    """One owner-furnished item of a story: description, kind and (for the first) a lead time."""
    if not isinstance(raw, dict):
        return None
    description = _text(raw.get("description"), locale)
    if description is None or raw.get("item_kind") not in _OFI_KINDS:
        return None
    out: dict[str, Any] = {"description": description, "item_kind": raw["item_kind"]}
    if lead:
        days = raw.get("lead_time_days")
        if not (isinstance(days, int) and not isinstance(days, bool) and days > 0):
            return None
        out["lead_time_days"] = days
    return out


_CONTRACT_GROUPS = ("contract_form", "land_tenure", "utility_contract", "user_agreement", "partner_structure")
_CONTRACT_STATUS = ("draft", "negotiating", "agreed", "signed", "terminated")

# English defaults for a demo project whose pack brings no story: (group, preferred kinds in order, code, title,
# counterparty, status, days from the seed day to the start, share). A story replaces the whole list.
DEMO_CONTRACT_ITEMS: tuple[dict[str, Any], ...] = (
    {
        "group": "contract_form",
        "kinds": ["design_build_contract", "construction_contract"],
        "code": "CF-01",
        "title": "Main works contract, lump sum at award",
        "counterparty": "General contractor, to be awarded",
        "status": "negotiating",
        "days": AWARD,
    },
    {
        "group": "land_tenure",
        "kinds": ["leasehold", "purchase"],
        "code": "LT-01",
        "title": "Site held on a long leasehold from the municipality",
        "counterparty": "Municipality",
        "status": "signed",
        "days": -120,
    },
    {
        "group": "utility_contract",
        "kinds": ["power_connection", "water_sewer_connection"],
        "code": "UC-01",
        "title": "Medium voltage connection of the new building",
        "counterparty": "Regional grid operator",
        "status": "agreed",
        "days": 30,
    },
    {
        "group": "user_agreement",
        "kinds": ["lease_to_user", "service_level_agreement"],
        "code": "UA-01",
        "title": "Lease with the future operator, handover criteria attached",
        "counterparty": "Future operator",
        "status": "draft",
        "days": START,
    },
    {
        "group": "partner_structure",
        "kinds": ["project_company", "joint_venture"],
        "code": "PS-01",
        "title": "Owner share of the project company",
        "counterparty": "Owner holding",
        "status": "agreed",
        "days": -90,
        "share": "70",
    },
    {
        "group": "partner_structure",
        "kinds": ["co_investment", "consortium"],
        "code": "PS-02",
        "title": "Co-investor share of the project company",
        "counterparty": "Co-investor",
        "status": "agreed",
        "days": -90,
        "share": "30",
    },
)


def _contract_items_from_story(raw: Any, locale: str) -> list[dict[str, Any]] | None:
    """The contract-side items of a story; one malformed entry makes the whole list fall back to the default."""
    if not isinstance(raw, list) or not raw:
        return None
    out: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            return None
        title, counterparty = _text(entry.get("title"), locale), _text(entry.get("counterparty"), locale)
        kinds, code, days = entry.get("kinds"), entry.get("code"), entry.get("days")
        share = entry.get("share")
        ok = (
            entry.get("group") in _CONTRACT_GROUPS
            and entry.get("status") in _CONTRACT_STATUS
            and title is not None
            and counterparty is not None
            and isinstance(code, str)
            and code.strip()
            and isinstance(kinds, list)
            and kinds
            and all(isinstance(k, str) for k in kinds)
            and isinstance(days, int)
            and not isinstance(days, bool)
            and (share is None or isinstance(share, str))
        )
        if not ok:
            return None
        item = {**entry, "title": title, "counterparty": counterparty}
        out.append(item)
    return out


def resolve_story(story: dict[str, Any] | None, locale: str = "en") -> dict[str, Any]:
    """The validated overrides of a demo story; a key that is absent or malformed is left out.

    Keys: ``forms`` (preferred form codes), ``rationales`` (form code to text, used for the form
    that leads the comparison), ``owner_capability``, ``risks`` (category codes), ``ground_rationale``,
    ``ofi_first``, ``ofi_second``, ``plant_item`` (code of the register item the owner supplies) and
    ``award_days`` / ``start_days`` and ``scores`` (form code to criterion code to a score from 1 to 5,
    the owner's own assessment where it departs from the catalogue default). Codes of forms, criteria and
    risk categories are checked against the pinned catalogue where they are used, not here.
    """
    out: dict[str, Any] = {}
    if not story:
        return out

    def keep(key: str, value: Any) -> None:
        if value is None:
            logger.info("delivery_model demo story: key %r is malformed, the default is kept", key)
        elif key in story:
            out[key] = value

    def codes(raw: Any) -> list[str] | None:
        ok = isinstance(raw, list) and raw and all(isinstance(c, str) and c.strip() for c in raw)
        return list(raw) if ok else None

    def rationales(raw: Any) -> dict[str, str] | None:
        if not (isinstance(raw, dict) and raw):
            return None
        texts = {k: _text(v, locale) for k, v in raw.items()}
        return None if any(v is None for v in texts.values()) else texts  # type: ignore[return-value]

    def capability(raw: Any) -> dict[str, Any] | None:
        if not (isinstance(raw, dict) and set(raw) <= set(OWNER_CAPABILITY)):
            return None
        out = dict(raw)
        for key, value in raw.items():
            if key == "funding_source":
                text = _text(value, locale)
                if not (text and len(text) <= 120):
                    return None
                out[key] = text
            elif not isinstance(value, bool):
                return None
        return {**OWNER_CAPABILITY, **out}

    def scores(raw: Any) -> dict[str, dict[str, int]] | None:
        ok = (
            isinstance(raw, dict)
            and raw
            and all(
                isinstance(form, str)
                and isinstance(row, dict)
                and row
                and all(
                    isinstance(c, str) and isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 5
                    for c, v in row.items()
                )
                for form, row in raw.items()
            )
        )
        return {form: dict(row) for form, row in raw.items()} if ok else None

    def day(raw: Any) -> int | None:
        return raw if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0 else None

    if "forms" in story:
        keep("forms", codes(story["forms"]))
    if "rationales" in story:
        keep("rationales", rationales(story["rationales"]))
    if "owner_capability" in story:
        keep("owner_capability", capability(story["owner_capability"]))
    if "risks" in story:
        keep("risks", codes(story["risks"]))
    if "ground_rationale" in story:
        keep("ground_rationale", _text(story["ground_rationale"], locale))
    if "ofi_first" in story:
        keep("ofi_first", _ofi_from_story(story["ofi_first"], locale, lead=True))
    if "ofi_second" in story:
        keep("ofi_second", _ofi_from_story(story["ofi_second"], locale, lead=False))
    if "contract_items" in story:
        keep("contract_items", _contract_items_from_story(story["contract_items"], locale))
    if "plant_item" in story:
        value = story["plant_item"]
        keep("plant_item", value if isinstance(value, str) and value.strip() else None)
    if "scores" in story:
        keep("scores", scores(story["scores"]))
    for key in ("award_days", "start_days"):
        if key in story:
            keep(key, day(story[key]))
    return out


def story_score_rows(
    options: dict[str, Any], criteria: Iterable[str], scores: dict[str, dict[str, int]]
) -> list[dict[str, Any]]:
    """The story's scores as rows of ``put_scores``, for the compared forms and the project's criteria only."""
    known = set(criteria)
    rows = []
    for form, row in scores.items():
        if form not in options:
            logger.info("delivery_model demo story: form %r is not compared, its scores are dropped", form)
            continue
        for code, score in row.items():
            if code not in known:
                logger.info("delivery_model demo story: criterion %r is unknown, the score is dropped", code)
                continue
            rows.append({"option_id": options[form], "criterion_code": code, "score": score})
    return rows


def forms_to_compare(available: Iterable[str], preferred: Iterable[str] = DEMO_FORMS) -> list[str]:
    """Up to three forms of the pinned catalogue: the preferred ones it has, then its own order."""
    have = list(available)
    picked = [code for code in preferred if code in have]
    picked += [code for code in have if code not in picked]
    return picked[:COMPARED]


def item_dates(today: date, *, pre_construction: bool, award: int = AWARD, start: int = START) -> dict[str, date]:
    """Dates of the seeded package and items for the story the project is in."""
    if pre_construction:
        return {
            "package_need": today + timedelta(days=award),
            "switchboard_delivery": today + timedelta(days=start + 60),
            "switchboard_need": today + timedelta(days=start + 70),
            "furniture_need": today + timedelta(days=start + 300),
        }
    return {
        "package_need": today + timedelta(days=120),
        "switchboard_delivery": today + timedelta(days=100),
        "switchboard_need": today + timedelta(days=110),
        "furniture_need": today + timedelta(days=200),
    }


async def seed_delivery_model_demo(session: AsyncSession, project_ids: Iterable[uuid.UUID]) -> dict[str, Any]:
    """Seed the delivery model of every demo project in ``project_ids`` that has none. The caller commits.

    Returns counts plus ``no_decision`` (projects seeded without a proposal, with the reason), ``failed``
    (projects whose seed raised and was rolled back) and ``ok`` (both lists empty).
    """
    from app.core.demo_marker import demo_id_of
    from app.modules.delivery_model.models import DeliveryOption
    from app.modules.projects.models import Project

    totals: dict[str, Any] = {
        "projects": 0,
        "packages": 0,
        "risks": 0,
        "ofis": 0,
        "contract_items": 0,
        "decisions": 0,
        "no_decision": [],
        "failed": [],
        "ok": True,
    }
    ids = list(project_ids)
    if not ids:
        return totals
    rows = (await session.execute(select(Project.id, Project.metadata_).where(Project.id.in_(ids)))).all()
    for pid, demo_id in [(pid, demo_id_of(meta)) for pid, meta in rows]:
        if not demo_id:
            continue
        has = (
            await session.execute(select(DeliveryOption.id).where(DeliveryOption.project_id == pid).limit(1))
        ).scalar_one_or_none()
        if has is not None:
            continue
        try:
            async with session.begin_nested():
                counts = await _seed_project(session, pid, await _story_of(session, pid, demo_id))
        except Exception as exc:
            logger.error("delivery_model demo seed failed for %s and was rolled back", pid, exc_info=True)
            totals["failed"].append({"project_id": str(pid), "reason": type(exc).__name__})
            continue
        totals["projects"] += 1
        reason = counts.pop("no_decision_reason")
        if reason:
            totals["no_decision"].append({"project_id": str(pid), "reason": reason})
        for k, v in counts.items():
            totals[k] += v
    totals["ok"] = not totals["failed"] and not totals["no_decision"]
    return totals


async def _story_of(session: AsyncSession, project_id: uuid.UUID, demo_id: str) -> dict[str, Any]:
    """The validated story of this project in its own language, ``{}`` when it has none."""
    from app.modules.project_governance.public import demo_module_story
    from app.modules.projects.models import Project

    project = await session.get(Project, project_id)
    return resolve_story(demo_module_story(demo_id, "delivery_model"), getattr(project, "locale", None) or "en")


async def link_demo_plant_items(session: AsyncSession, project_ids: Iterable[uuid.UUID]) -> dict[str, Any]:
    """Have the plant register record that the owner supplies the demo switchgear; the caller commits.

    Runs after the plant register's demo seed. Per demo project it asks the
    register to set an owner-furnished route on :data:`DEMO_PLANT_ITEM`, with
    the package that builds as installer; the register then asks this module
    for the owner-furnished item, which is how the link comes to exist. The
    item gets a procurement route like every seeded item.

    Nothing is asked that is known to be refused: a project is skipped, at
    info, when there is no register, no such plant item, the item is ordered
    or cancelled (its route is frozen), or it is already owner-furnished.
    Returns ``{"linked": n, "skipped": [{project_id, reason}]}``.
    """
    from app.core.demo_marker import demo_id_of
    from app.modules.delivery_model.repository import DeliveryModelRepository
    from app.modules.delivery_model.service import DeliveryModelService
    from app.modules.projects.models import Project

    out: dict[str, Any] = {"linked": 0, "skipped": []}
    ids = list(project_ids)
    if not ids:
        return out
    rows = (
        await session.execute(select(Project.id, Project.owner_id, Project.metadata_).where(Project.id.in_(ids)))
    ).all()
    for pid, owner, meta in rows:
        if not demo_id_of(meta):
            continue
        story = await _story_of(session, pid, demo_id_of(meta) or "")
        reason = await _link_demo_plant_item(session, pid, owner, story.get("plant_item", DEMO_PLANT_ITEM))
        if reason is None:
            item = next(i for i in await DeliveryModelRepository(session).ofis(pid) if i.plant_item_id is not None)
            if item.procurement_route == "none_yet":
                await DeliveryModelService(session).set_ofi_route(
                    pid, item.id, route=DEMO_PLANT_ROUTE, link_kind=None, link_id=None, actor_id=owner
                )
            out["linked"] += 1
        else:
            logger.info("delivery_model demo: plant item not linked for project %s (%s)", pid, reason)
            out["skipped"].append({"project_id": str(pid), "reason": reason})
    return out


async def _link_demo_plant_item(
    session: AsyncSession, project_id: uuid.UUID, owner: uuid.UUID, item_code: str = DEMO_PLANT_ITEM
) -> str | None:
    """``None`` when the register recorded the owner-furnished route, else why nothing was asked or done."""
    from app.modules.delivery_model import plant
    from app.modules.delivery_model.repository import DeliveryModelRepository

    if not plant.installed():
        return "plant_register_unavailable"
    repo = DeliveryModelRepository(session)
    if await repo.get_model(project_id) is None:
        return "delivery_model_missing"
    plant_item_id = await plant.plant_item_id_by_code(session, project_id, item_code)
    dates = await plant.plant_item_dates(session, project_id, plant_item_id) if plant_item_id is not None else None
    if dates is None:
        return "plant_item_missing"
    if plant.keeps_owner_furnished_item(dates):
        return "already_owner_furnished"
    if not plant.route_open(dates):
        return "plant_item_route_frozen"
    # The package that builds installs what the owner supplies; without one the owner installs.
    installer = next((p.id for p in await repo.packages(project_id) if p.builds and p.status != "cancelled"), None)
    return await plant.set_owner_furnished_route(
        session, project_id, plant_item_id, installer_package_id=installer, actor_id=owner
    )


async def _seed_contract_items(
    svc: Any,
    project_id: uuid.UUID,
    catalogue: Any,
    package: Any,
    today: date,
    actor: Any,
    items: Iterable[dict[str, Any]],
) -> int:
    """The contract-side items of the demo project; the pinned catalogue decides which kinds exist."""
    model = await svc.require_model(project_id)
    form = catalogue.form(model.selected_form_code) if model.selected_form_code else None
    made = 0
    for spec in items:
        group = spec["group"]
        kind = next((k for k in spec["kinds"] if catalogue.contract_kind(group, k) is not None), None)
        if kind is None:
            continue
        data: dict[str, Any] = {
            "code": spec["code"],
            "group_code": group,
            "kind_code": kind,
            "title": spec["title"],
            "counterparty": spec["counterparty"],
            "status": spec["status"],
            "start_date": (today + timedelta(days=spec["days"])).isoformat(),
        }
        if group == "contract_form":
            data["package_id"] = package.id if package else None
            data["price_basis"] = form.price_basis_at_award if form else "lump_sum"
        if spec.get("share") is not None:
            data["share_percent"] = spec["share"]
        await svc.create_contract_item(project_id, data, actor)
        made += 1
    return made


async def _seed_project(
    session: AsyncSession, project_id: uuid.UUID, story: dict[str, Any] | None = None
) -> dict[str, Any]:
    from app.modules.contracts.models import Contract
    from app.modules.delivery_model import hosting
    from app.modules.delivery_model.service import DeliveryModelService
    from app.modules.projects.models import Project

    story = story or {}
    project = await session.get(Project, project_id)
    actor = project.owner_id
    locale = getattr(project, "locale", None) or "en"
    svc = DeliveryModelService(session)
    model = await svc.get_model(project_id) or await svc.set_model(project_id, actor_id=actor, tenant_id=None)
    catalogue = await svc.catalogue_for(model)
    options = {}
    for code in forms_to_compare((f.code for f in catalogue.forms), story.get("forms", DEMO_FORMS)):
        row = await svc.add_option(project_id, code, overrides={}, notes="", actor_id=actor)
        options[code] = row.id
    await svc.prefill_scores(project_id, actor)
    if story.get("scores"):
        criteria = [c.code for c in await svc.repo.criteria(project_id)]
        rows = story_score_rows(options, criteria, story["scores"])
        if rows:
            await svc.put_scores(project_id, rows, actor)
    await svc.patch_model(
        project_id,
        actor_id=actor,
        owner_capability=story.get("owner_capability", OWNER_CAPABILITY),
    )
    # Before a proposal the matrix and the plan follow the form leading the comparison, whichever it is.
    leading = await svc._leading_form(project_id)
    await svc.confirm_allocations(project_id, None, actor)
    parties = {p.code for p in catalogue.parties}
    if catalogue.category("ground_conditions") is not None and {"shared", "owner", "contractor"} <= parties:
        await svc.put_allocation(
            project_id,
            "ground_conditions",
            {
                "party": "shared",
                "basis": "ground_baseline",
                "shares": {"owner": "60", "contractor": "40"},
                "rationale": story.get("ground_rationale", GROUND_RATIONALE),
            },
            actor,
        )
        await svc.confirm_allocations(project_id, ["ground_conditions"], actor)
    seeded = [code for code in story.get("risks", SEEDED_RISKS) if catalogue.category(code) is not None]
    risks = await svc.seed_risks(project_id, seeded, preview=False, actor_id=actor, locale=locale) if seeded else []
    packages = await svc.derive_packages(project_id, actor, locale=locale) if leading else []
    contract_id = (
        await session.execute(
            select(Contract.id).where(Contract.project_id == project_id).order_by(Contract.created_at).limit(1)
        )
    ).scalar_one_or_none()
    db = next((p for p in packages if p.kind == "design_and_construction"), None)
    if contract_id is not None and db is not None:
        await svc.link_package(project_id, db.id, "contract", contract_id, actor)
    today = datetime.now(UTC).date()
    dates = item_dates(
        today,
        pre_construction=await hosting.construction_not_released(session, project_id),
        award=story.get("award_days", AWARD),
        start=story.get("start_days", START),
    )
    if db is not None:
        await svc.update_package(project_id, db.id, {"need_date": dates["package_need"].isoformat()}, actor)
    first = story.get("ofi_first", OFI_FIRST)
    second = story.get("ofi_second", OFI_SECOND)
    # Every item gets a route: where procurement is released from the first phase a missing one is an error.
    switchboard = await svc.create_ofi(
        project_id,
        {
            "code": "OFI-01",
            "description": first["description"],
            "item_kind": first["item_kind"],
            "install_by": "package" if db else "owner",
            "package_id": db.id if db else None,
            "need_by_date": dates["switchboard_need"].isoformat(),
            "expected_delivery_date": dates["switchboard_delivery"].isoformat(),
            "lead_time_days": first["lead_time_days"],
            "enquiry_date": today.isoformat(),
        },
        actor,
    )
    await svc.set_ofi_route(project_id, switchboard.id, route="framework", link_kind=None, link_id=None, actor_id=actor)
    furniture = await svc.create_ofi(
        project_id,
        {
            "code": "OFI-02",
            "description": second["description"],
            "item_kind": second["item_kind"],
            "install_by": "owner",
            "need_by_date": dates["furniture_need"].isoformat(),
        },
        actor,
    )
    await svc.set_ofi_route(
        project_id, furniture.id, route="existing_stock", link_kind=None, link_id=None, actor_id=actor
    )
    contract_items = await _seed_contract_items(
        svc, project_id, catalogue, db, today, actor, story.get("contract_items", DEMO_CONTRACT_ITEMS)
    )
    # Proposed last, so the decision record carries the allocations and the package plan it was made with.
    decisions, reason = 0, ""
    if leading is None or len(options) < 2:
        reason = "too_few_forms"
    else:
        # Asked first, not tried: a project that uses gates and has no frame document for the decision
        # would refuse the proposal.
        blocked = (await svc._action_blocks(await svc.require_model(project_id)))["propose"]
        if blocked in (hosting.NO_CARRIER, hosting.NO_GOVERNANCE_MODEL):
            reason = blocked
        else:
            await svc.propose(
                project_id,
                option_id=options[leading],
                rationale=story.get("rationales", {}).get(leading)
                or (RATIONALE_CHOSEN if leading == CHOSEN else RATIONALE_LEADING),
                owner_capability=None,
                dispositions={},
                actor_id=actor,
            )
            decisions = 1
    if reason:
        # Loud on purpose: a demo project without a proposed decision shows an empty decision screen.
        logger.error("delivery_model demo: no decision proposed for project %s (%s)", project_id, reason)
    return {
        "packages": len(packages),
        "risks": len([r for r in risks if r.get("risk_id")]),
        "ofis": 2,
        "contract_items": contract_items,
        "decisions": decisions,
        "no_decision_reason": reason,
    }
