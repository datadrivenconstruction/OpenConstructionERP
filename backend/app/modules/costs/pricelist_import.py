# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Preview and import of a regional price list, shared by the endpoints and the background jobs.

The work is the same whether it runs inside a request (a small list through
the API) or as a background job (the import screen, any size): read the list,
report it, or create the catalogue and write the voci. Refusals carry a code
the import screen translates (:class:`PriceListRefused`).

Writing is batched. A regional list holds tens of thousands of voci, and the
generic cost import looks each one up before inserting it, which costs about
4 ms a row on PostgreSQL: four and a half minutes for a 44 000 voce list. Here
one query per slice of 2 000 finds the codes the catalogue already holds, and
the slice goes in with one flush. The import is atomic all the same: the rows
go with the transaction, and a catalogue created for a failed run is removed.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
import zipfile
import zlib
from collections.abc import Awaitable, Callable, Iterator
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.importers import ImporterParseError
from app.modules.costs.pricelists.base import REGION_NAMES, PriceListSource
from app.modules.costs.pricelists.containers import ContainerRefused
from app.modules.costs.pricelists.service import (
    CURRENCY,
    UploadPlan,
    build_preview,
    cost_item_payload,
    skip_reason,
    source_payload,
)

logger = logging.getLogger(__name__)

# Rows written per flush; also the slice the generic import hands over.
HANDOVER_ROWS = 2000
CATALOG_NAME_MAX = 50  # the catalogue name is also the items' region tag (max 50)

# What each refusal says to an API user; the import screen translates the code.
REFUSAL_MESSAGES: dict[str, str] = {
    "empty_file": "The file is empty.",
    "file_too_large": "The file is larger than the upload limit.",
    "zip_unreadable": "The ZIP archive cannot be read.",
    "zip_too_many_members": "The ZIP archive holds too many files.",
    "zip_too_large_inflated": "The ZIP archive would unpack to more than the limit.",
    "zip_ratio_suspicious": "A file in the ZIP archive is compressed far more than any price list is.",
    "zip_encrypted": "The ZIP archive is encrypted.",
    "zip_member_too_large": "A file in the ZIP archive unpacks to more than it declares.",
    "zip_member_corrupt": "A file in the ZIP archive is damaged: its contents do not match its checksum.",
    "text_encoding_unreadable": "The file's text encoding could not be read.",
    "no_price_list_found": "No regional price list in a recognised format was found in the upload.",
    "pricelist_unreadable": "The price list could not be read.",
    "invalid_region": "Unknown region code.",
    "invalid_edition": "The edition must be a year such as 2025.",
    "catalog_name_required": "A catalogue name is required.",
    "catalog_name_too_long": "The catalogue name is longer than 50 characters.",
    "catalog_name_unavailable": "This name cannot be used for a new catalogue. Choose another name.",
    "nothing_to_import": "The price list holds no priced voci.",
    "import_failed": "The import failed and was rolled back. No cost items were imported.",
    "upload_not_found": "The uploaded file is no longer available. Upload it again.",
}


class PriceListRefused(Exception):
    """A refusal the import screen translates by ``code``."""

    def __init__(self, code: str, status_code: int = status.HTTP_400_BAD_REQUEST, **params: Any) -> None:
        super().__init__(REFUSAL_MESSAGES.get(code, code))
        self.code = code
        self.status_code = status_code
        self.params = params

    def as_http(self) -> HTTPException:
        return HTTPException(
            status_code=self.status_code,
            detail={"code": self.code, "message": str(self), **self.params},
        )

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), "params": self.params}

    @classmethod
    def from_parse_error(cls, exc: ImporterParseError) -> PriceListRefused:
        """A reader's coded parse error, worded by the screen from ``boq.import_error.<code>``.

        The parser's own message stays the English fallback: it names what
        broke, which the bare code does not.
        """
        refused = cls(exc.code, **exc.params)
        refused.args = (str(exc),)
        return refused


def apply_overrides(source: PriceListSource, region_code: str | None, edition: str | None) -> None:
    """The user's corrections to the region and edition the file suggested."""
    if region_code:
        code = region_code.strip().upper()
        if code not in REGION_NAMES:
            raise PriceListRefused("invalid_region", status.HTTP_422_UNPROCESSABLE_CONTENT, region_code=region_code)
        source.region_code = code
        source.detected_from = "user"
        if source.licence_stated_in == "catalogue":
            source.licence = None
            source.licence_stated_in = None
    if edition:
        value = edition.strip()
        if not re.fullmatch(r"20\d{2}", value):
            raise PriceListRefused("invalid_edition", status.HTTP_422_UNPROCESSABLE_CONTENT, edition=edition)
        source.edition = value


def check_catalog_name(catalog_name: str | None) -> str:
    """The catalogue name the user gave, trimmed, or a refusal."""
    name = (catalog_name or "").strip()
    if not name:
        raise PriceListRefused("catalog_name_required", status.HTTP_422_UNPROCESSABLE_CONTENT)
    if len(name) > CATALOG_NAME_MAX:
        raise PriceListRefused("catalog_name_too_long", status.HTTP_422_UNPROCESSABLE_CONTENT, limit=CATALOG_NAME_MAX)
    return name


