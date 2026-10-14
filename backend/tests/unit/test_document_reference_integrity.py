# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pin every column that points at a document without the database enforcing it.

Thirty-four columns across twenty-one modules hold a document id that no
foreign key constrains. Six other document columns do carry one, so the
unconstrained ones are a choice made repeatedly rather than a convention the
codebase lacks: the usual reason given in the comments is portability, a
``String(36)`` being safe across PostgreSQL and SQLite without a FK.

What makes the set worth pinning is the delete path. ``delete_document``
(``documents/service.py``) removes the row unconditionally. It looks up the
document, records an activity row, calls ``repo.delete`` and unlinks the file.
It never asks whether anything still points at the id, and there is no
in_use/referenced/reference-count check anywhere in the module. Afterwards it
publishes ``documents.document.deleted`` detached, and exactly three
subscribers exist for that name: the documents module's own handler, the
file_search indexer and the file_references purger. None of those three owns
any of the thirty-four columns below.

One consumer is handled, and how it is handled is the strongest evidence that
the gap is real. ``takeoff`` has its blobs preserved by a direct call placed
inline in the delete path, and the comment there says why it is not driven off
the event: the publish is detached, so a subscriber would race the unlink and
lose nondeterministically, passing on a developer's box and failing on a
loaded one. That reasoning applies to all thirty-three other referrers equally.
They just have nobody calling for them.

So deleting a document leaves dangling ids in up to thirty-three places, and
the user is asked to confirm with a dialog whose entire text is "Delete?".

