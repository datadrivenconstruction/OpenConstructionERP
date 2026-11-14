# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Documents demo seed - a project document register backed by real files.

What the file manager calls a folder
------------------------------------
``/files`` builds its left pane from one node per *file kind* - documents,
photos, sheets, BIM models, DWG drawings, takeoffs, reports, markups - and the
documents table tracks no sub-folder path of its own (``kind_and_path_for_document``
in ``folder_permissions_service`` states this outright). Inside the document
kind the folder is therefore the ``category`` column, and that column has a
fixed vocabulary: drawing, contract, specification, photo, correspondence,
reality_capture, other. So "a folder structure a construction project would
actually have" means coverage across those categories, plus the ISO 19650
revision chain the columns already carry - not a nested tree, which the storage
layer cannot express.

Real bytes, real sizes
----------------------
The file manager reports ``Document.file_size`` when it is non-zero and only
falls back to ``os.stat``. A row with an invented size and a path pointing at
nothing therefore shows a plausible size next to a download that 404s. Every
document written here is a file that exists: the committed reference PDFs are
copied into the same store an upload writes to, the narrative documents are
authored as real PDFs, and ``file_size`` is read back off the file on disk.
A document whose bytes cannot be produced is not written at all.

``photo`` and ``reality_capture`` are deliberately left empty. Photos are their
own file kind (and the documents service already cross-links a photo row to a
document row by shared path, so a seeded photo-category document would double up
in the tree); reality capture means scan data, and there is no scan asset to
stand behind such a row.