async def name_is_free(session: AsyncSession, name: str) -> bool:
    """Whether a new catalogue may take ``name``: the very check the catalogue's creation runs."""
    from app.modules.costs.service import CostCatalogService

    try:
        await CostCatalogService(session)._assert_name_available(name)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_409_CONFLICT:
            return False
        raise
    return True


async def free_catalog_name(session: AsyncSession, name: str) -> str:
    """``name``, or the first of ``name (2)``, ``name (3)``, ... a new catalogue may take.

    Catalogue names are unique across the whole installation, because the
    name is also the region tag the imported items are keyed by. So the name
    a list suggests ("Toscana 2026") may already be in use by someone the
    user cannot see; offering it would let the import refuse it, and the
    refusal would tell them it exists. The suggestion is made free up front.
    """
    base = name.strip()[:CATALOG_NAME_MAX].rstrip()
    if not base or await name_is_free(session, base):
        return base
    for number in range(2, 100):
        suffix = f" ({number})"
        candidate = base[: CATALOG_NAME_MAX - len(suffix)].rstrip() + suffix
        if await name_is_free(session, candidate):
            return candidate
    return base


async def with_free_suggestion(session: AsyncSession, report: dict[str, Any]) -> dict[str, Any]:
    """The preview with its suggested catalogue name made free for a new catalogue."""
    source = report.get("source") or {}
    suggested = source.get("suggested_catalog_name")
    if suggested:
        source["suggested_catalog_name"] = await free_catalog_name(session, suggested)
    return report


