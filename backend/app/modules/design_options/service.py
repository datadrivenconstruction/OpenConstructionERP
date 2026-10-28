# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Design Options service - attach-model and per-option BOQ/cost orchestration.

Business logic for building and pricing alternative design options. Each option
is paired with its OWN bill of quantities so a full set of options can be
compared side by side without one option's numbers bleeding into another's.

The generate flow is the heart of this module and is deliberately assembled from
existing platform services rather than re-implemented:

* the BIM hub owns CAD upload and conversion (this module only links the
  resulting model to an option);
* element matching owns turning a model into confirmed, priced groups
  (this module runs a match session scoped to the option's model, previews it,
  and on confirm applies it into the option's own BOQ via
  ``target_boq_id``);
* the BOQ editor owns the FX-correct money rollup and markups
  (this module totals the option's BOQ through it).

Money, quantity and ratio values are Decimal in Python and are stored on the
option as plain decimal strings (the platform Decimal-as-string contract); no
float ever reaches the option row or the wire. Currencies are never blended: the
rollup runs through the BOQ module's currency-aware totalling, and a mixed
currency BOQ is surfaced as a warning rather than summed blindly.

AI-augmented, human-confirmed: ``generate`` exposes a ``dry_run`` preview that
runs the match and returns the would-be positions and totals WITHOUT writing
anything. Only a non-dry-run call applies the matches and prices the option.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.design_options.models import DesignOption, DesignOptionSet
from app.modules.design_options.repository import DesignOptionsRepository
from app.modules.design_options.schemas import (
    AttachModelRequest,
    DesignOptionCreate,
    DesignOptionGeneratePreviewLine,
    DesignOptionGenerateRequest,
    DesignOptionGenerateResponse,
    DesignOptionLinkRequest,
    DesignOptionSetCreate,
)

logger = logging.getLogger(__name__)

_CENTS = Decimal("0.01")
_VALID_METHODS = ("vector", "lexical", "resources", "llm")

# DIN 276 top-level cost groups (stable key -> default English label). The
# frontend localises the label via t('designOptions.trade.<key>'); the backend
# only stores a stable key and an honest English default, mirroring how the
# conceptual-estimate module keeps ELEMENT_LABELS.
_DIN276_GROUPS: dict[str, str] = {
    "100": "Land",
    "200": "Preparatory measures",
    "300": "Building construction",
    "400": "Building services",
    "500": "External works",
    "600": "Furnishings",
    "700": "Ancillary costs",
    "800": "Financing",
}

# Division scope descriptions (common subset; unknown divisions fall back
# to a "Division NN" label so nothing is dropped). Numbers are
# interoperability facts; the wording is our own and matches
# us_pack/config.py - the proprietary division titles must never be
# bundled (licensing denylist).
_MASTERFORMAT_DIVISIONS: dict[str, str] = {
    "00": "Bidding and contract-formation documents",
    "01": "General project requirements and temporary provisions",
    "02": "Demolition, site assessment and existing structures",
    "03": "Cast-in-place and precast concrete work",
    "04": "Brick, block and stone work",
    "05": "Structural and miscellaneous metal work",
    "06": "Carpentry, millwork and composite framing",
    "07": "Roofing, waterproofing and insulation",
    "08": "Doors, windows and glazed assemblies",
    "09": "Interior finishing: drywall, flooring, painting",
    "10": "Built-in specialty items and signage",
    "11": "Fixed building equipment",
    "12": "Furniture, casework and window treatments",
    "13": "Pre-engineered and special-purpose structures",
    "14": "Elevators, escalators and lifts",
    "21": "Sprinkler and fire-suppression systems",
    "22": "Piping systems and sanitary fixtures",
    "23": "Heating, cooling and ventilation systems",
    "25": "Building automation and controls integration",
    "26": "Power distribution and lighting systems",
    "27": "Voice, data and network cabling",
    "28": "Fire alarm, access control and surveillance",
    "31": "Excavation, grading and earth support",
    "32": "Paving, landscaping and site amenities",
    "33": "Site water, sewer, storm and power services",
    "34": "Rail, transit and transportation infrastructure",
    "35": "Marine, dredging and waterfront work",
}


# ── Decimal helpers (Decimal-as-string contract) ─────────────────────────────


def _parse_decimal(value: object) -> Decimal:
    """Parse an arbitrary value into a finite Decimal, never raising."""
    try:
        if value is None or value == "":
            return Decimal("0")
        parsed = Decimal(str(value))
        return parsed if parsed.is_finite() else Decimal("0")
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _parse_iso_date(value: object) -> date | None:
    """Parse a stored schedule date into a ``date``, or ``None`` when unusable.

    Schedule dates are stored as free-form strings, so they arrive as plain
    ``YYYY-MM-DD`` from one importer and as a full ISO timestamp from another.
    Both read as the same day here; anything else is treated as absent rather
    than guessed at, because a misread date silently moves a completion.
    """
    # datetime is a subclass of date, and mixing the two blows up on comparison,
    # so narrow it first rather than letting one through as if it were a day.
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _money_str(value: object) -> str:
    """Render a value as a plain decimal string, guarding non-finite values."""
    dec = value if isinstance(value, Decimal) else _parse_decimal(value)
    if not dec.is_finite():
        return "0"
    return format(dec, "f")


def _cents(value: Decimal) -> Decimal:
    """Quantise a Decimal to two places, half-up (money precision)."""
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _slug(text: str) -> str:
    """Filesystem/JSON-safe stable key from a free-form label."""
    lowered = "".join(ch.lower() if ch.isalnum() else "-" for ch in (text or "").strip())
    parts = [p for p in lowered.split("-") if p]
    return "-".join(parts) or "unclassified"


def _classify_bucket(classification: object, preferred: str) -> tuple[str, str, str]:
    """Map a position classification to a (key, label, system) trade bucket.

    Tries the project's preferred classification standard first, then the other
    supported standards, then a free-form ``trade`` tag, so a project set up for
    DIN 276 still buckets a MasterFormat-coded line sensibly. An unclassified
    line lands in a single ``unclassified`` bucket rather than being dropped.
    """
    codes = classification if isinstance(classification, dict) else {}
    order = [preferred, *[s for s in ("din276", "masterformat", "trade") if s != preferred]]
    for system in order:
        raw = codes.get(system)
        code = str(raw).strip() if raw not in (None, "") else ""
        if not code:
            continue
        if system == "din276":
            first = next((ch for ch in code if ch.isdigit()), "")
            if first and first != "0":
                key = f"{first}00"
                return key, _DIN276_GROUPS.get(key, f"DIN 276 {key}"), "din276"
        elif system == "masterformat":
            digits = "".join(ch for ch in code if ch.isdigit())
            if len(digits) >= 2:
                div = digits[:2]
                return div, _MASTERFORMAT_DIVISIONS.get(div, f"Division {div}"), "masterformat"
        else:  # free-form trade tag
            return _slug(code), code, "trade"
    return "unclassified", "Unclassified", "none"


@dataclass
class _PricedOption:
    """One option's headline figures, rolled up from its own bill of quantities.

    The single result of :meth:`DesignOptionsService._price_from_boq`, shared by
    the two ways an option comes by a bill: generated from the matched model, or
    linked from an estimate the project already held. Both paths persist these
    same fields, so a linked option and a generated one can never drift into
    reporting the same bill two different ways.

    Every money and quantity value is a Decimal here and leaves as a plain
    decimal string; ``currency`` is the project base the BOQ rollup converted to.
    """

    direct: Decimal
    markups: Decimal
    grand: Decimal
    cost_per_m2: Decimal
    gfa: str
    gfa_unit: str
    currency: str
    is_mixed: bool
    position_count: int
    breakdown: list[dict]
    warnings: list[str]

    def as_fields(self, *, boq_source: str) -> dict[str, object]:
        """The option columns these figures write, ready for a repository update."""
        return {
            "direct_cost": _money_str(self.direct),
            "markups_total": _money_str(self.markups),
            "grand_total": _money_str(self.grand),
            "cost_per_m2": _money_str(self.cost_per_m2),
            "gfa": self.gfa,
            "gfa_unit": self.gfa_unit,
            "currency": self.currency,
            "position_count": self.position_count,
            "breakdown": self.breakdown,
            "boq_source": boq_source,
            "status": "priced",
            "error": "",
        }


class DesignOptionsService:
    """Business logic for design-option sets, options and their pricing."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = DesignOptionsRepository(session)

    # ── Sets ─────────────────────────────────────────────────────────────

    async def create_set(
        self,
        data: DesignOptionSetCreate,
        *,
        created_by: uuid.UUID | None,
    ) -> DesignOptionSet:
        """Create a new design-option set for a project."""
        option_set = DesignOptionSet(
            project_id=data.project_id,
            name=data.name,
            comparison_currency=(data.comparison_currency or "").strip().upper(),
            created_by=created_by,
        )
        option_set = await self.repo.create_set(option_set)
        logger.info("Design-option set created: %s (project=%s)", option_set.name, data.project_id)
        # Re-fetch through a query so the selectin ``options`` relationship is
        # eagerly populated for the response (accessing it on the freshly added
        # instance would otherwise trip an async lazy-load).
        return await self.repo.get_set(option_set.id)  # type: ignore[return-value]

    async def get_set(self, set_id: uuid.UUID) -> DesignOptionSet:
        """Get a set by id or raise 404. Access is gated by the router."""
        option_set = await self.repo.get_set(set_id)
        if option_set is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Design-option set not found")
        return option_set

    async def list_sets(self, project_id: uuid.UUID) -> list[DesignOptionSet]:
        """List all sets for a project (newest first)."""
        return await self.repo.list_sets(project_id)

    async def set_baseline(self, option_set: DesignOptionSet, option_id: uuid.UUID) -> DesignOptionSet:
        """Mark one option in the set as the baseline for delta comparison."""
        option = await self.repo.get_option(option_id)
        if option is None or option.set_id != option_set.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Option not found in this set")
        await self.repo.update_set_fields(option_set.id, baseline_option_id=option.id)
        await self.session.flush()
        logger.info("Design-option baseline set: set=%s option=%s", option_set.id, option_id)
        return await self.get_set(option_set.id)

    async def delete_set(self, option_set: DesignOptionSet) -> None:
        """Hard-delete a set and, by cascade, all of its options."""
        await self.repo.delete_set(option_set.id)
        logger.info("Design-option set deleted: %s", option_set.id)

    # ── Options ──────────────────────────────────────────────────────────

    async def create_option(self, option_set: DesignOptionSet, data: DesignOptionCreate) -> DesignOption:
        """Create a new empty option inside a set (draft status)."""
        option = DesignOption(
            set_id=option_set.id,
            project_id=option_set.project_id,
            name=data.name,
            sort_order=await self.repo.next_sort_order(option_set.id),
        )
        option = await self.repo.create_option(option)
        logger.info("Design option created: %s (set=%s)", option.name, option_set.id)
        return option

    async def get_option(self, option_id: uuid.UUID) -> DesignOption:
        """Get an option by id or raise 404. Access is gated by the router."""
        option = await self.repo.get_option(option_id)
        if option is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Design option not found")
        return option

    async def delete_option(self, option: DesignOption) -> None:
        """Hard-delete a single option, clearing it as the set's baseline.

        ``baseline_option_id`` is a soft pointer with no foreign key, so nothing
        in the database clears it when the option it names goes away. Left
        dangling it is worse than absent: the comparison finds no baseline
        column and reports every delta as zero, while the fairness banner
        withholds its "no baseline chosen" notice because the id is not null.
        """
        set_id = option.set_id
        option_id = option.id
        await self.repo.delete_option(option_id)
        option_set = await self.repo.get_set(set_id)
        if option_set is not None and option_set.baseline_option_id == option_id:
            await self.repo.update_set_fields(set_id, baseline_option_id=None)
            await self.session.flush()
            logger.info("Design-option baseline cleared: set=%s (baseline option deleted)", set_id)
        logger.info("Design option deleted: %s", option_id)

    @staticmethod
    def _match_session_reset(option: DesignOption, new_model_id: uuid.UUID | None) -> dict[str, object]:
        """Fields that drop a match session scoped to a model being replaced.

        ``match_session_id`` names a match run created from one specific model,
        and ``generate`` reuses it whenever it is set. Carrying it across a
        re-source would match, confirm and price the superseded design under
        the new model's name - the same failure as a stale ``bim_model_id``,
        one field over and invisible in the option's own row. Re-attaching the
        model already in place is not a change, so the session survives that.

        Args:
            option: The option as it stands before the attach is applied.
            new_model_id: The model it is about to point at, ``None`` when the
                option is going back to awaiting conversion.

        Returns:
            The fields to merge into the update, empty when nothing changed.
        """
        if option.match_session_id is None or option.bim_model_id == new_model_id:
            return {}
        return {"match_session_id": None}

    async def attach_model(self, option: DesignOption, data: AttachModelRequest) -> DesignOption:
        """Pair an option with a converted BIM model or an existing document.

        Exactly one of ``bim_model_id`` / ``source_document_id`` must be given.
        The BIM hub owns the CAD upload + conversion pipeline (its upload-cad /
        upload / from-document endpoints); this method never re-implements that.
        It links an already-converted model, or records a document to convert,
        applying a cross-project IDOR guard on whatever it links.
        """
        has_model = data.bim_model_id is not None
        has_doc = data.source_document_id is not None
        if has_model == has_doc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Provide exactly one of bim_model_id or source_document_id.",
            )

        if has_model:
            from app.modules.bim_hub.models import BIMModel

            model = await self.session.get(BIMModel, data.bim_model_id)
            # Cross-project guard: a model from another project must read as 404
            # (not 403) so option ids cannot be used to probe foreign models.
            if model is None or model.project_id != option.project_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BIM model not found")
            meta = dict(option.metadata_ or {})
            meta["attached_model_format"] = getattr(model, "model_format", "") or ""
            meta["attached_element_count"] = int(getattr(model, "element_count", 0) or 0)
            await self.repo.update_option_fields(
                option.id,
                bim_model_id=model.id,
                source_document_id=None,
                status="model_attached",
                error="",
                metadata_=meta,
                **self._match_session_reset(option, model.id),
            )
            logger.info("Design option %s linked to BIM model %s", option.id, model.id)
        else:
            from app.modules.documents.repository import DocumentRepository

            doc = await DocumentRepository(self.session).get_by_id(data.source_document_id)
            if doc is None or doc.project_id != option.project_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

            # Adopt an already-converted model when the BIM hub cross-linked one
            # to this document (its from-document idempotency stamp); otherwise
            # record the document and mark the option as awaiting conversion, so
            # the caller runs the BIM hub from-document endpoint and re-attaches
            # the resulting model. No conversion is triggered from here.
            doc_meta = doc.metadata_ if isinstance(doc.metadata_, dict) else {}
            linked_model_id = doc_meta.get("source_id") if doc_meta.get("source_module") == "bim_hub" else None
            fields: dict[str, object] = {"source_document_id": doc.id, "error": ""}
            new_model_id: uuid.UUID | None = None
            adopted = False
            if linked_model_id:
                from app.modules.bim_hub.models import BIMModel

                try:
                    model = await self.session.get(BIMModel, uuid.UUID(str(linked_model_id)))
                except (ValueError, TypeError):
                    model = None
                if model is not None and model.project_id == option.project_id:
                    new_model_id = model.id
                    fields["bim_model_id"] = model.id
                    fields["status"] = "model_attached"
                    adopted = True
            if not adopted:
                # Document recorded, no model yet: it must be converted by the
                # BIM hub before the option can be priced. Drop any model a
                # previous attach left behind - mirroring how the model branch
                # clears ``source_document_id`` - because ``generate`` only
                # checks that ``bim_model_id`` is set and would otherwise price
                # the superseded design while the option reads as converting.
                fields["bim_model_id"] = None
                fields["status"] = "converting"
            fields.update(self._match_session_reset(option, new_model_id))
            await self.repo.update_option_fields(option.id, **fields)
            logger.info(
                "Design option %s linked to document %s (model adopted=%s)",
                option.id,
                doc.id,
                adopted,
            )

        await self.session.flush()
        return await self.get_option(option.id)

    # ── Link what the project already holds ──────────────────────────────

    async def link_references(self, option: DesignOption, data: DesignOptionLinkRequest) -> DesignOption:
        """Point an option at a bill, a schedule and a carbon inventory it already has.

        This is the answer to "why can I only give an option a model": an option
        is a whole design alternative, and the estimate, the programme and the
        carbon inventory that describe it usually exist on the platform before
        anyone opens this page. Each reference is guarded against the option's own
        project, so a record from another tenant reads 404 rather than 403 and an
        option id cannot be used to probe foreign estimates.

        Only the fields actually present in the request body are touched
        (``model_fields_set``), so clearing a schedule and leaving it alone are
        different requests. Linking a bill prices the option there and then
        through the same rollup ``generate`` uses - no model required, which is
        what makes a hand-built option estimate a first-class option.

        Args:
            option: The option to update.
            data: The references to link; a field sent as ``null`` clears it.

        Returns:
            The reloaded option.

        Raises:
            HTTPException: 400 when nothing was asked for, 404 when a referenced
                record is missing or belongs to another project.
        """
        provided = data.model_fields_set
        if not provided:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Provide at least one of boq_id, schedule_id or carbon_inventory_id.",
            )

        fields: dict[str, object] = {}
        price_boq_id: uuid.UUID | None = None
        # Read before anything is written. ``update_option_fields`` is an ORM
        # bulk UPDATE, which synchronises the instance already in the session, so
        # by the time the bill is priced below ``option.boq_id`` is the NEW id
        # and cannot answer "was this the bill it had before".
        previous_boq_id = option.boq_id

        if "boq_id" in provided:
            if data.boq_id is None:
                # Unlinking a bill also unpriced the option: leaving the totals in
                # place would show a priced column sourced from nothing.
                fields.update(
                    boq_id=None,
                    boq_source="",
                    direct_cost="0",
                    markups_total="0",
                    grand_total="0",
                    cost_per_m2="0",
                    position_count=0,
                    breakdown=[],
                    status="model_attached" if option.bim_model_id is not None else "draft",
                )
            else:
                boq = await self._project_scoped(option, "boq", data.boq_id)
                fields["boq_id"] = boq.id
                price_boq_id = boq.id

        if "schedule_id" in provided:
            if data.schedule_id is None:
                fields.update(schedule_id=None, duration_days="0", finish_date="")
            else:
                schedule = await self._project_scoped(option, "schedule", data.schedule_id)
                duration, finish = await self._schedule_metrics(schedule)
                fields.update(schedule_id=schedule.id, duration_days=duration, finish_date=finish)

        if "carbon_inventory_id" in provided:
            if data.carbon_inventory_id is None:
                fields.update(carbon_inventory_id=None, embodied_carbon_kg="0", carbon_per_m2="0")
            else:
                inventory = await self._project_scoped(option, "carbon", data.carbon_inventory_id)
                embodied, per_m2 = await self._carbon_metrics(option, inventory.id)
                fields.update(
                    carbon_inventory_id=inventory.id,
                    embodied_carbon_kg=embodied,
                    carbon_per_m2=per_m2,
                )

        await self.repo.update_option_fields(option.id, **fields)
        await self.session.flush()

        if price_boq_id is not None:
            from app.modules.projects.models import Project

            project = await self.session.get(Project, option.project_id)
            priced = await self._price_from_boq(option, price_boq_id, project)
            # Re-sending the bill an option already carries is a refresh, not a
            # change of provenance. Keeping "generated" there matters: a bill this
            # module wrote must not be relabelled as somebody else's just because
            # the user moved the schedule next to it, or the refusal above would
            # start blocking a regeneration this module is entitled to.
            source = option.boq_source if price_boq_id == previous_boq_id and option.boq_source else "linked"
            await self.repo.update_option_fields(option.id, **priced.as_fields(boq_source=source))
            await self.session.flush()
            logger.info(
                "Design option priced from a linked bill: option=%s boq=%s grand=%s %s",
                option.id,
                price_boq_id,
                priced.grand,
                priced.currency,
            )

        logger.info("Design option %s references updated: %s", option.id, sorted(provided))
        return await self.get_option(option.id)

    async def _project_scoped(self, option: DesignOption, kind: str, record_id: uuid.UUID) -> object:
        """Load a cross-module record and prove it belongs to the option's project.

        Every reference an option can hold points at another module's table, so the
        guard has to be the same in all of them: unknown id and foreign-project id
        both read as 404, never 403, so nothing here can be used to discover that a
        record exists in a project the caller cannot see.
        """
        if kind == "boq":
            from app.modules.boq.models import BOQ

            record: object | None = await self.session.get(BOQ, record_id)
            label = "Bill of quantities"
        elif kind == "schedule":
            from app.modules.schedule.models import Schedule

            record = await self.session.get(Schedule, record_id)
            label = "Schedule"
        else:
            from app.modules.carbon.models import CarbonInventory

            record = await self.session.get(CarbonInventory, record_id)
            label = "Carbon inventory"

        if record is None or getattr(record, "project_id", None) != option.project_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{label} not found")
        return record

    async def _schedule_metrics(self, schedule: object) -> tuple[str, str]:
        """Read a schedule's duration in days and its finish date.

        The activities are the truth: a schedule row's own start/end are metadata
        an import may never have filled in, while the activities are what the
        planner actually moved. So the span is taken from the earliest activity
        start to the latest activity finish, and the schedule's own dates are only
        the fallback for a schedule with no activities yet.

        Returns:
            ``(duration_days, finish_date)`` as a decimal string and an ISO date,
            both zero/blank when the schedule carries no usable dates - an
            unanswered question, not a zero-day programme.
        """
        from app.modules.schedule.models import Activity

        rows = (
            await self.session.execute(
                select(Activity.start_date, Activity.end_date).where(
                    Activity.schedule_id == getattr(schedule, "id", None)
                )
            )
        ).all()
        starts = [parsed for row in rows if (parsed := _parse_iso_date(row[0])) is not None]
        finishes = [parsed for row in rows if (parsed := _parse_iso_date(row[1])) is not None]

        start = min(starts) if starts else _parse_iso_date(getattr(schedule, "start_date", None))
        finish = max(finishes) if finishes else _parse_iso_date(getattr(schedule, "end_date", None))
        if start is None or finish is None or finish < start:
            return "0", finish.isoformat() if finish is not None else ""
        # Inclusive of both end days: a task that starts and finishes on the same
        # day lasts one day, not zero.
        return str((finish - start).days + 1), finish.isoformat()

    async def _carbon_metrics(self, option: DesignOption, inventory_id: uuid.UUID) -> tuple[str, str]:
        """Read an inventory's embodied carbon and the same figure over the area.

        A1-A5 (cradle to practical completion) is the figure a design alternative
        is judged on: it is the carbon the choice of scheme actually commits,
        where the operational stages depend on how the finished building is run.
        The totals come from the carbon module's own fresh rollup so this module
        never re-implements a factor calculation.

        Returns:
            ``(embodied_carbon_kg, carbon_per_m2)`` as decimal strings; the second
            is ``"0"`` when the project has no gross floor area to divide by.
        """
        from app.modules.carbon.service import CarbonService

        totals = await CarbonService(self.session).compute_inventory_totals_fresh(inventory_id)
        embodied = _parse_decimal(totals.get("embodied_a1a5", 0))

        gfa = _parse_decimal(option.gfa)
        if gfa <= 0:
            from app.modules.projects.models import Project

            project = await self.session.get(Project, option.project_id)
            gfa = _parse_decimal(getattr(project, "gross_floor_area", None))
        per_m2 = _cents(embodied / gfa) if gfa > 0 else Decimal("0")
        return _money_str(_cents(embodied)), _money_str(per_m2)

    async def _price_from_boq(
        self,
        option: DesignOption,
        boq_id: uuid.UUID,
        project: object,
    ) -> _PricedOption:
        """Roll a bill up into the option's headline figures, FX-correct.

        The one place an option's totals are computed, whether the bill was
        generated from the matched model or linked from the project. The rollup is
        the BOQ module's own currency-aware ``compute_boq_totals``: lines priced in
        a foreign currency are converted to the project base BEFORE they are
        summed, never blended, and a bill that mixes currencies inside itself comes
        back flagged rather than silently added up.

        Args:
            option: The option being priced (its ``gfa_unit`` is preserved).
            boq_id: The bill to total.
            project: The option's project, for the base currency, the FX map and
                the gross floor area behind cost per m2.

        Returns:
            The figures plus the warnings worth telling the caller about.
        """
        from app.modules.boq.service import BOQService, _project_fx_map

        warnings: list[str] = []
        totals = await BOQService(self.session).compute_boq_totals([boq_id])
        totals_row = totals.get(boq_id, {})
        base_currency = (totals_row.get("base_currency") or getattr(project, "currency", "") or "").upper()
        direct = _cents(_parse_decimal(totals_row.get("direct_cost", 0)))
        markups = _cents(_parse_decimal(totals_row.get("markups_total", 0)))
        grand = _cents(_parse_decimal(totals_row.get("grand_total", 0)))
        is_mixed = bool(totals_row.get("is_mixed_currency", False))
        if is_mixed:
            warnings.append("mixed_currency")

        fx_map = _project_fx_map(project)
        breakdown = await self._build_trade_breakdown(boq_id, project, base_currency, fx_map)
        position_count = await self._count_positions(boq_id)

        gfa_dec = _parse_decimal(getattr(project, "gross_floor_area", None))
        if gfa_dec > 0:
            cost_per_m2 = _cents(direct / gfa_dec)
        else:
            cost_per_m2 = Decimal("0")
            warnings.append("no_gfa")

        return _PricedOption(
            direct=direct,
            markups=markups,
            grand=grand,
            cost_per_m2=cost_per_m2,
            gfa=_money_str(gfa_dec) if gfa_dec > 0 else "0",
            gfa_unit=option.gfa_unit or "m2",
            currency=base_currency,
            is_mixed=is_mixed,
            position_count=position_count,
            breakdown=breakdown,
            warnings=warnings,
        )

    # ── Generate (match -> preview/apply -> price) ───────────────────────

    async def generate(
        self,
        option: DesignOption,
        req: DesignOptionGenerateRequest,
        *,
        actor_id: uuid.UUID | None,
    ) -> DesignOptionGenerateResponse:
        """Match the option's model, preview it, and on confirm price its BOQ.

        Steps:
            1. Require an attached BIM model.
            2. Ensure the option has its OWN BOQ (create one when ``boq_id`` is
               null). This is what keeps two options from collapsing into one
               shared BOQ: every option carries a distinct ``boq_id`` and the
               apply is always targeted at it.
            3. Ensure a match session scoped to the option's model.
            4. Run the match and auto-confirm the confident groups (skipped on a
               non-dry-run apply when a prior preview already confirmed them).
            5. Preview (``dry_run``) or apply the confirmed groups into the
               option's own BOQ via ``target_boq_id``.
            6. On apply, roll up the option BOQ's direct cost, markups and grand
               total through the BOQ module (FX-correct, currency-aware), compute
               cost per m2 against the project GFA, snapshot the by-trade
               breakdown, and persist the headline strings.
        """
        warnings: list[str] = []

        if option.bim_model_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Attach a BIM model to this option before generating its estimate.",
            )

        # A linked bill belongs to whoever built it. Step 5 applies the matched
        # positions into ``boq_id`` through ``target_boq_id``, so generating over
        # a linked bill would write this module's guesses into somebody else's
        # estimate - and the same bill may be the tender, the budget or the
        # contract sum elsewhere in the project. Attaching a model to an option
        # that is already priced from a linked bill is a perfectly ordinary
        # thing to do, which is exactly why the refusal has to live here and not
        # only in the button that offers it.
        if (option.boq_source or "") == "linked" and option.boq_id is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "This option is priced from a bill of quantities linked from the project. "
                    "Unlink it before generating an estimate, so the linked bill is not overwritten."
                ),
            )

        from app.modules.projects.models import Project

        project = await self.session.get(Project, option.project_id)

        # ── 2. Ensure the option owns its BOQ (anti-collapse invariant) ──
        boq_id = option.boq_id
        if boq_id is None:
            from app.modules.boq.schemas import BOQCreate
            from app.modules.boq.service import BOQService

            option_set = await self.session.get(DesignOptionSet, option.set_id)
            set_name = option_set.name if option_set is not None else "Design options"
            boq_name = f"{set_name} / {option.name or 'Option'}"[:255]
            boq = await BOQService(self.session).create_boq(
                BOQCreate(
                    project_id=option.project_id,
                    name=boq_name,
                    description=f"Priced bill of quantities for design option '{option.name}'.",
                    estimate_type="design_option",
                )
            )
            boq_id = boq.id
            await self.repo.update_option_fields(option.id, boq_id=boq_id)
            option.boq_id = boq_id

        # ── 3. Ensure a match session scoped to the option's model ───────
        from app.modules.match_elements import schemas as match_schemas
        from app.modules.match_elements.service import get_service as get_match_service

        match_service = get_match_service()
        session_id = option.match_session_id
        if session_id is None:
            created = await match_service.create_session(
                self.session,
                match_schemas.SessionCreate(
                    project_id=option.project_id,
                    bim_model_id=option.bim_model_id,
                    source="bim",
                    name=f"Design option: {option.name}"[:255],
                    catalogue_id=req.catalogue_id,
                    catalogue_ids=req.catalogue_ids,
                    auto_confirm_threshold=req.auto_confirm_threshold,
                ),
                created_by=actor_id,
            )
            session_id = created.id
            await self.repo.update_option_fields(option.id, match_session_id=session_id)
            option.match_session_id = session_id

        # ── 4. Match + auto-confirm ──────────────────────────────────────
        # On a dry run always (re)match so the preview reflects the current
        # catalogue. On an apply, reuse the groups a prior preview already
        # confirmed; only match from scratch when the session has neither
        # confirmed nor applied groups (a direct apply with no preview).
        confirmed_count = await self._count_groups(session_id, ("confirmed",))
        applied_count = await self._count_groups(session_id, ("applied",))
        if req.dry_run or (confirmed_count == 0 and applied_count == 0):
            method = (req.method or "vector").strip().lower()
            if method not in _VALID_METHODS:
                method = "vector"
            try:
                await match_service.run_match(
                    self.session,
                    session_id,
                    match_schemas.RunMatchRequest(
                        method=method,
                        # RunMatchRequest caps max_groups at 200 and top_k at 50;
                        # clamp so a larger option-level request never 422s the
                        # inner match call.
                        max_groups=min(req.max_groups, 200),
                        top_k=min(req.top_k, 50),
                    ),
                    actor_id,
                )
            except HTTPException:
                raise
            except Exception:  # noqa: BLE001 - a matcher failure degrades to an empty preview
                logger.warning("Design option %s match run failed", option.id, exc_info=True)
                warnings.append("match_failed")
            await match_service.bulk_confirm(
                self.session,
                session_id,
                match_schemas.BulkConfirmRequest(threshold=req.auto_confirm_threshold),
                actor_id,
            )

        # ── 5. Preview or apply into the option's OWN BOQ ────────────────
        apply_res = await match_service.apply_to_boq(
            self.session,
            session_id,
            match_schemas.ApplyToBoqRequest(dry_run=req.dry_run, target_boq_id=boq_id),
            actor_id,
        )

        groups_total = await self._count_groups(session_id, None)
        groups_confirmed = await self._count_groups(session_id, ("confirmed", "applied"))
        element_count = await self._sum_group_elements(session_id, ("confirmed", "applied"))

        gfa_dec = _parse_decimal(getattr(project, "gross_floor_area", None))
        gfa_str = _money_str(gfa_dec) if gfa_dec > 0 else "0"
        gfa_unit = option.gfa_unit or "m2"

        preview_lines = [
            DesignOptionGeneratePreviewLine(
                group_key=p.group_key,
                description=p.description,
                unit=p.unit,
                quantity=_money_str(_parse_decimal(p.quantity)),
                unit_rate=_money_str(p.unit_rate),
                currency=p.currency or "",
                line_total=_money_str(p.line_total),
                section_path=list(p.section_path or []),
            )
            for p in apply_res.positions
        ]

        # ── 6a. Dry run: report the preview, persist nothing ─────────────
        if req.dry_run:
            direct = _cents(_parse_decimal(apply_res.grand_total))
            currency = (apply_res.currency or getattr(project, "currency", "") or "").upper()
            if gfa_dec > 0:
                cost_per_m2 = _cents(direct / gfa_dec)
            else:
                cost_per_m2 = Decimal("0")
                warnings.append("no_gfa")
            return DesignOptionGenerateResponse(
                option_id=option.id,
                dry_run=True,
                boq_id=boq_id,
                method=req.method,
                status=option.status,
                positions_created=apply_res.positions_created,
                element_count=element_count,
                position_count=len(apply_res.positions),
                groups_total=groups_total,
                groups_confirmed=groups_confirmed,
                direct_cost=_money_str(direct),
                markups_total="0",
                grand_total=_money_str(direct),
                cost_per_m2=_money_str(cost_per_m2),
                gfa=gfa_str,
                gfa_unit=gfa_unit,
                currency=currency,
                breakdown=self._preview_breakdown(apply_res.positions),
                preview=preview_lines,
                warnings=warnings,
            )

        # ── 6b. Apply: authoritative FX-correct rollup + persist ─────────
        priced = await self._price_from_boq(option, boq_id, project)
        warnings.extend(priced.warnings)

        await self.repo.update_option_fields(
            option.id,
            **priced.as_fields(boq_source="generated"),
            element_count=element_count,
        )
        await self.session.flush()
        logger.info(
            "Design option priced: option=%s boq=%s direct=%s grand=%s %s (mixed=%s)",
            option.id,
            boq_id,
            priced.direct,
            priced.grand,
            priced.currency,
            priced.is_mixed,
        )

        return DesignOptionGenerateResponse(
            option_id=option.id,
            dry_run=False,
            boq_id=boq_id,
            method=req.method,
            status="priced",
            positions_created=apply_res.positions_created,
            element_count=element_count,
            position_count=priced.position_count,
            groups_total=groups_total,
            groups_confirmed=groups_confirmed,
            direct_cost=_money_str(priced.direct),
            markups_total=_money_str(priced.markups),
            grand_total=_money_str(priced.grand),
            cost_per_m2=_money_str(priced.cost_per_m2),
            gfa=priced.gfa,
            gfa_unit=priced.gfa_unit,
            currency=priced.currency,
            is_mixed_currency=priced.is_mixed,
            breakdown=priced.breakdown,
            preview=preview_lines,
            warnings=warnings,
        )

    # ── Internal helpers ─────────────────────────────────────────────────

    async def _count_groups(
        self,
        session_id: uuid.UUID,
        statuses: tuple[str, ...] | None,
    ) -> int:
        """Count match groups for a session, optionally filtered by status."""
        from app.modules.match_elements.models import MatchGroup

        stmt = select(func.count(MatchGroup.id)).where(MatchGroup.session_id == session_id)
        if statuses:
            stmt = stmt.where(MatchGroup.status.in_(statuses))
        return int((await self.session.execute(stmt)).scalar() or 0)

    async def _sum_group_elements(
        self,
        session_id: uuid.UUID,
        statuses: tuple[str, ...],
    ) -> int:
        """Sum the BIM element count across a session's groups in the given states."""
        from app.modules.match_elements.models import MatchGroup

        stmt = (
            select(func.coalesce(func.sum(MatchGroup.element_count), 0))
            .where(MatchGroup.session_id == session_id)
            .where(MatchGroup.status.in_(statuses))
        )
        return int((await self.session.execute(stmt)).scalar() or 0)

    async def _count_positions(self, boq_id: uuid.UUID) -> int:
        """Count the positions written into an option's BOQ (flat, no sections)."""
        from app.modules.boq.models import Position

        stmt = select(func.count(Position.id)).where(Position.boq_id == boq_id)
        return int((await self.session.execute(stmt)).scalar() or 0)

    def _preview_breakdown(self, positions: list) -> list[dict]:
        """Group dry-run preview lines into a by-trade snapshot (best effort).

        A preview line carries the resolved classification label as its
        ``section_path`` head rather than the raw code, so preview buckets group
        by that label. The authoritative code-based breakdown is built from real
        positions in :meth:`_build_trade_breakdown` on apply.
        """
        buckets: dict[str, dict] = {}
        for p in positions:
            section_path = list(getattr(p, "section_path", None) or [])
            label = section_path[0] if section_path else "Unclassified"
            key = _slug(label)
            bucket = buckets.setdefault(
                key,
                {
                    "key": key,
                    "label": label,
                    "classification_system": "preview",
                    "cost": Decimal("0"),
                },
            )
            bucket["cost"] += _parse_decimal(getattr(p, "line_total", 0))
        out = [
            {
                "key": b["key"],
                "label": b["label"],
                "classification_system": b["classification_system"],
                "quantity": "0",
                "unit": "",
                "cost": _money_str(_cents(b["cost"])),
            }
            for b in buckets.values()
        ]
        out.sort(key=lambda entry: _parse_decimal(entry["cost"]), reverse=True)
        return out

    async def _build_trade_breakdown(
        self,
        boq_id: uuid.UUID,
        project: object,
        base_currency: str,
        fx_map: dict[str, str],
    ) -> list[dict]:
        """Snapshot the option BOQ's cost per trade in the project base currency.

        Every leaf position is converted into the base currency with the same
        FX-aware helper the BOQ export/rollup uses, then bucketed by
        classification (DIN 276 group, MasterFormat division or free-form trade).
        Each entry carries a dominant unit and its summed quantity (the unit that
        contributes the most cost in the bucket), so the comparison phase can show
        a per-trade quantity without blending m2 and m3. Money and quantity are
        Decimal-as-strings.
        """
        from app.modules.boq.models import Position
        from app.modules.boq.service import _is_section, _leaf_total_base_with_resources

        preferred = (getattr(project, "classification_standard", "") or "din276").strip().lower() or "din276"
        rows = (await self.session.execute(select(Position).where(Position.boq_id == boq_id))).scalars().all()

        buckets: dict[str, dict] = {}
        for pos in rows:
            if _is_section(pos):
                continue
            cost = _leaf_total_base_with_resources(pos, fx_map, base_currency)
            key, label, system = _classify_bucket(getattr(pos, "classification", None), preferred)
            bucket = buckets.setdefault(
                key,
                {
                    "key": key,
                    "label": label,
                    "classification_system": system,
                    "cost": Decimal("0"),
                    "_units": {},
                },
            )
            bucket["cost"] += cost
            unit = (getattr(pos, "unit", "") or "").strip()
            if unit:
                per_unit = bucket["_units"].setdefault(unit, {"qty": Decimal("0"), "cost": Decimal("0")})
                per_unit["qty"] += _parse_decimal(getattr(pos, "quantity", 0))
                per_unit["cost"] += cost

        out: list[dict] = []
        for bucket in buckets.values():
            units = bucket.pop("_units")
            dominant_unit = ""
            dominant_qty = Decimal("0")
            if units:
                dominant_unit = max(units.items(), key=lambda kv: kv[1]["cost"])[0]
                dominant_qty = units[dominant_unit]["qty"]
            out.append(
                {
                    "key": bucket["key"],
                    "label": bucket["label"],
                    "classification_system": bucket["classification_system"],
                    "quantity": _money_str(dominant_qty),
                    "unit": dominant_unit,
                    "cost": _money_str(_cents(bucket["cost"])),
                }
            )
        out.sort(key=lambda entry: _parse_decimal(entry["cost"]), reverse=True)
        return out