Idempotent per project on this seeder's own marker. A plain "the project has no
documents" test would never fire, because the demo install already writes a
handful of document rows before this ever runs.
"""

from __future__ import annotations

import logging
import shutil
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.documents.models import Document

logger = logging.getLogger(__name__)

# Marks the rows this seeder owns, so a re-run recognises its own work rather
# than the documents the demo install writes.
_SEED_SOURCE = "documents_demo_seed"

# Committed reference PDFs, already used by the takeoff and markups seeds.
_ASSET_DIR = Path(__file__).resolve().parents[2] / "scripts" / "flagship_assets"
_PLAN_SET = "house_plans.pdf"
_STANDARDS = "housing_standards.pdf"
# Two issues of one German sheet, rendered from the same geometry module by
# app/scripts/generate_grundriss_pdf.py - the pair that lets a revision chain
# show a change instead of the same page twice.
_GRUNDRISS_A = "grundriss_erdgeschoss.pdf"
_GRUNDRISS_B = "grundriss_erdgeschoss_index_b.pdf"
_GRUNDRISS_SHEET = "A-2.01"

_PDF_MIME = "application/pdf"


@dataclass(frozen=True)
class _DocSpec:
    """One document in the seeded register.

    ``asset`` names a committed PDF to copy; when it is None the document's own
    ``body`` is rendered into a PDF instead. A spec with neither is not written.
    """

    key: str
    name: str
    description: str
    category: str
    tags: list[str]
    asset: str | None = None
    body: tuple[str, ...] = ()
    discipline: str | None = None
    drawing_number: str | None = None
    revision_code: str | None = None
    cde_state: str | None = None
    suitability_code: str | None = None
    is_current_revision: bool = True
    # Key of the document this one supersedes, resolved to an id after that
    # document has been written.
    supersedes: str | None = None
    metadata: dict = field(default_factory=dict)


# The register. Ten documents across five folders, with one drawing carried
# through a full revision: the superseded issue is archived and flagged as no
# longer current, and the current issue points back at it. On the German
# showcase projects that chain is the Grundriss pair below, whose two issues
# are different drawings rather than one file filed twice.
_REGISTER: tuple[_DocSpec, ...] = (
    _DocSpec(
        key="ga-p01",
        name="General arrangement - Level 00 (P.01.01).pdf",
        description="Preliminary general arrangement issued for coordination. Superseded.",
        category="drawing",
        tags=["general arrangement", "level 00", "superseded"],
        asset=_PLAN_SET,
        discipline="architectural",
        drawing_number="A-10-001",
        revision_code="P.01.01",
        cde_state="archived",
        suitability_code="AR",
        is_current_revision=False,
    ),
    _DocSpec(
        key="ga-c01",
        name="General arrangement - Level 00 (C.01).pdf",
        description="General arrangement approved for construction. Supersedes P.01.01.",
        category="drawing",
        tags=["general arrangement", "level 00", "for construction"],
        asset=_PLAN_SET,
        discipline="architectural",
        drawing_number="A-10-001",
        revision_code="C.01",
        cde_state="published",
        suitability_code="A1",
        supersedes="ga-p01",
    ),
    _DocSpec(
        key="framing",
        name="Structural framing plan.pdf",
        description="Framing layout issued for coordination with the services model.",
        category="drawing",
        tags=["structure", "framing", "coordination"],
        asset=_PLAN_SET,
        discipline="structural",
        drawing_number="S-20-001",
        revision_code="P.02.01",
        cde_state="shared",
        suitability_code="S1",
    ),
    _DocSpec(
        key="spec-concrete",
        name="Specification - Concrete works.pdf",
        description="Materials, tolerances and testing regime for in-situ concrete.",
        category="specification",
        tags=["specification", "concrete", "testing"],
        asset=_STANDARDS,
        discipline="structural",
        revision_code="C.01",
        cde_state="published",
        suitability_code="A3",
    ),
    _DocSpec(
        key="spec-mep",
        name="Specification - Mechanical and electrical installations.pdf",
        description="Performance requirements for the services installation. Work in progress.",
        category="specification",
        tags=["specification", "mep", "draft"],
        asset=_STANDARDS,
        discipline="mechanical",
        revision_code="P.01.01",
        cde_state="wip",
        suitability_code="S0",
    ),
    _DocSpec(
        key="contract-main",
        name="Main contract - scope and conditions.pdf",
        description="Executed main contract: scope, programme obligations and payment terms.",
        category="contract",
        tags=["contract", "main", "executed"],
        body=(
            "Main contract - scope and conditions",
            "",
            "1. Scope of works",
            "The contractor carries out the whole of the permanent works described in "
            "the contract drawings and specification, together with the temporary works "
            "needed to build them.",
            "",
            "2. Programme",
            "The works are carried out in the sections set out in the accepted "
            "programme. Each section has its own completion date, and sectional "
            "completion is certified section by section.",
            "",
            "3. Payment",
            "Payment is applied for monthly against work properly executed and "
            "materials on site. Each application is valued, certified and paid within "
            "the periods stated in the contract particulars.",
            "",
            "4. Variations",
            "A variation is instructed in writing before the work is carried out. "
            "Where no rate in the bill applies, the work is valued using rates for "
            "comparable work, or as daywork where no comparable rate exists.",
            "",
            "5. Retention and defects",
            "Retention is held at the stated percentage and released in two moieties: "
            "on completion of a section and on issue of the certificate confirming "
            "that defects have been made good.",
        ),
        cde_state="published",
        suitability_code="A3",
        revision_code="C.01",
    ),
    _DocSpec(
        key="contract-groundworks",
        name="Subcontract - groundworks package.pdf",
        description="Groundworks package subcontract issued for stage approval.",
        category="contract",
        tags=["contract", "subcontract", "groundworks"],
        body=(
            "Subcontract - groundworks package",
            "",
            "1. Package scope",
            "Site clearance, bulk excavation, reduced-level dig, formation "
            "preparation, drainage below slab and backfill to the underside of the "
            "ground-bearing slab.",
            "",
            "2. Interfaces",
            "The package ends at the underside of the slab. Slab reinforcement and "
            "concrete are in the concrete frame package; ducting beyond the building "
            "line is in the external works package.",
            "",
            "3. Measurement",
            "Excavation is measured net in place, with no allowance for bulking. "
            "Disposal is measured on the same net quantities. Working space is "
            "included in the rates and is not measured separately.",
            "",
            "4. Attendance",
            "The main contractor provides site access, welfare and the setting-out "
            "grid. The subcontractor provides all plant, small tools and its own "
            "temporary works design.",
        ),
        cde_state="shared",
        suitability_code="S4",
        revision_code="P.01.02",
    ),
    _DocSpec(
        key="letter-instruction",
        name="Site instruction 014 - revised door schedule.pdf",
        description="Instruction issued to the contractor covering the revised door schedule.",
        category="correspondence",
        tags=["instruction", "doors", "issued"],
        body=(
            "Site instruction 014 - revised door schedule",
            "",
            "The door schedule has been revised following the fire strategy review. "
            "Doors on the protected corridor are now specified with a thirty-minute "
            "fire rating and cold-smoke seals.",
            "",
            "Please carry out the work described in the revised schedule issued with "
            "this instruction. The change affects ironmongery sets on the corridor "
            "doors only; the leaf sizes and structural openings are unchanged.",
            "",
            "Any cost or time consequence is to be notified within the period set out "
            "in the contract, with a build-up of the quantities affected.",
        ),
    ),
    _DocSpec(
        key="letter-early-warning",
        name="Early warning - late release of the facade design.pdf",
        description="Early warning raised on the facade design release date.",
        category="correspondence",
        tags=["early warning", "facade", "programme"],
        body=(
            "Early warning - late release of the facade design",
            "",
            "The facade design package has not yet been released for construction. "
            "The procurement route for the unitised panels needs a firm design a "
            "minimum of twelve weeks before the first delivery to site.",
            "",
            "On the current programme the first panel delivery is inside that window, "
            "so a further delay to the design release moves the start of the facade "
            "installation and, with it, the date the building becomes weathertight.",
            "",
            "This notice is issued so the matter can be discussed at the next risk "
            "reduction meeting and the options recorded before any cost is committed.",
        ),
    ),
    _DocSpec(
        key="method-facade",
        name="Method statement - facade installation.pdf",
        description="Sequence, plant and controls for installing the facade panels.",
        category="other",
        tags=["method statement", "facade", "safety"],
        body=(
            "Method statement - facade installation",
            "",
            "1. Sequence",
            "Panels are installed floor by floor, working from the lowest level "
            "upwards and from one end of each elevation to the other, so that the "
            "installed run is always closed and never leaves an open pocket.",
            "",
            "2. Plant",
            "Panels are lifted by the tower crane using a purpose-made spreader beam "
            "and vacuum lifters. A mast climbing platform provides the working "
            "position at the face.",
            "",
            "3. Controls",
            "The lifting zone is barriered at ground level for the duration of each "
            "lift. Lifts are stopped when the wind speed at the crane exceeds the "
            "limit given in the lift plan.",
            "",
            "4. Inspection",
            "Each completed bay is inspected for panel alignment, gasket seating and "
            "sealed joints before the access platform moves on, and the result is "
            "recorded against the inspection plan.",
        ),
        discipline="architectural",
    ),
)


#: The German showcase projects, matched by name because a demo install mints
#: random project ids (the takeoff seeder routes its sheets the same way).
_GERMAN_SHOWCASE_PROJECTS = frozenset(
    {
        "Bürogebäude Frankfurt Europaviertel",
        "Lebensmittelmarkt Heilbronn",
        "Lebensmittelmarkt Heidelberg",
    }
)

#: The English general-arrangement pair, which the German chain replaces on
#: those projects rather than sitting beside it as a second chain.
_ENGLISH_CHAIN_KEYS = frozenset({"ga-p01", "ga-c01"})

#: The sheet that pair files under. A written row does not carry the spec key
#: that named it, so retiring the pair on an install seeded before the German
#: chain matches on the sheet number instead. Derived from the register rather
#: than typed again, so it cannot drift away from the specs it has to match.
_ENGLISH_CHAIN_SHEET: str | None = next(
    (spec.drawing_number for spec in _REGISTER if spec.key in _ENGLISH_CHAIN_KEYS),
    None,
)

# The German projects carry the same drawing through a revision as two REALLY
# different sheets: index A and index B of A-2.01 are rendered from the same
# geometry module, and index B widened the corridor. A chain whose archived
# and current issues serve one file looks like a chain and proves nothing -
# open both and the picture is identical.
_GERMAN_REVISION_CHAIN: tuple[_DocSpec, ...] = (
    _DocSpec(
        key="gr-index-a",
        name="A-2.01 Grundriss Erdgeschoss (Index A).pdf",
        description="Ground floor plan M 1:100, first issue. Superseded by index B.",
        category="drawing",
        tags=["grundriss", "erdgeschoss", "index-A", "superseded"],
        asset=_GRUNDRISS_A,
        discipline="architectural",
        drawing_number=_GRUNDRISS_SHEET,
        revision_code="A",
        cde_state="archived",
        suitability_code="AR",
        is_current_revision=False,
    ),
    _DocSpec(
        key="gr-index-b",
        name="A-2.01 Grundriss Erdgeschoss (Index B).pdf",
        description=(
            "Ground floor plan M 1:100, index B: corridor widened to 2.50 m for the escape route, "
            "second meeting room door added. Supersedes index A."
        ),
        category="drawing",
        tags=["grundriss", "erdgeschoss", "index-B", "for construction"],
        asset=_GRUNDRISS_B,
        discipline="architectural",
        drawing_number=_GRUNDRISS_SHEET,
        revision_code="B",
        cde_state="published",
        suitability_code="A1",
        supersedes="gr-index-a",
    ),
)

#: Name, description and tags of the shared register in the languages whose demo projects would
#: otherwise read English. Keyed by language prefix of the project locale, then by spec key.
_LOCALE_TEXT: dict[str, dict[str, tuple[str, str, list[str]]]] = {
    "de": {
        "ga-p01": (
            "Grundriss Ebene 00 (P.01.01).pdf",
            "Vorentwurf des Grundrisses zur Koordination. Ersetzt.",
            ["grundriss", "ebene 00", "ersetzt"],
        ),
        "ga-c01": (
            "Grundriss Ebene 00 (C.01).pdf",
            "Zur Ausführung freigegebener Grundriss. Ersetzt P.01.01.",
            ["grundriss", "ebene 00", "zur ausführung"],
        ),
        "framing": (
            "Tragwerksplan.pdf",
            "Tragwerksplan zur Abstimmung mit dem Fachmodell Haustechnik.",
            ["tragwerk", "bauteilplan", "koordination"],
        ),
        "spec-concrete": (
            "Leistungsbeschreibung - Betonarbeiten.pdf",
            "Baustoffe, Toleranzen und Prüfumfang für Ortbeton.",
            ["leistungsbeschreibung", "beton", "prüfung"],
        ),
        "spec-mep": (
            "Leistungsbeschreibung - Technische Gebäudeausrüstung.pdf",
            "Leistungsanforderungen an die TGA-Installation. In Bearbeitung.",
            ["leistungsbeschreibung", "tga", "entwurf"],
        ),
        "contract-main": (
            "Hauptvertrag - Leistungsumfang und Bedingungen.pdf",
            "Unterzeichneter Hauptvertrag: Leistungsumfang, Terminpflichten und Zahlungsbedingungen.",
            ["vertrag", "hauptvertrag", "unterzeichnet"],
        ),
        "contract-groundworks": (
            "Nachunternehmervertrag - Erdarbeiten.pdf",
            "Nachunternehmervertrag Erdarbeiten, zur Freigabe der Leistungsphase vorgelegt.",
            ["vertrag", "nachunternehmer", "erdarbeiten"],
        ),
        "letter-instruction": (
            "Anordnung 014 - geänderte Türliste.pdf",
            "Anordnung an den Auftragnehmer zur geänderten Türliste.",
            ["anordnung", "türen", "erteilt"],
        ),
        "letter-early-warning": (
            "Behinderungsanzeige - verspätete Freigabe der Fassadenplanung.pdf",
            "Anzeige zum Freigabetermin der Fassadenplanung.",
            ["behinderungsanzeige", "fassade", "terminplan"],
        ),
        "method-facade": (
            "Montageanweisung - Fassadeneinbau.pdf",
            "Ablauf, Geräte und Schutzmaßnahmen für den Einbau der Fassadenelemente.",
            ["montageanweisung", "fassade", "arbeitssicherheit"],
        ),
    },
    "fr": {
        "ga-p01": (
            "Plan d'ensemble - Niveau 00 (P.01.01).pdf",
            "Plan d'ensemble préliminaire émis pour la coordination. Remplacé.",
            ["plan d'ensemble", "niveau 00", "remplacé"],
        ),
        "ga-c01": (
            "Plan d'ensemble - Niveau 00 (C.01).pdf",
            "Plan d'ensemble approuvé pour exécution. Remplace P.01.01.",
            ["plan d'ensemble", "niveau 00", "bon pour exécution"],
        ),
        "framing": (
            "Plan de structure.pdf",
            "Plan de structure émis pour la coordination avec la maquette des lots techniques.",
            ["structure", "ossature", "coordination"],
        ),
        "spec-concrete": (
            "CCTP - Lot béton.pdf",
            "Matériaux, tolérances et programme d'essais du béton coulé en place.",
            ["cctp", "béton", "essais"],
        ),
        "spec-mep": (
            "CCTP - Lots techniques CVC, plomberie et électricité.pdf",
            "Performances exigées des installations techniques. En cours de rédaction.",
            ["cctp", "lots techniques", "projet"],
        ),
        "contract-main": (
            "Marché principal - consistance et conditions.pdf",
            "Marché principal signé : consistance des travaux, obligations de délais et modalités de paiement.",
            ["marché", "principal", "signé"],
        ),
        "contract-groundworks": (
            "Contrat de sous-traitance - lot terrassement.pdf",
            "Contrat de sous-traitance du lot terrassement, soumis à l'agrément de la phase.",
            ["marché", "sous-traitance", "terrassement"],
        ),
        "letter-instruction": (
            "Ordre de service 014 - bordereau de portes révisé.pdf",
            "Ordre de service adressé à l'entreprise sur le bordereau de portes révisé.",
            ["ordre de service", "portes", "émis"],
        ),
        "letter-early-warning": (
            "Alerte - remise tardive des études de façade.pdf",
            "Alerte sur la date de remise des études de façade.",
            ["alerte", "façade", "planning"],
        ),
        "method-facade": (
            "Mode opératoire - pose de la façade.pdf",
            "Séquence, matériel et mesures de maîtrise pour la pose des panneaux de façade.",
            ["mode opératoire", "façade", "sécurité"],
        ),
    },
}


def _register_for(project_name: str) -> tuple[_DocSpec, ...]:
    """The register one project gets.

    German showcase projects trade the English general-arrangement pair for
    the Grundriss revision chain, so they end up with exactly one chain and
    both of its issues are the drawing they say they are.
    """
    if project_name not in _GERMAN_SHOWCASE_PROJECTS:
        return _REGISTER
    kept = tuple(spec for spec in _REGISTER if spec.key not in _ENGLISH_CHAIN_KEYS)
    return kept + _GERMAN_REVISION_CHAIN


def _localized(spec: _DocSpec, story: dict[str, Any], locale: str) -> _DocSpec:
    """The spec with the name, description and tags a demo story words in the project's language.

    The story keys ``documents`` -> document key -> ``name`` / ``description`` (a text or a language map)
    and ``tags`` (a list of texts or language maps). A key the story leaves out, or words badly, keeps
    the register's default, so a project without a story reads exactly as before.
    """
    from app.modules.project_governance.public import story_text

    rows = story.get("documents")
    row = rows.get(spec.key) if isinstance(rows, dict) else None
    if not isinstance(row, dict):
        return spec
    name = story_text(row.get("name"), locale)
    description = story_text(row.get("description"), locale)
    raw_tags = row.get("tags")
    tags = [story_text(t, locale) for t in raw_tags] if isinstance(raw_tags, list) else []
    return replace(
        spec,
        name=name or spec.name,
        description=description or spec.description,
        tags=tags if tags and all(tags) else spec.tags,
    )


def _in_locale(spec: _DocSpec, locale: str | None) -> _DocSpec:
    """The spec worded in the project's language when the locale table covers it, else unchanged."""
    row = _LOCALE_TEXT.get((locale or "en").lower()[:2], {}).get(spec.key)
    if row is None or spec.name != next((s.name for s in _REGISTER if s.key == spec.key), None):
        return spec
    name, description, tags = row
    return replace(spec, name=name, description=description, tags=list(tags))


