# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""What still points at a document, so a delete can say what it costs.

Thirty-four columns across twenty-one modules hold a document id that no
foreign key constrains. ``delete_document`` removes the row unconditionally:
it never asks whether anything still points at the id, and the three
subscribers of ``documents.document.deleted`` (the module's own handler, the
file_search indexer, the file_references purger) own none of these columns.
So the ids are left behind, and the user confirming the delete is told
nothing about them.

This module is the read-only half of the answer: it names the referrers and
counts them. It changes no delete behaviour. Blocking the delete would be the
wrong call, and the codebase says so itself - ``CloseoutBinding`` documents
its soft link as deliberate "so deleting a document never cascade-wipes the
closeout history". The references are meant to be severable. They are just
not meant to be invisible.

Why the list is curated rather than discovered
----------------------------------------------
Matching column names at runtime finds the same thirty-four, and that
agreement is what the gate in ``tests/unit/test_document_reference_integrity``
checks. It is not safe as the source of truth, because in this codebase a
column called ``document_id`` does not always mean a document:

* ``EInvoiceEvent.document_id`` carries a ForeignKey to
  ``oe_einvoice_clearance_document`` - a different table entirely. It is
  excluded here only because it has that key; a name-matcher would have
  swallowed it.
* ``PortalDocumentAccessLog.document_id`` is polymorphic. It is qualified by
  ``document_type``, a free-form ``String(64)`` the API accepts from the
  caller, and only the value ``document`` means a documents-module row. Hence
  ``qualifier`` below.

Impact vocabulary
-----------------
``strands``
    The column is NOT NULL, so the row cannot even record that the document
    went away. It is left pointing at nothing and no repair short of deleting
    the row can fix it. Six columns are in this state.
``unlinks``
    The column is nullable, or the id sits in a JSON array an element can be
    dropped from. The row survives and loses its attachment.
``retains``
    The row is meant to outlive the document. The portal access log is
    append-only audit, and takeoff already holds its own copy of the blob:
    ``preserve_blobs_for_deleted_source`` runs inline in the delete path
    precisely so the takeoff document keeps working.

Impacts are read off the model and its comments, never off the column name.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Text, cast, func, literal, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Base

logger = logging.getLogger(__name__)

ReferenceKind = Literal["scalar", "array"]
ReferenceImpact = Literal["strands", "unlinks", "retains"]


@dataclass(frozen=True)
class DocumentReference:
    """One column somewhere in the platform that holds a document id.

    ``table`` and ``column`` are physical names resolved against
    :data:`Base.metadata` at call time. Nothing here imports another module,
    so the registry stays loadable whatever subset of modules is installed,
    and a module that is absent simply drops out of the resolved set.
    """

    module: str
    model: str
    table: str
    column: str
    kind: ReferenceKind
    impact: ReferenceImpact
    #: ``(column, value)`` that narrows a polymorphic reference to documents.
    qualifier: tuple[str, str] | None = None

    @property
    def key(self) -> str:
        """Stable identifier the API and the tests both use."""
        return f"{self.model}.{self.column}"