This gate does not fix that. Adding a reference-count endpoint spanning these
tables and a warning dialog naming what would break is a scoped piece of work,
and the decision about how hard to block a delete is a product one. What the
gate does is stop the set growing silently, and give that work a census to
start from. It fails in both directions: a new unconstrained document
reference fails here, and one that gains a foreign key or is removed fails
here too, so the list can never outlive what it describes.
"""

from __future__ import annotations

import pathlib
import re

_MODULES = pathlib.Path(__file__).resolve().parents[2] / "app" / "modules"

_COLUMN = re.compile(r"^\s*(\w*document_ids?)\s*:\s*Mapped\[", re.M)
_CLASS = re.compile(r"^class (\w+)\(", re.M)

# Columns carrying a document id with no ForeignKey behind them, by module.
# Keyed by owning class so that a module holding two of them stays legible and
# so the pin does not churn every time a line moves.
UNCONSTRAINED_DOCUMENT_REFERENCES: dict[str, tuple[str, ...]] = {
    "cde": ("DocumentRevision.document_id",),
    "closeout": ("CloseoutBinding.document_id",),
    "engineering_brief": ("SpecificationIssue.document_id", "Study.document_id"),
    "hse_frame": ("HseFrame.plan_document_id", "HseRole.appointment_document_id"),
    "construction_control": ("MaterialRecord.cert_document_id",),
    "contracts": (
        "ContractDocument.document_id",
        "ContractSecurity.document_id",
        "RetentionRelease.document_ids",
        "StoredMaterial.bill_of_sale_document_id",
        "StoredMaterial.delivery_ticket_document_id",
        "StoredMaterial.insurance_document_id",
        "StoredMaterial.invoice_document_id",
        "StoredMaterial.photo_document_ids",
    ),
    "correspondence": ("Correspondence.linked_document_ids",),
    "defects_liability": ("DlpWarranty.document_id",),
    "design_options": ("DesignOption.source_document_id",),
    "documents": ("ProjectPhoto.document_id", "Sheet.document_id"),
    "fieldreports": ("FieldReport.document_ids",),
    "markups": ("Markup.document_id", "ScaleConfig.document_id"),
    "meetings": ("Meeting.document_ids",),
    "plan_room": ("PlanPin.document_id",),
    "portal": ("PortalDocumentAccessLog.document_id",),
    "punchlist": ("PunchItem.document_id",),
    "qms": ("QMSInspection.attachment_document_ids", "QMSInspectionAttachment.document_id"),
    "resumable_uploads": ("ResumableUploadSession.document_id",),
    "takeoff": (
        "AiTakeoffRun.document_id",
        "TakeoffDocument.source_document_id",
        "TakeoffMeasurement.document_id",
    ),
    "tax_withholding": ("PartyTaxStatus.evidence_document_id",),
    "temporary_works": (
        "TemporaryWorksItem.check_certificate_document_id",
        "TemporaryWorksItem.design_document_id",
    ),
    "transmittals": ("TransmittalItem.document_id",),
    "variations": ("VariationRequest.source_document_id",),
}


def _balanced_call(source: str, start: int) -> str:
    """Return the ``mapped_column(...)`` text starting at the first paren."""
    open_at = source.index("(", start)
    depth, i = 0, open_at
    while i < len(source):
        if source[i] == "(":
            depth += 1
        elif source[i] == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    return source[open_at : i + 1]


def _census() -> dict[str, set[str]]:
    """Find every document-id column that no ForeignKey constrains."""
    found: dict[str, set[str]] = {}
    scanned = 0
    for path in sorted(_MODULES.rglob("*.py")):
        if "__pycache__" in str(path) or "models" not in path.name:
            continue
        scanned += 1
        source = path.read_text(encoding="utf-8", errors="ignore")
        module = path.relative_to(_MODULES).parts[0]
        classes = [(m.start(), m.group(1)) for m in _CLASS.finditer(source)]
        for match in _COLUMN.finditer(source):
            owner = "?"
            for position, name in classes:
                if position < match.start():
                    owner = name
                else:
                    break
            if "ForeignKey" in _balanced_call(source, match.end()):
                continue
            found.setdefault(module, set()).add(f"{owner}.{match.group(1)}")
    assert scanned > 100, f"scanned only {scanned} model files - the instrument is broken"
    return found


def test_census_finds_a_real_population() -> None:
    """Print the denominator beside the verdict, so an empty sweep cannot pass.

    An earlier draft of this scan compiled its pattern without ``re.MULTILINE``,
    so ``^`` matched only at the start of each file and the census came back
    empty. Zero findings look exactly like a clean tree.
    """
    census = _census()
    total = sum(len(v) for v in census.values())
    assert total > 20, f"census found only {total} references - the instrument is broken"


def test_no_new_unconstrained_document_references() -> None:
    """A new dangling-by-design document reference must be a decision."""
    census = _census()
    pinned = {module: set(columns) for module, columns in UNCONSTRAINED_DOCUMENT_REFERENCES.items()}

    added = {
        module: sorted(columns - pinned.get(module, set()))
        for module, columns in census.items()
        if columns - pinned.get(module, set())
    }
    assert not added, (
        f"new document references with no foreign key behind them: {added}. "
        f"delete_document removes the row without checking for referrers, so these "
        f"ids dangle. Add a foreign key, or pin the column here with the others."
    )

    removed = {
        module: sorted(columns - census.get(module, set()))
        for module, columns in pinned.items()
        if columns - census.get(module, set())
    }
    assert not removed, (
        f"these pinned references are gone or now carry a foreign key: {removed}. "
        f"Delete their entries - the pin must not outlive what it describes."
    )


def test_pinned_modules_all_exist() -> None:
    """A pin naming a module that no longer ships is a pin nobody is reading."""
    missing = sorted(m for m in UNCONSTRAINED_DOCUMENT_REFERENCES if not (_MODULES / m).is_dir())
    assert not missing, f"pinned modules that do not exist: {missing}"


# ── The runtime registry, gated against the census above ────────────────────
#
# ``app.modules.documents.references`` is what the delete prompt actually
# queries. It is curated rather than derived from column names, because in
# this codebase the name does not settle the meaning: ``EInvoiceEvent``
# carries a ``document_id`` pointing at ``oe_einvoice_clearance_document``,
# and ``PortalDocumentAccessLog.document_id`` is polymorphic, qualified by a
# free-form ``document_type`` the API accepts from the caller.
#
# Curation buys precision and costs drift, so these tests pay the cost back.
# The registry has to agree with the regex census above AND with the ORM
# metadata, and its impact classification has to agree with what the schema
# actually permits. Each of the three fails in both directions.


def _all_models_imported() -> None:
    """Populate ``Base.metadata`` with every module's tables.

    The registry resolves against the metadata, so a half-imported one would
    make entries silently drop out and read as "missing" here.
    """
    import importlib

    backend = _MODULES.parents[1]
    for path in sorted(_MODULES.rglob("*.py")):
        if "__pycache__" in str(path) or "models" not in path.name:
            continue
        importlib.import_module(".".join(path.relative_to(backend).with_suffix("").parts))


#: The two entries that keep a document id on purpose, and why. Anything else
#: classified ``retains`` is unexplained, and anything here that stops being
#: ``retains`` has lost its reason.
_RETAINS_BY_DESIGN = {
    "PortalDocumentAccessLog.document_id": "append-only audit log - the id it recorded is the record",
    "TakeoffDocument.source_document_id": "preserve_blobs_for_deleted_source hands takeoff its own copy",
}


def test_registry_covers_exactly_the_census() -> None:
    """The queried set and the pinned set are the same set."""
    from app.modules.documents.references import DOCUMENT_REFERENCES

    census = {f"{module}:{column}" for module, columns in _census().items() for column in columns}
    registry = {f"{ref.module}:{ref.model}.{ref.column}" for ref in DOCUMENT_REFERENCES}

    missing = sorted(census - registry)
    assert not missing, (
        f"these references are pinned but the delete prompt never asks them: {missing}. "
        f"Add them to DOCUMENT_REFERENCES, or the warning under-reports."
    )

    extra = sorted(registry - census)
    assert not extra, (
        f"the delete prompt queries references the census does not know: {extra}. "
        f"Either the column gained a foreign key and the entry is stale, or the "
        f"census pin is missing."
    )


def test_registry_entries_resolve_and_carry_no_foreign_key() -> None:
    """Every entry names a real column, and none of them is constrained.

    A column that gains a foreign key stops belonging here: the database will
    cascade or refuse on its own, and counting it would tell the user about a
    link the engine already handles.
    """
    _all_models_imported()

    from app.database import Base
    from app.modules.documents.references import DOCUMENT_REFERENCES

    unresolved, constrained = [], []
    for ref in DOCUMENT_REFERENCES:
        table = Base.metadata.tables.get(ref.table)
        if table is None or ref.column not in table.c:
            unresolved.append(f"{ref.key} ({ref.table}.{ref.column})")
            continue
        if table.c[ref.column].foreign_keys:
            constrained.append(ref.key)
        if ref.qualifier and ref.qualifier[0] not in table.c:
            unresolved.append(f"{ref.key} qualifier {ref.qualifier[0]}")

    assert not unresolved, f"registry entries naming columns that do not exist: {unresolved}"
    assert not constrained, f"these now carry a foreign key and no longer belong in the registry: {constrained}"


def test_impact_matches_what_the_schema_permits() -> None:
    """``strands`` means NOT NULL, and the exceptions are named.

    The classification is what the user is shown, so it cannot be a matter of
    taste. A nullable column lets the row record the loss; a NOT NULL one does
    not, and that is the whole difference between "loses the attachment" and
    "left pointing at nothing". The only entries allowed to ignore nullability
    are the two that keep the id deliberately.
    """
    _all_models_imported()

    from app.database import Base
    from app.modules.documents.references import DOCUMENT_REFERENCES

    retains = {ref.key for ref in DOCUMENT_REFERENCES if ref.impact == "retains"}
    assert retains == set(_RETAINS_BY_DESIGN), (
        f"entries classified 'retains' without a recorded reason, or a reason "
        f"whose entry changed: registry={sorted(retains)} "
        f"documented={sorted(_RETAINS_BY_DESIGN)}"
    )

    wrong = []
    for ref in DOCUMENT_REFERENCES:
        if ref.key in _RETAINS_BY_DESIGN:
            continue
        column = Base.metadata.tables[ref.table].c[ref.column]
        # An array column is NOT NULL as a column while still letting an
        # element be dropped, so nullability says nothing about it.
        expected = "strands" if (ref.kind == "scalar" and not column.nullable) else "unlinks"
        if ref.impact != expected:
            wrong.append(f"{ref.key}: classified {ref.impact}, schema says {expected}")

    assert not wrong, "impact classifications that disagree with the column definition: " + "; ".join(wrong)