def _safe_name(name: str) -> str:
    """A storage-safe filename, mirroring how an upload names its stored file."""
    return "".join(ch if (ch.isalnum() or ch in "-_.") else "-" for ch in name)


def _write_pdf(path: Path, lines: Iterable[str]) -> bool:
    """Author a real PDF whose text is ``lines``. False when unavailable.

    Uses reportlab, a declared base dependency. The text is the document's own
    content, so the file that lands on disk really is the document the register
    names - not a placeholder sized to look plausible.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas
    except ImportError:
        logger.info("documents seed: reportlab unavailable - narrative documents skipped")
        return False

    try:
        width, height = A4
        left = 20 * mm
        top = height - 25 * mm
        bottom = 25 * mm
        leading = 6 * mm
        wrap_at = 88

        pdf = canvas.Canvas(str(path), pagesize=A4)
        pdf.setFont("Helvetica", 10)
        cursor = top
        for raw in lines:
            chunks = _wrap(raw, wrap_at) or [""]
            for chunk in chunks:
                if cursor < bottom:
                    pdf.showPage()
                    pdf.setFont("Helvetica", 10)
                    cursor = top
                pdf.drawString(left, cursor, chunk)
                cursor -= leading
        pdf.save()
        return True
    except Exception:  # noqa: BLE001 - a seed must never break a boot
        logger.warning("documents seed: failed to author %s", path, exc_info=True)
        return False


def _wrap(text: str, width: int) -> list[str]:
    """Wrap one paragraph to ``width`` characters, preserving blank lines."""
    if not text.strip():
        return [""]
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _store(project_id: uuid.UUID, spec: _DocSpec) -> tuple[str, int] | None:
    """Materialise a document's bytes in the upload store.

    Returns ``(file_path, size_bytes)`` read back off the file that was written,
    or None when the bytes could not be produced - in which case the caller
    writes no row at all rather than a row whose size contradicts the disk.
    """
    from app.modules.documents.service import UPLOAD_BASE

    upload_dir = Path(UPLOAD_BASE) / str(project_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / f"{uuid.uuid4().hex[:12]}_{_safe_name(spec.name)}"

    if spec.asset:
        source = _ASSET_DIR / spec.asset
        if not source.exists():
            logger.warning("documents seed: asset missing %s", source)
            return None
        shutil.copyfile(source, dest)
    elif spec.body:
        if not _write_pdf(dest, spec.body):
            return None
    else:
        return None

    if not dest.exists():
        return None
    return str(dest), dest.stat().st_size


def _check_suitability(spec: _DocSpec) -> bool:
    """True when the spec's suitability code is legal for its CDE state.

    Checked against the ISO 19650 table the API itself validates against, so a
    row written straight through the ORM can never carry a combination the
    product would reject on a PATCH.
    """
    if not spec.cde_state or not spec.suitability_code:
        return True
    from app.modules.cde.suitability import validate_suitability_for_state

    ok, reason = validate_suitability_for_state(spec.suitability_code, spec.cde_state)
    if not ok:
        logger.warning("documents seed: %s has an illegal suitability code (%s)", spec.key, reason)
    return ok


async def _already_seeded(session: AsyncSession, project_id: uuid.UUID) -> bool:
    """True when this seeder has already written to the project.

    Read back and matched in Python: the demo install writes its own document
    rows first, so "the project has no documents" would never be true, and a
    JSON predicate against the metadata column compiles to a string LIKE on
    PostgreSQL.
    """
    stmt = select(Document.metadata_).where(Document.project_id == project_id)
    for metadata in (await session.execute(stmt)).scalars().all():
        if (metadata or {}).get("source") == _SEED_SOURCE:
            return True
    return False


async def _has_seeded_sheet(session: AsyncSession, project_id: uuid.UUID, drawing_number: str) -> bool:
    """True when this seeder already filed the given sheet on the project."""
    stmt = select(Document.metadata_).where(
        Document.project_id == project_id,
        Document.drawing_number == drawing_number,
    )
    return any((metadata or {}).get("source") == _SEED_SOURCE for metadata in (await session.execute(stmt)).scalars())


async def _retire_english_chain(session: AsyncSession, project_id: uuid.UUID) -> int:
    """Drop the English pair the German chain replaced. Returns rows removed.

    An install seeded before the German chain existed keeps the English
    general-arrangement pair, and that pair IS the defect the chain fixes: its
    archived and current issues serve one file, so the register shows a
    revision that changed nothing. The top-up therefore removes it instead of
    leaving it beside a chain that does the same job honestly.

    Deliberately narrow. Only rows this seeder wrote are touched, matched on
    its own marker and on the sheet number, never on a name a user could have
    typed. Only called once the German chain is confirmed on the project, so a
    register can never end up with neither chain. And a row some takeoff
    document was opened from is left alone: takeoff keeps its source as a plain
    id column with no foreign key behind it, so deleting underneath one would
    strand the measurements filed against it with nothing failing to say so.

    The files stay on disk. Each project is seeded inside a SAVEPOINT that can
    still roll back after this runs, and a surviving row whose bytes were
    deleted is a broken register, while two orphaned demo PDFs cost nothing.
    """
    if not _ENGLISH_CHAIN_SHEET:
        return 0

    stmt = select(Document).where(
        Document.project_id == project_id,
        Document.drawing_number == _ENGLISH_CHAIN_SHEET,
    )
    candidates = [
        document
        for document in (await session.execute(stmt)).scalars().all()
        if (document.metadata_ or {}).get("source") == _SEED_SOURCE
    ]
    if not candidates:
        return 0

    from app.modules.takeoff.models import TakeoffDocument

    opened_in_takeoff = set(
        (
            await session.execute(
                select(TakeoffDocument.source_document_id).where(
                    TakeoffDocument.source_document_id.in_([str(document.id) for document in candidates])
                )
            )
        )
        .scalars()
        .all()
    )

    retired = 0
    for document in candidates:
        if str(document.id) in opened_in_takeoff:
            logger.info("documents seed: keeping %s, a takeoff document was opened from it", document.id)
            continue
        await session.delete(document)
        retired += 1
    await session.flush()
    return retired


async def _seed_project(
    session: AsyncSession,
    project_id: uuid.UUID,
    owner_id: uuid.UUID,
    project_name: str,
    demo_id: str | None = None,
    locale: str | None = None,
) -> dict[str, int]:
    """Write one project's document register, or top up its revision chain."""
    empty = {"projects": 0, "documents": 0, "bytes": 0, "retired": 0}
    specs = _register_for(project_name)

    if await _already_seeded(session, project_id):
        # An install seeded before the German chain existed keeps its register;
        # only the chain is written on top, because a chain whose archived and
        # current issues serve one file is what this fixes, and re-filing the
        # other nine documents would double the register.
        specs = tuple(spec for spec in specs if spec in _GERMAN_REVISION_CHAIN)
        if not specs:
            return empty
        if await _has_seeded_sheet(session, project_id, _GRUNDRISS_SHEET):
            # The chain is already filed, which is the whole condition the
            # retire waits on, so it still runs from here. An install reseeded
            # between the chain landing and the retire landing carries both the
            # chain and the pair it replaces, and this early return is the only
            # path that install ever takes again.
            return {**empty, "retired": await _retire_english_chain(session, project_id)}

    counts = {"projects": 1, "documents": 0, "bytes": 0, "retired": 0}
    by_key: dict[str, uuid.UUID] = {}

    story: dict[str, Any] = {}
    if demo_id:
        from app.modules.project_governance.public import demo_module_story

        story = demo_module_story(demo_id, "documents")

    for spec in specs:
        if story:
            spec = _localized(spec, story, locale or "en")
        spec = _in_locale(spec, locale)
        if not _check_suitability(spec):
            continue
        stored = _store(project_id, spec)
        if stored is None:
            continue
        file_path, size_bytes = stored

        parent_id = by_key.get(spec.supersedes) if spec.supersedes else None
        document = Document(
            project_id=project_id,
            name=spec.name,
            description=spec.description,
            category=spec.category,
            file_size=size_bytes,
            mime_type=_PDF_MIME,
            file_path=file_path,
            version=1,
            uploaded_by=str(owner_id),
            tags=list(spec.tags),
            cde_state=spec.cde_state,
            suitability_code=spec.suitability_code,
            revision_code=spec.revision_code,
            drawing_number=spec.drawing_number,
            is_current_revision=spec.is_current_revision,
            parent_document_id=parent_id,
            discipline=spec.discipline,
            metadata_={"source": _SEED_SOURCE, "seed": True, "demo": True, **spec.metadata},
        )
        session.add(document)
        await session.flush()
        by_key[spec.key] = document.id
        counts["documents"] += 1
        counts["bytes"] += size_bytes

    # Retire only behind a chain that is fully on the project. Counted off the
    # keys that actually got a row, not off the specs that were meant to write
    # one: an asset that failed to store skips its spec quietly, and trading a
    # working English pair for half a German chain would leave the register
    # with no honest revision at all.
    if all(spec.key in by_key for spec in _GERMAN_REVISION_CHAIN):
        counts["retired"] = await _retire_english_chain(session, project_id)

    return counts