#: Every unconstrained document reference in the platform, by owning module.
DOCUMENT_REFERENCES: tuple[DocumentReference, ...] = (
    DocumentReference("cde", "DocumentRevision", "oe_cde_revision", "document_id", "scalar", "unlinks"),
    DocumentReference("closeout", "CloseoutBinding", "oe_closeout_binding", "document_id", "scalar", "unlinks"),
    DocumentReference(
        "construction_control",
        "MaterialRecord",
        "oe_cc_material_record",
        "cert_document_id",
        "scalar",
        "unlinks",
    ),
    DocumentReference("contracts", "ContractDocument", "oe_contracts_document", "document_id", "scalar", "unlinks"),
    DocumentReference("contracts", "ContractSecurity", "oe_contracts_security", "document_id", "scalar", "unlinks"),
    DocumentReference(
        "contracts",
        "RetentionRelease",
        "oe_contracts_retention_release",
        "document_ids",
        "array",
        "unlinks",
    ),
    # Evidence behind a stored material claim. Deleting the ticket or the
    # invoice does not undo the billing, it only removes what backs it up,
    # which is exactly what a payer asks to see when the claim is queried.
    DocumentReference(
        "contracts",
        "StoredMaterial",
        "oe_contracts_stored_material",
        "bill_of_sale_document_id",
        "scalar",
        "unlinks",
    ),
    DocumentReference(
        "contracts",
        "StoredMaterial",
        "oe_contracts_stored_material",
        "delivery_ticket_document_id",
        "scalar",
        "unlinks",
    ),
    DocumentReference(
        "contracts",
        "StoredMaterial",
        "oe_contracts_stored_material",
        "insurance_document_id",
        "scalar",
        "unlinks",
    ),
    DocumentReference(
        "contracts",
        "StoredMaterial",
        "oe_contracts_stored_material",
        "invoice_document_id",
        "scalar",
        "unlinks",
    ),
    DocumentReference(
        "contracts",
        "StoredMaterial",
        "oe_contracts_stored_material",
        "photo_document_ids",
        "array",
        "unlinks",
    ),
    DocumentReference(
        "correspondence",
        "Correspondence",
        "oe_correspondence_correspondence",
        "linked_document_ids",
        "array",
        "unlinks",
    ),
    DocumentReference("defects_liability", "DlpWarranty", "oe_dlp_warranty", "document_id", "scalar", "unlinks"),
    DocumentReference(
        "design_options",
        "DesignOption",
        "oe_design_options_option",
        "source_document_id",
        "scalar",
        "unlinks",
    ),
    DocumentReference("documents", "ProjectPhoto", "oe_documents_photo", "document_id", "scalar", "unlinks"),
    # NOT NULL: a sheet is a page OF the document, and cannot outlive it usefully.
    DocumentReference("documents", "Sheet", "oe_documents_sheet", "document_id", "scalar", "strands"),
    DocumentReference("fieldreports", "FieldReport", "oe_fieldreports_report", "document_ids", "array", "unlinks"),
    DocumentReference("markups", "Markup", "oe_markups_markup", "document_id", "scalar", "unlinks"),
    # NOT NULL: a scale calibration is meaningless without the page it calibrates.
    DocumentReference("markups", "ScaleConfig", "oe_markups_scale_config", "document_id", "scalar", "strands"),
    DocumentReference("meetings", "Meeting", "oe_meetings_meeting", "document_ids", "array", "unlinks"),
    # NOT NULL: a pin is positioned on a document page.
    DocumentReference("plan_room", "PlanPin", "oe_plan_pin", "document_id", "scalar", "strands"),
    # Append-only audit, and polymorphic: only document_type='document' is us.
    DocumentReference(
        "portal",
        "PortalDocumentAccessLog",
        "oe_portal_document_access_log",
        "document_id",
        "scalar",
        "retains",
        qualifier=("document_type", "document"),
    ),
    DocumentReference("punchlist", "PunchItem", "oe_punchlist_item", "document_id", "scalar", "unlinks"),
    DocumentReference(
        "qms",
        "QMSInspection",
        "oe_qms_inspection",
        "attachment_document_ids",
        "array",
        "unlinks",
    ),
    # NOT NULL, and the row carries a SHA-256 so a later check can prove the
    # bytes never changed after sign-off. Deleting the document destroys the
    # evidence that sign-off was recorded against.
    DocumentReference(
        "qms",
        "QMSInspectionAttachment",
        "oe_qms_inspection_attachment",
        "document_id",
        "scalar",
        "strands",
    ),
    DocumentReference(
        "resumable_uploads",
        "ResumableUploadSession",
        "oe_resumable_uploads_session",
        "document_id",
        "scalar",
        "unlinks",
    ),
    # NOT NULL: the run's bookkeeping row names the document it read.
    DocumentReference("takeoff", "AiTakeoffRun", "oe_ai_takeoff_run", "document_id", "scalar", "strands"),
    # preserve_blobs_for_deleted_source hands takeoff its own copy of the file
    # before the unlink, so the takeoff document keeps working; what dangles is
    # the provenance link, not the content.
    DocumentReference(
        "takeoff",
        "TakeoffDocument",
        "oe_takeoff_document",
        "source_document_id",
        "scalar",
        "retains",
    ),
    DocumentReference(
        "takeoff",
        "TakeoffMeasurement",
        "oe_takeoff_measurement",
        "document_id",
        "scalar",
        "unlinks",
    ),
    DocumentReference(
        "tax_withholding",
        "PartyTaxStatus",
        "oe_tax_withholding_party",
        "evidence_document_id",
        "scalar",
        "unlinks",
    ),
    DocumentReference(
        "temporary_works",
        "TemporaryWorksItem",
        "oe_temp_works_item",
        "check_certificate_document_id",
        "scalar",
        "unlinks",
    ),
    DocumentReference(
        "temporary_works",
        "TemporaryWorksItem",
        "oe_temp_works_item",
        "design_document_id",
        "scalar",
        "unlinks",
    ),
    DocumentReference("transmittals", "TransmittalItem", "oe_transmittals_item", "document_id", "scalar", "unlinks"),
    DocumentReference(
        "variations",
        "VariationRequest",
        "oe_variations_request",
        "source_document_id",
        "scalar",
        "unlinks",
    ),
)