def preview(
    plan: UploadPlan,
    region_code: str | None,
    edition: str | None,
    on_row: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Report the list without writing anything (blocking: run it in a thread)."""
    apply_overrides(plan.source, region_code, edition)
    try:
        report = build_preview(plan, on_row=on_row)
    except ContainerRefused as exc:
        raise PriceListRefused(exc.code, **exc.params) from exc
    except PriceListRefused:
        raise
    except ImporterParseError as exc:
        raise PriceListRefused.from_parse_error(exc) from exc
    except (zipfile.BadZipFile, zlib.error) as exc:
        # A workbook's own archive, read by the spreadsheet library.
        raise PriceListRefused("zip_member_corrupt") from exc
    except Exception as exc:
        logger.warning("Price list preview failed (%s): %s", plan.format.format_id, exc)
        raise PriceListRefused("pricelist_unreadable", format=plan.format.format_id) from exc
    # Re-applied: the readers fill the source as they go and may overwrite a
    # field the user corrected.
    apply_overrides(plan.source, region_code, edition)
    report["source"] = source_payload(plan.source)
    if region_code:
        for warning in ("region_inferred", "region_not_detected"):
            if warning in report["warnings"]:
                report["warnings"].remove(warning)
    return report


def payload_batches(
    plan: UploadPlan, region_code: str | None, edition: str | None
) -> Iterator[tuple[list[dict[str, Any]], dict[str, Any]]]:
    """Slices of cost-item payloads, with running counts, read in one pass."""
    seen: set[str] = set()
    counts: dict[str, Any] = {"rows": 0, "duplicates": 0, "skipped": {}}
    batch: list[dict[str, Any]] = []
    for row in plan.rows():
        counts["rows"] += 1
        reason = skip_reason(row)
        if reason:
            counts["skipped"][reason] = counts["skipped"].get(reason, 0) + 1
            continue
        if row.code in seen:
            counts["duplicates"] += 1
            continue
        seen.add(row.code)
        apply_overrides(plan.source, region_code, edition)
        plan.source.resolve_licence()
        batch.append(cost_item_payload(row, plan.source))
        if len(batch) >= HANDOVER_ROWS:
            yield batch, counts
            batch = []
    yield batch, counts


async def insert_batch(
    session: AsyncSession, payloads: list[dict[str, Any]], *, catalog_id: uuid.UUID, region: str
) -> int:
    """Write one slice of voci into the catalogue; return how many were new.

    One query finds the codes the catalogue already holds, the rest go in with
    one flush, and the session forgets them afterwards so a long list does not
    pile up in its identity map. Every row is validated as ``CostItemCreate``
    first, like any other cost item.
    """
    from app.modules.costs.models import CostItem
    from app.modules.costs.schemas import CostItemCreate

    if not payloads:
        return 0
    rows = [CostItemCreate(**p, region=region, catalog_id=catalog_id) for p in payloads]
    codes = [row.code for row in rows]
    existing = set(
        (await session.execute(select(CostItem.code).where(CostItem.region == region, CostItem.code.in_(codes))))
        .scalars()
        .all()
    )
    items = [
        CostItem(
            code=row.code,
            description=row.description,
            descriptions=row.descriptions,
            unit=row.unit,
            rate=str(row.rate),
            currency=row.currency or CURRENCY,
            source=row.source,
            classification=row.classification,
            components=row.components,
            tags=row.tags,
            region=row.region,
            mass_per_unit=row.mass_per_unit,
            mass_basis=row.mass_basis,
            catalog_id=row.catalog_id,
            metadata_=row.metadata,
        )
        for row in rows
        if row.code not in existing
    ]
    if items:
        session.add_all(items)
        await session.flush()
        for item in items:
            session.expunge(item)
    return len(items)


ProgressCallback = Callable[[int, int], Awaitable[None]]


async def import_list(
    session: AsyncSession,
    plan: UploadPlan,
    *,
    catalog_name: str,
    region_code: str | None,
    edition: str | None,
    owner_id: uuid.UUID | None,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Create the catalogue and write the list's priced voci into it, all or nothing.

    Args:
        session: A session of its own; it is committed on success.
        plan: The planned upload.
        catalog_name: The new catalogue's name, also the items' region tag.
        region_code: The region the user confirmed, if the file did not say.
        edition: The edition the user confirmed, if the file did not say.
        owner_id: Who creates the catalogue.
        on_progress: Called after each slice with the rows read and the voci
            written so far.

    Raises:
        PriceListRefused: For anything the user can act on; the catalogue
            and every row are gone again when it is raised.
    """
    from app.modules.costs.schemas import CostCatalogCreate
    from app.modules.costs.service import CostCatalogService, CostItemService, _safe_publish

    name = check_catalog_name(catalog_name)
    apply_overrides(plan.source, region_code, edition)
    catalog_service = CostCatalogService(session)
    try:
        catalog = await catalog_service.create_catalog(
            CostCatalogCreate(name=name, currency=CURRENCY, description=None),
            created_by=owner_id,
            source="import",
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_409_CONFLICT:
            # Neutral on purpose: the name may belong to a catalogue the user
            # cannot see, and the refusal must not confirm that it exists.
            raise PriceListRefused(
                "catalog_name_unavailable",
                status.HTTP_409_CONFLICT,
                suggestion=await free_catalog_name(session, name),
            ) from exc
        raise
    catalog_id = catalog.id

    # Imported here: ``costs/router.py`` mounts the price-list router at import
    # time, so a module-level import of it from this side would be circular.
    from app.modules.costs.router import _discard_failed_import, _invalidate_cost_cache

    batches = payload_batches(plan, region_code, edition)
    imported = 0
    handed_over = 0
    counts: dict[str, Any] = {}
    try:
        while True:
            step = await asyncio.to_thread(next, batches, None)
            if step is None:
                break
            payloads, counts = step
            handed_over += len(payloads)
            imported += await insert_batch(session, payloads, catalog_id=catalog_id, region=name)
            if on_progress is not None:
                await on_progress(int(counts.get("rows", 0)), imported)
        if imported == 0:
            # A catalogue with nothing in it is not what the user confirmed.
            raise PriceListRefused(
                "nothing_to_import", status.HTTP_422_UNPROCESSABLE_CONTENT, skipped=counts.get("skipped", {})
            )
        await session.commit()
    except PriceListRefused:
        await _discard_failed_import(CostItemService(session), catalog_service, catalog_id)
        raise
    except ContainerRefused as exc:
        await _discard_failed_import(CostItemService(session), catalog_service, catalog_id)
        raise PriceListRefused(exc.code, **exc.params) from exc
    except ImporterParseError as exc:
        await _discard_failed_import(CostItemService(session), catalog_service, catalog_id)
        raise PriceListRefused.from_parse_error(exc) from exc
    except (zipfile.BadZipFile, zlib.error) as exc:
        await _discard_failed_import(CostItemService(session), catalog_service, catalog_id)
        raise PriceListRefused("zip_member_corrupt") from exc
    except Exception as exc:
        logger.exception("Price list import failed after %d staged rows", handed_over)
        await _discard_failed_import(CostItemService(session), catalog_service, catalog_id)
        raise PriceListRefused(
            "import_failed",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            rows_discarded=handed_over,
            error=str(exc)[:300],
        ) from exc

    # The Cost Explorer index rebuilds the one region a price-base import loads.
    await _safe_publish(
        "costs.items.bulk_imported",
        {"created_count": imported, "skipped_count": handed_over - imported, "region": name},
        source_module="oe_costs",
    )
    _invalidate_cost_cache()
    logger.info(
        "Price list imported: %s, %s rows, %d imported into catalogue %s",
        plan.format.format_id,
        counts.get("rows"),
        imported,
        catalog_id,
    )
    return {
        "imported": imported,
        "rows": counts.get("rows", 0),
        "duplicates": counts.get("duplicates", 0) + (handed_over - imported),
        "skipped": counts.get("skipped", {}),
        "durability": "atomic",
        "catalog": name,
        "catalog_id": str(catalog_id),
        "catalog_currency": CURRENCY,
        "source": source_payload(plan.source),
    }


__all__ = [
    "free_catalog_name",
    "name_is_free",
    "with_free_suggestion",
    "CATALOG_NAME_MAX",
    "HANDOVER_ROWS",
    "REFUSAL_MESSAGES",
    "PriceListRefused",
    "apply_overrides",
    "check_catalog_name",
    "import_list",
    "insert_batch",
    "payload_batches",
    "preview",
]