async def seed_documents_demo(
    session: AsyncSession,
    project_ids: Iterable[uuid.UUID],
) -> dict[str, int]:
    """Fill the document register for the demo projects.

    Only demo projects are touched: ``enrich_all`` hands this seeder every
    project in the database, including a customer's own. A project without
    ``metadata["demo_id"]`` is skipped outright - "this project has no documents"
    is not a gate, because a real project on which nobody has filed anything is
    empty by that test too.

    Args:
        session: Async DB session. The caller commits.
        project_ids: Candidate projects. Skipped when not a demo project or when
            this seeder has already written to it - except for the German
            revision chain, which is topped up on an install seeded before it
            existed so the chain there shows two different sheets.

    Returns:
        Dict with the number of projects touched, documents written, total bytes
        actually placed in the upload store, and rows retired: the English
        general-arrangement pair the German chain replaces, removed only from
        projects that now carry that chain.
    """
    totals = {"projects": 0, "documents": 0, "bytes": 0, "retired": 0}
    ids = list(project_ids)
    if not ids:
        return totals

    from app.core.demo_marker import demo_id_of
    from app.modules.projects.models import Project

    rows = (
        await session.execute(
            select(Project.id, Project.owner_id, Project.name, Project.metadata_, Project.locale).where(
                Project.id.in_(ids)
            )
        )
    ).all()

    for project_id, owner_id, project_name, metadata, locale in rows:
        if not (metadata or {}).get("demo_id"):
            continue
        if owner_id is None:
            continue
        try:
            # A SAVEPOINT per project: on PostgreSQL a failed statement aborts
            # the whole transaction, so one project that cannot be seeded would
            # otherwise take every later project down with it.
            async with session.begin_nested():
                counts = await _seed_project(
                    session, project_id, owner_id, project_name or "", demo_id_of(metadata) or None, locale
                )
        except Exception:
            logger.warning("Documents demo seed skipped for project=%s (non-fatal)", project_id, exc_info=True)
            continue
        for key, value in counts.items():
            totals[key] += value
    return totals