def resolved_references() -> tuple[DocumentReference, ...]:
    """Return the references whose table and column are actually present.

    Modules are plugins. A deployment that does not carry ``temporary_works``
    has no ``oe_temp_works_item`` in the metadata, and querying it would
    raise. Resolving against :data:`Base.metadata` keeps the registry honest
    about one install without having to be edited per install.
    """
    present = []
    for ref in DOCUMENT_REFERENCES:
        table = Base.metadata.tables.get(ref.table)
        if table is None:
            continue
        if ref.column not in table.c:
            logger.debug("Reference %s: table %s has no column %s", ref.key, ref.table, ref.column)
            continue
        if ref.qualifier and ref.qualifier[0] not in table.c:
            logger.debug("Reference %s: qualifier column %s missing", ref.key, ref.qualifier[0])
            continue
        present.append(ref)
    return tuple(present)


def _predicate(ref: DocumentReference, document_id: uuid.UUID):
    """Build the WHERE clause that matches ``document_id`` for one reference."""
    table = Base.metadata.tables[ref.table]
    col = table.c[ref.column]

    if ref.kind == "array":
        # The six array columns are JSON, not JSONB, so the containment
        # operator is unavailable without a cast that differs per dialect.
        # Matching the quoted id inside the serialised array is portable
        # across PostgreSQL and SQLite and exact enough: the elements are
        # UUID strings, and the quotes bound the match so one id can never be
        # a substring of another. ``contains`` binds the value rather than
        # inlining it.
        clause = cast(col, Text).contains(f'"{document_id}"')
    else:
        # The columns are a mix of GUID and String(36)/String(255), and one
        # bound string serves both: GUID is a TypeDecorator over String(36)
        # on every dialect (see its docstring - it never emitted a native
        # uuid column), and its bind step passes a str through untouched.
        # Asking the column for its ``python_type`` instead would raise:
        # TypeDecorator leaves that property unimplemented, and it raises
        # rather than returning, so even ``getattr(..., None)`` does not
        # shield the caller.
        clause = col == str(document_id)

    if ref.qualifier:
        qualifier_col, qualifier_value = ref.qualifier
        clause = clause & (table.c[qualifier_col] == qualifier_value)
    return clause


async def count_references(session: AsyncSession, document_id: uuid.UUID) -> dict[str, int]:
    """Count the rows still pointing at ``document_id``, keyed by reference.

    One round trip: the per-table counts are UNION ALL'd into a single
    statement rather than issued as thirty-four queries. Only non-zero
    counts come back, so the caller can treat an empty mapping as "nothing
    references this".

    Most of these columns carry no index - eight declare ``index=True`` and
    the rest leave the branch a sequential scan on a large project. That is
    accepted rather than overlooked: this runs once, when somebody clicks
    delete, and the caller is built so a slow answer costs nothing. The panel
    is simply absent until the count arrives, and the confirm buttons work
    throughout. Indexing for it would be a migration across most of the
    twenty-one modules to speed up a once-per-delete query.
    """
    refs = resolved_references()
    if not refs:
        return {}

    selects = [
        select(literal(ref.key).label("ref_key"), func.count().label("hits"))
        .select_from(Base.metadata.tables[ref.table])
        .where(_predicate(ref, document_id))
        for ref in refs
    ]
    statement = union_all(*selects) if len(selects) > 1 else selects[0]

    result = await session.execute(statement)
    return {row.ref_key: int(row.hits) for row in result if row.hits}


#: Ids per statement in :func:`count_references_many`. Bounds the ``IN`` list
#: and the ``OR`` of array matches so one batch never builds a statement the
#: driver chokes on; a full 2000-id batch is four rounds.
_MANY_CHUNK = 500


#: Heaviest consequence first. A row reached through two columns is counted
#: in the batch under the heavier of the two.
_IMPACT_RANK: dict[str, int] = {"strands": 0, "unlinks": 1, "retains": 2}


@dataclass(frozen=True)
class BatchReferenceCounts:
    """What :func:`count_references_many` found, read two ways.

    ``per_document`` is the per-document answer, equal to calling
    :func:`count_references` once per id: it counts links, so a meeting that
    holds two of the selected drawings counts once against each.

    ``rows_by_key`` counts rows, which is what a "N records lose the
    attachment" headline promises. Each row that points into the batch is
    counted once over the whole batch, under one reference key: the one with
    the heaviest impact among those that reach it, then the first in
    :data:`DOCUMENT_REFERENCES`. Its values therefore add up to the number of
    distinct rows, and the per-impact sums of it to the number of rows that
    strand, unlink or retain.
    """

    per_document: dict[uuid.UUID, dict[str, int]]
    rows_by_key: dict[str, int]


async def count_references_many(
    session: AsyncSession,
    document_ids: list[uuid.UUID],
) -> BatchReferenceCounts:
    """:func:`count_references` for a batch, per document and per row.

    The per-document half answers exactly what calling
    :func:`count_references` once per id would, and the tests hold it to that,
    but with one statement per reference and chunk instead of one per
    document: a batch delete of a few hundred drawings would otherwise be a
    few hundred round trips, each a union of thirty-four mostly unindexed
    scans.

    Scalar columns are grouped by value in SQL. The JSON array columns cannot
    be (there is no portable unnest of a ``JSON`` column), so the rows matching
    any id in the chunk come back and are attributed in Python with the same
    quoted-id match the single-id predicate applies to the serialised array.
    A row holding two ids of the batch therefore counts once against each
    document, as it would if each document were asked about on its own.

    Summing those per-document counts would count links, not rows, and the
    batch prompt says how many records lose something. So the rows are
    counted too, see :class:`BatchReferenceCounts`. Only two shapes can reach
    one row twice inside a batch: an array holding several selected ids, and a
    table with more than one document column (``StoredMaterial``,
    ``TemporaryWorksItem``). Those rows come back with their primary key and
    are counted once by it, across chunks too. A table reached through a
    single scalar column cannot repeat a row, so it keeps the grouped count.

    Documents nothing points at are absent from ``per_document``.
    """
    refs = resolved_references()
    wanted = {str(doc_id): doc_id for doc_id in document_ids}
    per_document: dict[uuid.UUID, dict[str, int]] = {}
    rows_by_key: dict[str, int] = {}
    if not refs or not wanted:
        return BatchReferenceCounts(per_document, rows_by_key)

    columns_per_table: dict[str, int] = {}
    for ref in refs:
        columns_per_table[ref.table] = columns_per_table.get(ref.table, 0) + 1

    # (table, primary key) -> (impact rank, registry position, reference key)
    # of the heaviest route found to that row so far.
    claimed: dict[tuple[str, tuple[object, ...]], tuple[int, int, str]] = {}

    def _add(doc_key: str, ref_key: str, hits: int) -> bool:
        doc_id = wanted.get(doc_key)
        if doc_id is None or hits <= 0:
            return False
        bucket = per_document.setdefault(doc_id, {})
        bucket[ref_key] = bucket.get(ref_key, 0) + hits
        return True

    def _count_rows(ref_key: str, rows: int) -> None:
        rows_by_key[ref_key] = rows_by_key.get(ref_key, 0) + rows

    def _claim(position: int, ref: DocumentReference, identity: tuple[object, ...]) -> None:
        candidate = (_IMPACT_RANK[ref.impact], position, ref.key)
        row_key = (ref.table, identity)
        current = claimed.get(row_key)
        if current is None or candidate < current:
            claimed[row_key] = candidate

    keys = list(wanted)
    for start in range(0, len(keys), _MANY_CHUNK):
        chunk = keys[start : start + _MANY_CHUNK]
        for position, ref in enumerate(refs):
            table = Base.metadata.tables[ref.table]
            col = table.c[ref.column]
            pk_cols = list(table.primary_key.columns)
            if ref.kind == "array":
                clause = or_(*(cast(col, Text).contains(f'"{key}"') for key in chunk))
                if ref.qualifier:
                    clause = clause & (table.c[ref.qualifier[0]] == ref.qualifier[1])
                rows = await session.execute(select(col, *pk_cols).where(clause))
                for row in rows.all():
                    serialised = json.dumps(row[0])
                    matched = False
                    for key in chunk:
                        if f'"{key}"' in serialised:
                            matched = _add(key, ref.key, 1) or matched
                    if not matched:
                        continue
                    if pk_cols:
                        _claim(position, ref, tuple(row[1:]))
                    else:  # pragma: no cover - every registered table has a key
                        _count_rows(ref.key, 1)
            elif columns_per_table[ref.table] > 1 and pk_cols:
                clause = col.in_(chunk)
                if ref.qualifier:
                    clause = clause & (table.c[ref.qualifier[0]] == ref.qualifier[1])
                rows = await session.execute(select(col, *pk_cols).where(clause))
                for row in rows.all():
                    if _add(str(row[0]), ref.key, 1):
                        _claim(position, ref, tuple(row[1:]))
            else:
                clause = col.in_(chunk)
                if ref.qualifier:
                    clause = clause & (table.c[ref.qualifier[0]] == ref.qualifier[1])
                rows = await session.execute(select(col, func.count()).where(clause).group_by(col))
                for value, hits in rows.all():
                    # GUID columns hand back a UUID, String columns the stored
                    # text; both stringify to the key the IN list matched on.
                    if _add(str(value), ref.key, int(hits)):
                        _count_rows(ref.key, int(hits))

    for _rank, _position, ref_key in claimed.values():
        _count_rows(ref_key, 1)
    return BatchReferenceCounts(per_document, rows_by_key)
