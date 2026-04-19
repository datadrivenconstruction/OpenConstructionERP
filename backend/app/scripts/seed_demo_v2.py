"""Seed 5 fully-localized demo projects across US / DE / ES / BR / CN.

This is the v2 demo seeder. It supersedes ``seed_demo_showcase.py`` with
a deeper, more realistic data set:

  * 5 projects, one per country/language/currency/standard combo
  * Each project's BOQ structure is **driven from the uploaded CAD model**
    — element categories become BOQ sections, grouped quantities feed
    position quantities, and the entire group of elements is linked to
    the position it produced (group-link, not 1-to-1).
  * Every text field rendered to the user (project name, descriptions,
    section headings, position descriptions, contact names, task titles,
    transmittal subjects, finance line items, validation rule selection)
    is in the project's locale.
  * Other modules also get realistic data: contacts, tasks, field
    reports, finance (invoices + budgets), transmittals, BOQ markups,
    validation runs.

End-to-end flow
---------------

  1. Auth (or register) the seed admin user, promote to role=admin.
  2. Wipe every existing project (cascade clears BOQ/BIM/links/etc).
  3. For each of the 5 project specs:
       a. Create the project with locale + currency + classification.
       b. Seed contacts (companies + people in country-appropriate
          names).
       c. Seed tasks (kanban — mix of statuses).
       d. Seed field reports (a few daily logs).
       e. Seed finance (invoices + budget lines).
       f. Upload the CAD model and kick off conversion.
  4. Wait for every CAD model to reach status=ready.
  5. For each ready model:
       a. Fetch every element.
       b. Group by element_type → bucket by storey when useful.
       c. For each bucket, create a BOQ section (locale-aware label),
          create a position with summed quantities (volume / area /
          length / count whichever is most informative for the type),
          and link every element in the bucket to that position.
  6. Seed transmittals + markups now that BOQ exists.
  7. Run validation per project, leaving a realistic mix of pass /
     warning / error in the dashboard.
  8. Print a summary: per-project URLs to dashboard / BOQ / BIM viewer.

Issues encountered while running are appended to
``backend/app/scripts/demo_seed_issues.md`` for the post-seed audit.

Usage
-----

    python -m app.scripts.seed_demo_v2

Assumes the backend is running on http://localhost:8000.  Safe to
re-run — the wipe step is idempotent.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import pathlib
import shutil
import sqlite3
import sys
import time
import traceback
import uuid
from typing import Any

import httpx

# Windows console defaults to cp1252 — force utf-8 so Chinese / Cyrillic
# / accented Latin characters in localized strings don't blow up print().
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ── Configuration ─────────────────────────────────────────────────────────

BASE = "http://localhost:8000"
ADMIN_EMAIL = "admin@openestimate.io"
ADMIN_PASSWORD = "OpenEstimate2026"

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
CAD_SOURCE_DIR = pathlib.Path(
    r"C:\Users\Artem Boiko\Downloads\cad2data-Revit-IFC-DWG-DGN-main"
    r"\cad2data-Revit-IFC-DWG-DGN-main\Sample_Projects\test"
)
BIM_DATA_DIR = REPO_ROOT / "backend" / "data" / "bim"
ISSUES_FILE = REPO_ROOT / "backend" / "app" / "scripts" / "demo_seed_issues.md"

# CAD upload poll settings
MODEL_READY_TIMEOUT_S = 600  # 10 min per CAD file (RVT is the slow one)
MODEL_POLL_INTERVAL_S = 5

# Today's date used as the anchor for invoice / FR / task date computation —
# pinned so re-runs produce stable output and the dashboard always shows
# data clustered around "now-ish".
TODAY = dt.date.today()


# ── Issues log ────────────────────────────────────────────────────────────

def log_issue(severity: str, title: str, found: str, symptom: str,
              workaround: str, fix_later: str) -> None:
    """Append a single issue entry to the issues markdown file."""
    block = (
        f"\n## [{severity}] {title}\n"
        f"- **Found**: {found}\n"
        f"- **Symptom**: {symptom}\n"
        f"- **Workaround**: {workaround}\n"
        f"- **Fix later**: {fix_later}\n"
    )
    try:
        with ISSUES_FILE.open("a", encoding="utf-8") as fh:
            fh.write(block)
    except Exception:  # never let logging crash the seeder
        pass


# ── Localization tables ───────────────────────────────────────────────────
#
# One block per project locale.  Holds every user-facing string the
# seeder needs to render.  Adding a 6th locale = adding a 6th block.
#
# Keys are stable across locales so the seeder code is locale-agnostic.

LOCALES: dict[str, dict[str, Any]] = {
    # ── United States — English / USD / MasterFormat ─────────────────
    "en": {
        "country_label": "United States",
        # Generic UI labels used in seeded data
        "boq_name": "Bill of Quantities — Main Trades",
        "boq_description": (
            "Element-by-element quantity takeoff derived from the BIM "
            "model, organized per MasterFormat division."
        ),
        # Element-type → section info.  `section_code` is the
        # MasterFormat-style ordinal and `unit` is the unit chosen for
        # the section heading (positions use the most-informative unit
        # the elements provide).
        "element_categories": {
            "Walls":      ("03 30 00", "Cast-in-Place Concrete — Walls",     "sf"),
            "Floors":     ("03 31 00", "Structural Concrete — Floors",       "sf"),
            "Roofs":      ("07 50 00", "Membrane Roofing",                   "sf"),
            "Doors":      ("08 11 00", "Metal Doors and Frames",             "ea"),
            "Windows":    ("08 50 00", "Windows",                            "ea"),
            "Columns":    ("03 30 00", "Cast-in-Place Concrete — Columns",   "ea"),
            "Stairs":     ("03 30 00", "Cast-in-Place Concrete — Stairs",    "ea"),
            "Ceilings":   ("09 50 00", "Ceilings",                           "sf"),
            "Furniture":  ("12 50 00", "Furniture",                          "ea"),
            "Railings":   ("05 50 00", "Metal Fabrications — Railings",      "lf"),
            "Generic Models":   ("01 10 00", "General Requirements",         "ea"),
            "Structural Framing": ("05 12 00", "Structural Steel Framing",   "lf"),
            "Structural Foundations": ("03 30 00", "Concrete Foundations",   "cy"),
            "Structural Columns": ("03 30 00", "Concrete Columns",           "ea"),
            "Curtain Walls": ("08 44 00", "Curtain Wall Assemblies",         "sf"),
            "Curtain Panels": ("08 44 13", "Curtain Wall Glazing Panels",    "sf"),
            "Curtain Wall Mullions": ("08 44 16", "Curtain Wall Mullions",   "lf"),
            "Mass": ("01 10 00", "Building Massing",                          "ea"),
            "Site": ("31 10 00", "Site Clearing",                             "ls"),
            "Topography": ("31 22 00", "Grading",                             "ea"),
            # IFC equivalents
            "IfcWall":            ("03 30 00", "Cast-in-Place Concrete — Walls",   "sf"),
            "IfcWallStandardCase": ("03 30 00", "Cast-in-Place Concrete — Walls",  "sf"),
            "IfcSlab":            ("03 31 00", "Structural Concrete — Slabs",      "sf"),
            "IfcRoof":            ("07 50 00", "Membrane Roofing",                 "sf"),
            "IfcDoor":            ("08 11 00", "Metal Doors and Frames",           "ea"),
            "IfcWindow":          ("08 50 00", "Windows",                          "ea"),
            "IfcColumn":          ("03 30 00", "Cast-in-Place Concrete — Columns", "ea"),
            "IfcBeam":            ("05 12 00", "Structural Steel Framing",         "lf"),
            "IfcMember":          ("05 12 00", "Structural Steel Members",         "ea"),
            "IfcStair":           ("03 30 00", "Cast-in-Place Concrete — Stairs",  "ea"),
            "IfcSpace":           ("01 10 00", "Spaces (informational)",           "sf"),
            "IfcOpeningElement":  ("08 11 00", "Openings",                         "ea"),
            "IfcRailing":         ("05 50 00", "Metal Fabrications — Railings",    "lf"),
            "IfcVirtualElement":  ("01 10 00", "Reference Geometry (informational)", "ea"),
        },
        "fallback_section": ("01 90 00", "General — Other Elements", "ea"),
        # Unit-rate hint per section (USD).  Multiplied by the bucket
        # quantity to populate `unit_rate` and seed a believable cost.
        "unit_rates": {
            "03 30 00": 28.50,   # concrete per cy/sf depending on unit
            "03 31 00": 12.00,
            "05 12 00": 65.00,
            "05 50 00": 95.00,
            "07 50 00": 14.00,
            "08 11 00": 950.00,
            "08 44 00": 110.00,
            "08 44 13": 105.00,
            "08 44 16": 75.00,
            "08 50 00": 720.00,
            "09 50 00": 8.50,
            "12 50 00": 480.00,
            "31 10 00": 12000.00,
            "31 22 00": 5500.00,
            "01 10 00": 25.00,
            "01 90 00": 25.00,
        },
        # Project metadata
        "project": {
            "name": "Boylston Crossing — Boston Mixed-Use",
            "description": (
                "8-story mixed-use development at the corner of Boylston St "
                "and Massachusetts Ave. Ground-floor retail (1,400 sf), 7 "
                "floors of class-A office and amenity (47,500 gsf). Steel "
                "frame on cast-in-place piles, curtain wall envelope. "
                "Targeting LEED Gold."
            ),
            "address": {
                "street": "412 Boylston Street",
                "city": "Boston",
                "state": "MA",
                "country": "USA",
                "postal_code": "02116",
            },
            "project_code": "US-2026-001",
            "project_type": "commercial",
            "phase": "design",
            "budget_estimate": "32500000",
            "contingency_pct": "8",
            "contract_value": "29200000",
            "planned_start_date": "2026-06-01",
            "planned_end_date": "2028-04-30",
            "actual_start_date": None,
            "actual_end_date": None,
        },
        # Contacts: tuple of (contact_type, company_name, first_name?, last_name?, email, role_label)
        "contacts": [
            ("client",        "Boylston Crossing LLC",          None,        None,        "info@boylstoncrossing.com",   "Owner"),
            ("client",        "Boylston Crossing LLC",          "Sarah",     "Whitfield", "sarah@boylstoncrossing.com",  "Owner's Project Manager"),
            ("consultant",    "Hartman Architects",             None,        None,        "office@hartman-arch.com",      "Architect of Record"),
            ("consultant",    "Hartman Architects",             "Daniel",    "Hartman",   "d.hartman@hartman-arch.com",   "Principal Architect"),
            ("consultant",    "LeMessurier Associates",         "Robert",    "Liu",       "rliu@lemessurier.com",         "Structural Engineer"),
            ("subcontractor", "Suffolk Construction",           None,        None,        "preconstruction@suffolk.com",  "General Contractor"),
            ("subcontractor", "JM Coull Inc.",                  "Michael",   "Coull",     "mcoull@jmcoull.com",           "Concrete Subcontractor"),
            ("supplier",      "Bay State Steel Supply",         "Jennifer",  "OBrien",    "j.obrien@baystatesteel.com",   "Structural Steel Supplier"),
            ("supplier",      "New England Glass Works",        "Tom",       "Patel",     "tpatel@neglassworks.com",      "Glazing Supplier"),
        ],
        # Tasks (status, task_type, title, description)
        "tasks": [
            ("draft",       "task",          "Coordinate steel shop drawings with curtain wall vendor",
             "RFI #042 highlighted a clearance issue between the perimeter beam and the curtain wall anchor; need a coordination meeting before steel is fabricated."),
            ("open",        "decision",      "Decide on roof membrane system (TPO vs PVC)",
             "TPO is 12% cheaper per sf but PVC has the better track record on similar Boston-climate projects. Need owner input by end of week."),
            ("open",        "task",          "Submit foundation permit set to Boston ISD",
             "Soil report and pile design are complete; package needs sign-off from structural before submission."),
            ("in_progress", "task",          "Finalize MEP routing through level 3 transfer beams",
             "MEP coordinator working with structural to clear conduit paths; expected resolution next sprint."),
            ("in_progress", "topic",         "Permit comments — life safety review",
             "Boston Fire requested two additional standpipes on the south stair; awaiting cost impact estimate."),
            ("completed",   "task",          "Issue 100% schematic design package",
             "Issued to owner for pricing; cost engineer's preliminary GMP came in 3% under target."),
            ("completed",   "task",          "Geotechnical investigation — borings B-1 through B-12",
             "12 borings to refusal; report received and incorporated into foundation design."),
            ("completed",   "personal",      "Site walk with civil engineer",
             "Walked existing storm utilities; will need to relocate a catch basin near the loading dock."),
        ],
        # Field reports
        "field_reports": [
            (1, "daily", "clear",   18, "Foundations crew set rebar mat at column lines D-G. Concrete pour scheduled for tomorrow pending weather."),
            (3, "daily", "cloudy",  15, "Excavation crew reached design grade at the south half of the site. Encountered minor unsuitable soil; civil notified."),
            (5, "safety","clear",   20, "Weekly toolbox talk: working at heights. All trades present, sign-in attached. No incidents this week."),
            (8, "concrete_pour","clear", 22, "Pour: 145 cy of 5000 psi mix for footings F-1 through F-9. Slump tests OK, cylinders cast for 7/28-day breaks."),
        ],
        # Finance
        "finance": {
            "budget_categories": [
                ("labor",         "8400000",  "8400000",  "1250000", "1250000", "8400000"),
                ("material",      "11200000", "11650000", "2100000", "2100000", "11650000"),
                ("equipment",     "1800000",  "1800000",  "320000",  "320000",  "1800000"),
                ("subcontractor", "8500000",  "8500000",  "1100000", "1100000", "8500000"),
                ("overhead",      "1900000",  "1900000",  "210000",  "210000",  "1900000"),
                ("contingency",   "2700000",  "2250000",  "0",       "0",       "2250000"),
            ],
            "invoices": [
                # (direction, invoice_number, amount_subtotal, days_offset_from_today, description, status)
                ("payable",    "JMC-2026-0014", "385000.00",  -45, "Cast-in-place concrete progress invoice #1",     "approved"),
                ("payable",    "JMC-2026-0021", "412500.00",  -15, "Cast-in-place concrete progress invoice #2",     "approved"),
                ("payable",    "BSS-2026-0089", "248000.00",  -7,  "Structural steel — fabrication advance",          "pending"),
                ("receivable", "INV-OWN-0007",  "950000.00",  -30, "Owner draw #7 — design phase services",          "paid"),
                ("payable",    "HART-2026-04",  "78500.00",   -2,  "Architectural services — April",                 "pending"),
            ],
        },
        # Transmittals (subject, purpose_code, days_offset)
        "transmittals": [
            ("Issue for Construction — Foundations Package (FND-100)",   "for_construction", -20),
            ("Curtain Wall Shop Drawings — Submittal #03",                "for_review",       -8),
            ("Owner's Request for Information — Loading Dock Capacity",    "for_information",  -3),
        ],
        # BOQ markups — financial markups added on top of direct cost
        "boq_markups": [
            ("General Conditions",          "percentage", "overhead",    7.0),
            ("Contractor's Fee",             "percentage", "profit",      4.5),
            ("Builder's Risk Insurance",     "percentage", "insurance",   1.2),
            ("Performance Bond",             "percentage", "bond",        1.5),
        ],
        # Validation rule sets to invoke for this project
        # Only `boq_quality`, `din276`, `gaeb` are registered as rule
        # set prefixes in app/core/validation/rules/__init__.py.  No
        # `masterformat` or `nrm` rules exist yet — for the US project
        # we run only the universal quality checks.
        "validation_rule_sets": ["boq_quality"],
    },

    # ── Germany — German / EUR / DIN 276 ─────────────────────────────
    "de": {
        "country_label": "Deutschland",
        "boq_name": "Leistungsverzeichnis — Hauptgewerke",
        "boq_description": (
            "Element-Mengenermittlung aus dem BIM-Modell, gegliedert "
            "nach Kostengruppen DIN 276."
        ),
        "element_categories": {
            "Walls":      ("330", "Außenwände — Stahlbeton",                "m²"),
            "Floors":     ("350", "Decken — Stahlbeton",                    "m²"),
            "Roofs":      ("360", "Dächer — Flachdach",                     "m²"),
            "Doors":      ("344", "Innentüren",                             "Stk"),
            "Windows":    ("334", "Fenster — Außenwände",                   "Stk"),
            "Columns":    ("331", "Tragende Stützen",                       "Stk"),
            "Stairs":     ("351", "Treppen",                                "Stk"),
            "Ceilings":   ("353", "Deckenbeläge",                           "m²"),
            "Furniture":  ("611", "Allgemeine Ausstattung",                 "Stk"),
            "Railings":   ("352", "Geländer",                               "m"),
            "Generic Models":   ("100", "Grundstück (allg.)",               "Stk"),
            "Structural Framing": ("331", "Tragwerk Stahl",                 "m"),
            "Structural Foundations": ("320", "Gründung",                   "m³"),
            "Structural Columns": ("331", "Stützen",                        "Stk"),
            "Curtain Walls": ("334", "Vorhangfassade",                      "m²"),
            "Curtain Panels": ("334", "Fassadenpaneele",                    "m²"),
            "Curtain Wall Mullions": ("334", "Fassadenpfosten",             "m"),
            "Mass": ("100", "Gebäudemasse",                                  "Stk"),
            "Site": ("210", "Erschließung",                                 "psch"),
            "Topography": ("210", "Geländearbeiten",                        "Stk"),
            "IfcWall":            ("330", "Außenwände — Stahlbeton",        "m²"),
            "IfcWallStandardCase": ("330", "Außenwände — Stahlbeton",       "m²"),
            "IfcSlab":            ("350", "Decken — Stahlbeton",            "m²"),
            "IfcRoof":            ("360", "Dächer",                          "m²"),
            "IfcDoor":            ("344", "Innentüren",                     "Stk"),
            "IfcWindow":          ("334", "Fenster",                        "Stk"),
            "IfcColumn":          ("331", "Tragende Stützen",               "Stk"),
            "IfcBeam":            ("331", "Tragende Träger",                "m"),
            "IfcMember":          ("331", "Tragende Bauteile",              "Stk"),
            "IfcStair":           ("351", "Treppen",                        "Stk"),
            "IfcSpace":           ("100", "Räume (informativ)",             "m²"),
            "IfcOpeningElement":  ("344", "Öffnungen",                      "Stk"),
            "IfcRailing":         ("352", "Geländer",                       "m"),
            "IfcVirtualElement":  ("100", "Hilfsgeometrie (informativ)",    "Stk"),
        },
        "fallback_section": ("390", "Sonstige Baukonstruktionen", "Stk"),
        "unit_rates": {
            "210": 12000.00,
            "320": 285.00,
            "330": 95.00,
            "331": 1450.00,
            "334": 380.00,
            "344": 420.00,
            "350": 110.00,
            "351": 4200.00,
            "352": 145.00,
            "353": 32.00,
            "360": 165.00,
            "611": 280.00,
            "100": 25.00,
            "390": 25.00,
        },
        "project": {
            "name": "Wohnpark Friedrichshain — Berlin",
            "description": (
                "Wohnungsneubau mit gemischter Nutzung. 4 Vollgeschosse, "
                "BGF ca. 2.140 m², 28 Wohneinheiten + Gewerbefläche im "
                "Erdgeschoss. KFW-40 Standard, mit Tiefgarage. "
                "Demo-Projekt aus IFC-Quellmodell (FZK-Haus)."
            ),
            "address": {
                "street": "Boxhagener Straße 47",
                "city": "Berlin",
                "state": "Berlin",
                "country": "Deutschland",
                "postal_code": "10245",
            },
            "project_code": "DE-2026-001",
            "project_type": "residential",
            "phase": "design",
            "budget_estimate": "8400000",
            "contingency_pct": "10",
            "contract_value": "7650000",
            "planned_start_date": "2026-08-01",
            "planned_end_date": "2028-02-28",
            "actual_start_date": None,
            "actual_end_date": None,
        },
        "contacts": [
            ("client",        "Friedrichshain Wohnbau GmbH",   None,        None,        "info@fhain-wohnbau.de",       "Bauherr"),
            ("client",        "Friedrichshain Wohnbau GmbH",   "Annika",    "Zimmermann","a.zimmermann@fhain-wohnbau.de","Projektleiterin Bauherrschaft"),
            ("consultant",    "Müller + Partner Architekten",  None,        None,        "buero@mueller-partner.de",     "Architekturbüro"),
            ("consultant",    "Müller + Partner Architekten",  "Stefan",    "Müller",    "s.mueller@mueller-partner.de", "Geschäftsführender Architekt"),
            ("consultant",    "Schmitt Tragwerksplanung",      "Heinrich",  "Schmitt",   "h.schmitt@schmitt-tw.de",      "Tragwerksplaner"),
            ("subcontractor", "Hauser Bau GmbH",               None,        None,        "info@hauser-bau.de",           "Generalunternehmer"),
            ("subcontractor", "Berliner Rohbau GmbH",          "Klaus",     "Hoffmann",  "k.hoffmann@berliner-rohbau.de","Rohbauunternehmer"),
            ("supplier",      "Heidelberger Beton AG",         "Petra",     "Bauer",     "p.bauer@heidelberger-beton.de","Betonlieferant"),
            ("supplier",      "Schüco Fenster + Fassaden",     "Markus",    "Wagner",    "m.wagner@schueco.de",          "Fensterlieferant"),
        ],
        "tasks": [
            ("draft",       "task",        "Statik prüfen — Lasteneintrag Tiefgaragenwand",
             "Tragwerksplaner hat Lastannahme der UG-Wand erhöht. Prüfung der Bewehrung erforderlich."),
            ("open",        "decision",    "Entscheidung Heizungssystem (Wärmepumpe vs Fernwärme)",
             "Wirtschaftlichkeitsvergleich liegt vor. Bauherr muss vor Werkplanung entscheiden."),
            ("open",        "task",        "Bauantrag bei Bezirksamt Friedrichshain einreichen",
             "Statik und Energieausweis liegen vor; Antragsmappe muss zusammengestellt werden."),
            ("in_progress","task",        "TGA-Koordinierung Sanitär / Heizung im Decken-Hohlraum",
             "Konflikt zwischen Lüftungskanal und Heizungsleitungen in der Decke EG/1.OG."),
            ("in_progress","topic",       "Brandschutzgutachten — Stellungnahme zu Fluchtweglängen",
             "Sachverständiger fordert zusätzlichen Rauchabzug im Treppenhaus B."),
            ("completed",   "task",        "Bauvoranfrage genehmigt",
             "Bezirksamt hat Vorbescheid mit kleineren Auflagen erteilt. Weiterplanung freigegeben."),
            ("completed",   "task",        "Baugrunduntersuchung — 8 Sondierungen",
             "Bohrungen bis 12 m abgeteuft, Gutachten liegt vor; Pfahlgründung empfohlen."),
            ("completed",   "personal",    "Ortsbegehung mit Vermessungsbüro",
             "Bestandsaufnahme der Nachbarbebauung und Höhenbezug zum Straßenniveau."),
        ],
        "field_reports": [
            (1, "daily", "clear",  14, "Erdarbeiten Achsen A–C abgeschlossen. Aushub abgefahren, Sohle liegt 50 cm tief als geplant — Geotechnik informiert."),
            (3, "daily", "cloudy",  9, "Bewehrung Bodenplatte verlegt, Achsen A–E. Werkprüfung durch Polier dokumentiert."),
            (5, "safety","clear",  16, "Wöchentliche Sicherheitsunterweisung: Arbeiten in Höhe. Alle Gewerke anwesend, Anwesenheitsliste anbei."),
            (8, "concrete_pour","clear", 18, "Betonage 110 m³ C30/37 Bodenplatte. Setzmaß ok, 6 Probewürfel für 7/28-Tage-Festigkeitsprüfung."),
        ],
        "finance": {
            "budget_categories": [
                ("labor",         "1900000", "1900000", "180000", "180000", "1900000"),
                ("material",      "2700000", "2825000", "420000", "420000", "2825000"),
                ("equipment",     "420000",  "420000",  "62000",  "62000",  "420000"),
                ("subcontractor", "2400000", "2400000", "180000", "180000", "2400000"),
                ("overhead",      "480000",  "480000",  "45000",  "45000",  "480000"),
                ("contingency",   "500000",  "375000",  "0",      "0",      "375000"),
            ],
            "invoices": [
                ("payable",    "BR-2026-0008", "94500.00",  -42, "Rohbauarbeiten — Abschlagsrechnung 1",        "approved"),
                ("payable",    "BR-2026-0014", "112000.00", -12, "Rohbauarbeiten — Abschlagsrechnung 2",        "approved"),
                ("payable",    "HBT-2026-031", "38500.00",  -5,  "Beton C30/37 — Lieferschein April",            "pending"),
                ("receivable", "RG-FW-0003",   "240000.00", -28, "Honorar Bauherr — Vorentwurf bis Genehmigung","paid"),
                ("payable",    "MUE-2026-04",  "22800.00",  -2,  "Architektenhonorar — April",                  "pending"),
            ],
        },
        "transmittals": [
            ("Ausführungsplanung Rohbau — Freigabe FRG-100",       "for_construction", -22),
            ("Werkplanung Fassade — Vorabzug zur Stellungnahme",   "for_review",       -10),
            ("Bauherrenanfrage — Ausstattungsstandard Bäder",       "for_information",  -4),
        ],
        "boq_markups": [
            ("Baustellen­einrichtung",   "percentage", "overhead",    6.0),
            ("Wagnis und Gewinn",        "percentage", "profit",      5.0),
            ("Bauversicherung",          "percentage", "insurance",   1.0),
            ("Bauwesensbürgschaft",      "percentage", "bond",        1.5),
        ],
        "validation_rule_sets": ["din276", "gaeb", "boq_quality"],
    },

    # ── Spain — Spanish / EUR / Custom ───────────────────────────────
    "es": {
        "country_label": "España",
        "boq_name": "Mediciones y Presupuesto — Obras Principales",
        "boq_description": (
            "Mediciones automáticas extraídas del modelo BIM, organizadas "
            "por capítulos según la estructura del proyecto."
        ),
        "element_categories": {
            "Walls":      ("04", "Cerramientos exteriores",        "m²"),
            "Floors":     ("05", "Forjados y losas",                "m²"),
            "Roofs":      ("07", "Cubiertas",                       "m²"),
            "Doors":      ("09", "Carpintería interior",            "ud"),
            "Windows":    ("08", "Carpintería exterior",            "ud"),
            "Columns":    ("03", "Estructura — Pilares",            "ud"),
            "Stairs":     ("06", "Escaleras",                       "ud"),
            "Ceilings":   ("11", "Falsos techos",                   "m²"),
            "Furniture":  ("13", "Mobiliario",                      "ud"),
            "Railings":   ("06", "Barandillas",                     "m"),
            "Generic Models":   ("01", "Trabajos previos",          "ud"),
            "Structural Framing": ("03", "Estructura metálica",     "m"),
            "Structural Foundations": ("02", "Cimentación",         "m³"),
            "Structural Columns": ("03", "Pilares",                 "ud"),
            "Curtain Walls": ("08", "Muro cortina",                 "m²"),
            "Curtain Panels": ("08", "Paneles muro cortina",        "m²"),
            "Curtain Wall Mullions": ("08", "Montantes muro cortina","m"),
            "Mass": ("01", "Volumetría general",                     "ud"),
            "Site": ("01", "Acondicionamiento del terreno",         "pa"),
            "Topography": ("01", "Replanteo y topografía",          "ud"),
            "IfcWall":            ("04", "Cerramientos exteriores",  "m²"),
            "IfcWallStandardCase": ("04", "Cerramientos exteriores", "m²"),
            "IfcSlab":            ("05", "Forjados",                 "m²"),
            "IfcRoof":            ("07", "Cubiertas",                "m²"),
            "IfcDoor":            ("09", "Carpintería interior",     "ud"),
            "IfcWindow":          ("08", "Carpintería exterior",     "ud"),
            "IfcColumn":          ("03", "Estructura — Pilares",     "ud"),
            "IfcBeam":            ("03", "Estructura — Vigas",       "m"),
            "IfcMember":          ("03", "Elementos estructurales",  "ud"),
            "IfcStair":           ("06", "Escaleras",                "ud"),
            "IfcSpace":           ("01", "Espacios (informativo)",   "m²"),
            "IfcOpeningElement":  ("09", "Huecos",                   "ud"),
            "IfcRailing":         ("06", "Barandillas",              "m"),
            "IfcVirtualElement":  ("01", "Geometría auxiliar",       "ud"),
        },
        "fallback_section": ("99", "Otras partidas", "ud"),
        "unit_rates": {
            "01": 8500.00,
            "02": 245.00,
            "03": 1250.00,
            "04": 78.00,
            "05": 92.00,
            "06": 3800.00,
            "07": 138.00,
            "08": 320.00,
            "09": 380.00,
            "11": 28.00,
            "13": 240.00,
            "99": 22.00,
        },
        "project": {
            "name": "Residencial Salamanca — Madrid",
            "description": (
                "Edificio residencial dúplex de obra nueva, 2 viviendas "
                "+ ampliación de planta baja existente. Superficie útil "
                "aprox. 320 m². Presupuesto base de licitación 1.450.000 "
                "EUR. Proyecto demostrativo a partir del modelo IFC "
                "Duplex (referencia buildingSMART)."
            ),
            "address": {
                "street": "Calle de Velázquez 86",
                "city": "Madrid",
                "state": "Comunidad de Madrid",
                "country": "España",
                "postal_code": "28006",
            },
            "project_code": "ES-2026-001",
            "project_type": "residential",
            "phase": "design",
            "budget_estimate": "1450000",
            "contingency_pct": "8",
            "contract_value": "1320000",
            "planned_start_date": "2026-09-01",
            "planned_end_date": "2027-12-15",
            "actual_start_date": None,
            "actual_end_date": None,
        },
        "contacts": [
            ("client",        "Inmobiliaria Salamanca SL",     None,        None,        "info@inmosalamanca.es",        "Promotor"),
            ("client",        "Inmobiliaria Salamanca SL",     "Carmen",    "Vázquez",   "c.vazquez@inmosalamanca.es",   "Directora de Obra Cliente"),
            ("consultant",    "García Arquitectos Asociados",   None,        None,        "estudio@garcia-arq.es",        "Estudio de Arquitectura"),
            ("consultant",    "García Arquitectos Asociados",   "Javier",    "García",    "j.garcia@garcia-arq.es",       "Arquitecto Director"),
            ("consultant",    "Estructuras Calatrava Consultores","Pilar",   "Ortiz",     "p.ortiz@calatrava-eng.es",     "Ingeniera de Estructuras"),
            ("subcontractor", "Construcciones Hispania SA",     None,        None,        "obras@hispania-cons.es",       "Constructora Principal"),
            ("subcontractor", "Aluminios Madrileños",           "Roberto",   "Fernández", "r.fernandez@alumadrid.es",     "Subcontrata Aluminio"),
            ("supplier",      "Cementos Portland Valderrivas",  "Lucía",     "Jiménez",   "l.jimenez@cporland.es",        "Proveedor de Hormigón"),
            ("supplier",      "Cerámicas Andaluzas",            "Manuel",    "Ruiz",      "m.ruiz@cer-and.es",            "Proveedor Revestimientos"),
        ],
        "tasks": [
            ("draft",       "task",        "Revisar cálculo estructural — sobrecarga forjado P1",
             "El proyectista incrementó la sobrecarga de uso. Recalcular armado del forjado entre P1 y P2."),
            ("open",        "decision",    "Decisión sobre sistema de climatización (aerotermia vs caldera gas)",
             "Comparativa económica entregada. El promotor debe decidir antes de presentar proyecto a visado."),
            ("open",        "task",        "Presentar solicitud de licencia ante Ayuntamiento de Madrid",
             "Proyecto básico completo; falta firma del visado y memoria de calidades."),
            ("in_progress","task",        "Coordinar instalaciones — choque entre clima y fontanería en falso techo",
             "El BIM coordinator detectó interferencia en planta baja. Revisión conjunta esta semana."),
            ("in_progress","topic",       "Comentarios revisión protección contra incendios",
             "Bombero municipal solicita extintor adicional en escalera oeste; pendiente confirmar coste."),
            ("completed",   "task",        "Visado del proyecto básico",
             "Visado conseguido en COAM con observaciones menores. Continuar con proyecto de ejecución."),
            ("completed",   "task",        "Estudio geotécnico — 4 sondeos",
             "Sondeos hasta 8 m. Recomendada zapata corrida en lugar de losa. Proyectista informado."),
            ("completed",   "personal",    "Visita al solar con topógrafo",
             "Replanteo de límites y cotas existentes confirmado para inicio de obra."),
        ],
        "field_reports": [
            (1, "daily", "clear",   16, "Excavación de zanjas para zapatas en eje A. Profundidad 1,20 m según proyecto. Encuentro con servicio existente — informado a dirección facultativa."),
            (3, "daily", "cloudy",  12, "Hormigonado de zapatas eje A. 22 m³ HA-25/B/20/IIa, vibrado correcto. Probetas tomadas para ensayos."),
            (5, "safety","clear",   18, "Charla semanal de seguridad: trabajo en zanjas y entibaciones. Asistencia 100%, sin incidentes."),
            (8, "inspection","clear",20, "Visita de OCT: revisión de armaduras de pilares planta baja. Acta firmada sin objeciones relevantes."),
        ],
        "finance": {
            "budget_categories": [
                ("labor",         "320000", "320000", "32000",  "32000",  "320000"),
                ("material",      "490000", "510000", "78000",  "78000",  "510000"),
                ("equipment",     "70000",  "70000",  "12000",  "12000",  "70000"),
                ("subcontractor", "420000", "420000", "32000",  "32000",  "420000"),
                ("overhead",      "85000",  "85000",  "8000",   "8000",   "85000"),
                ("contingency",   "100000", "75000",  "0",      "0",      "75000"),
            ],
            "invoices": [
                ("payable",    "CH-2026-0009", "22500.00",  -38, "Movimiento de tierras — certificación 1",     "approved"),
                ("payable",    "CH-2026-0014", "31200.00",  -10, "Cimentación — certificación 2",                "approved"),
                ("payable",    "CPV-2026-024", "8400.00",   -4,  "Hormigón HA-25 — albarán abril",               "pending"),
                ("receivable", "FAC-PROM-002", "62000.00",  -25, "Honorarios proyecto básico y ejecución",      "paid"),
                ("payable",    "GAR-2026-04",  "5800.00",   -2,  "Honorarios dirección de obra — abril",         "pending"),
            ],
        },
        "transmittals": [
            ("Proyecto de Ejecución — Cimentación PE-100",                "for_construction", -18),
            ("Planos de taller carpintería de aluminio — Revisión 2",     "for_review",       -7),
            ("Consulta del promotor — calidad acabados baños",             "for_information",  -3),
        ],
        "boq_markups": [
            ("Gastos generales de obra",  "percentage", "overhead",    13.0),
            ("Beneficio industrial",       "percentage", "profit",       6.0),
            ("Seguro todo riesgo",         "percentage", "insurance",    0.8),
            ("IVA repercutido",            "percentage", "tax",         21.0),
        ],
        "validation_rule_sets": ["boq_quality"],
    },

    # ── Brazil — Portuguese (BR) / BRL / Custom ──────────────────────
    "pt": {
        "country_label": "Brasil",
        "boq_name": "Planilha Orçamentária — Serviços Principais",
        "boq_description": (
            "Quantitativos extraídos do modelo BIM, organizados por "
            "macro-serviços segundo padrão SINAPI."
        ),
        "element_categories": {
            "Walls":      ("04", "Alvenaria e fechamentos",            "m²"),
            "Floors":     ("05", "Lajes e pavimentos",                  "m²"),
            "Roofs":      ("07", "Cobertura e impermeabilização",      "m²"),
            "Doors":      ("09", "Esquadrias internas",                 "un"),
            "Windows":    ("08", "Esquadrias externas",                 "un"),
            "Columns":    ("03", "Estrutura — Pilares",                 "un"),
            "Stairs":     ("06", "Escadas",                             "un"),
            "Ceilings":   ("11", "Forros",                              "m²"),
            "Furniture":  ("13", "Mobiliário",                          "un"),
            "Railings":   ("06", "Guarda-corpos",                       "m"),
            "Generic Models":   ("01", "Serviços preliminares",         "un"),
            "Structural Framing": ("03", "Estrutura metálica",          "m"),
            "Structural Foundations": ("02", "Fundações",               "m³"),
            "Structural Columns": ("03", "Pilares",                     "un"),
            "Curtain Walls": ("08", "Pele de vidro",                    "m²"),
            "Curtain Panels": ("08", "Painéis de fachada",              "m²"),
            "Curtain Wall Mullions": ("08", "Montantes de fachada",     "m"),
            "Mass": ("01", "Massa do edifício",                          "un"),
            "Site": ("01", "Serviços de canteiro",                      "vb"),
            "Topography": ("01", "Locação e topografia",                "un"),
            "IfcWall":            ("04", "Alvenaria e fechamentos",     "m²"),
            "IfcWallStandardCase": ("04", "Alvenaria e fechamentos",    "m²"),
            "IfcSlab":            ("05", "Lajes",                       "m²"),
            "IfcRoof":            ("07", "Cobertura",                   "m²"),
            "IfcDoor":            ("09", "Esquadrias internas",         "un"),
            "IfcWindow":          ("08", "Esquadrias externas",         "un"),
            "IfcColumn":          ("03", "Pilares",                     "un"),
            "IfcBeam":            ("03", "Vigas",                       "m"),
            "IfcMember":          ("03", "Elementos estruturais",       "un"),
            "IfcStair":           ("06", "Escadas",                     "un"),
            "IfcSpace":           ("01", "Ambientes (informativo)",     "m²"),
            "IfcOpeningElement":  ("09", "Vãos",                        "un"),
            "IfcRailing":         ("06", "Guarda-corpos",               "m"),
            "IfcVirtualElement":  ("01", "Geometria auxiliar",          "un"),
        },
        "fallback_section": ("99", "Outros serviços", "un"),
        "unit_rates": {
            "01": 22000.00,
            "02": 740.00,
            "03": 3200.00,
            "04": 165.00,
            "05": 220.00,
            "06": 9800.00,
            "07": 285.00,
            "08": 850.00,
            "09": 920.00,
            "11": 78.00,
            "13": 540.00,
            "99": 60.00,
        },
        "project": {
            "name": "Residencial Vila Madalena — São Paulo",
            "description": (
                "Edificação residencial unifamiliar com 2 pavimentos + "
                "subsolo, área construída ~210 m². Acabamento de alto "
                "padrão, automação residencial completa. Orçamento base "
                "R$ 1.850.000. Projeto demonstrativo baseado no modelo "
                "RAC Basic Sample (Autodesk)."
            ),
            "address": {
                "street": "Rua Harmonia 320",
                "city": "São Paulo",
                "state": "SP",
                "country": "Brasil",
                "postal_code": "05435-000",
            },
            "project_code": "BR-2026-001",
            "project_type": "residential",
            "phase": "design",
            "budget_estimate": "1850000",
            "contingency_pct": "10",
            "contract_value": "1680000",
            "planned_start_date": "2026-10-01",
            "planned_end_date": "2028-03-31",
            "actual_start_date": None,
            "actual_end_date": None,
        },
        "contacts": [
            ("client",        "Empreendimentos Vila SA",        None,        None,        "contato@empvila.com.br",       "Proprietário"),
            ("client",        "Empreendimentos Vila SA",        "Beatriz",   "Almeida",   "b.almeida@empvila.com.br",     "Gerente do Cliente"),
            ("consultant",    "Costa Arquitetura e Urbanismo",   None,        None,        "contato@costa-arq.com.br",     "Escritório de Arquitetura"),
            ("consultant",    "Costa Arquitetura e Urbanismo",   "Rafael",    "Costa",     "r.costa@costa-arq.com.br",     "Arquiteto Responsável"),
            ("consultant",    "Engenharia Pereira & Filhos",    "Marcos",    "Pereira",   "m.pereira@perengenharia.com.br","Engenheiro Estrutural"),
            ("subcontractor", "Construtora Bandeirantes Ltda",   None,        None,        "obras@bandeirantes-cons.com.br","Construtora Principal"),
            ("subcontractor", "Esquadrias Paulistas",            "Ana",       "Lima",      "a.lima@esqpaulistas.com.br",   "Subempreiteiro de Esquadrias"),
            ("supplier",      "Concreto Cimpor Brasil",          "João",      "Silva",     "j.silva@cimpor.com.br",        "Fornecedor de Concreto"),
            ("supplier",      "Cerâmica Portinari",              "Patricia",  "Santos",    "p.santos@portinari.com.br",    "Fornecedor de Revestimentos"),
        ],
        "tasks": [
            ("draft",       "task",        "Verificar projeto estrutural — sobrecarga laje L2",
             "Engenheiro estrutural revisou cargas e aumentou armadura. Confirmar com projetista de fôrmas."),
            ("open",        "decision",    "Decisão sistema de aquecimento de água (solar vs gás)",
             "Comparativo econômico entregue. Cliente deve decidir antes da execução das prumadas."),
            ("open",        "task",        "Protocolar projeto na Prefeitura de São Paulo",
             "Projeto arquitetônico completo, faltam ART do estrutural e do hidráulico."),
            ("in_progress","task",        "Compatibilização de instalações no forro do pavimento térreo",
             "Conflito entre eletrocalha e dutos de ar-condicionado. Reunião BIM marcada para sexta."),
            ("in_progress","topic",       "Comentários do Corpo de Bombeiros — saída de emergência",
             "Vistoria solicitou luminária autônoma adicional na escada. Aguardando custo do fornecedor."),
            ("completed",   "task",        "Aprovação do anteprojeto na PMSP",
             "Aprovação obtida com pequenas observações. Pode-se prosseguir com projeto executivo."),
            ("completed",   "task",        "Sondagem SPT — 6 furos",
             "Sondagens executadas até NA. Relatório indica solo coesivo, fundação direta viável."),
            ("completed",   "personal",    "Visita ao terreno com topógrafo",
             "Levantamento planialtimétrico finalizado. Cota do terreno conferida."),
        ],
        "field_reports": [
            (1, "daily", "clear",   24, "Escavação de baldrames eixo A concluída. Profundidade 1,5 m, conforme projeto. Solo coesivo confirmado."),
            (3, "daily", "rain",    19, "Chuva forte interrompeu concretagem. Equipe deslocada para serviços internos (alvenaria). Reagendar concreto p/ amanhã."),
            (5, "safety","clear",   26, "DDS semanal: uso correto de EPI em fôrmas e cimbramento. Todos os terceirizados presentes, lista anexa."),
            (8, "concrete_pour","clear", 28, "Concretagem de 18 m³ FCK 25 MPa para sapatas. Slump 8±2 cm, corpos de prova moldados (12 unidades)."),
        ],
        "finance": {
            "budget_categories": [
                ("labor",         "440000", "440000", "48000",  "48000",  "440000"),
                ("material",      "650000", "680000", "92000",  "92000",  "680000"),
                ("equipment",     "92000",  "92000",  "15000",  "15000",  "92000"),
                ("subcontractor", "510000", "510000", "42000",  "42000",  "510000"),
                ("overhead",      "108000", "108000", "9500",   "9500",   "108000"),
                ("contingency",   "150000", "120000", "0",      "0",      "120000"),
            ],
            "invoices": [
                ("payable",    "BAN-2026-0011","45200.00",  -36, "Construtora — medição de obra 1",             "approved"),
                ("payable",    "BAN-2026-0017","58400.00",  -11, "Construtora — medição de obra 2",             "approved"),
                ("payable",    "CIM-2026-029", "11800.00",  -6,  "Concreto FCK 25 — nota fiscal abril",          "pending"),
                ("receivable", "REC-PROP-005", "82000.00",  -22, "Honorários cliente — projeto e ART",          "paid"),
                ("payable",    "COS-2026-04",  "9400.00",   -2,  "Honorários arquitetura — abril",               "pending"),
            ],
        },
        "transmittals": [
            ("Projeto Executivo Estrutural — Liberação para Execução PE-100", "for_construction", -19),
            ("Projeto de fachada — Plotagem para análise",                    "for_review",       -8),
            ("Consulta do cliente — padrão de acabamento dos pisos",           "for_information",  -3),
        ],
        "boq_markups": [
            ("BDI — Despesas indiretas",   "percentage", "overhead",    14.0),
            ("Lucro construtor",            "percentage", "profit",      8.0),
            ("Seguro de obra",              "percentage", "insurance",    1.0),
            ("Tributos sobre faturamento",  "percentage", "tax",         11.0),
        ],
        "validation_rule_sets": ["boq_quality"],
    },

    # ── China — Simplified Chinese / CNY / Custom ─────────────────────
    "zh": {
        "country_label": "中国",
        "boq_name": "工程量清单 — 主要分部分项",
        "boq_description": (
            "BIM 模型自动提取工程量,按 GB 50500 清单计价规范分章节组织。"
        ),
        "element_categories": {
            "Walls":      ("04", "墙体工程",        "㎡"),
            "Floors":     ("05", "楼板工程",        "㎡"),
            "Roofs":      ("07", "屋面与防水工程",  "㎡"),
            "Doors":      ("09", "门窗 — 内门",     "樘"),
            "Windows":    ("08", "门窗 — 外窗",     "樘"),
            "Columns":    ("03", "结构 — 柱",        "根"),
            "Stairs":     ("06", "楼梯",            "组"),
            "Ceilings":   ("11", "吊顶",            "㎡"),
            "Furniture":  ("13", "家具",            "件"),
            "Railings":   ("06", "栏杆",            "m"),
            "Generic Models":   ("01", "总则与措施", "项"),
            "Structural Framing": ("03", "结构 — 钢结构", "m"),
            "Structural Foundations": ("02", "基础工程", "m³"),
            "Structural Columns": ("03", "结构 — 柱", "根"),
            "Curtain Walls": ("08", "幕墙工程",     "㎡"),
            "Curtain Panels": ("08", "幕墙板材",    "㎡"),
            "Curtain Wall Mullions": ("08", "幕墙立柱","m"),
            "Mass": ("01", "建筑体量",               "项"),
            "Site": ("01", "场地平整",              "项"),
            "Topography": ("01", "测量放线",        "项"),
            "IfcWall":            ("04", "墙体工程",  "㎡"),
            "IfcWallStandardCase": ("04", "墙体工程", "㎡"),
            "IfcSlab":            ("05", "楼板工程",  "㎡"),
            "IfcRoof":            ("07", "屋面工程",  "㎡"),
            "IfcDoor":            ("09", "内门",      "樘"),
            "IfcWindow":          ("08", "外窗",      "樘"),
            "IfcColumn":          ("03", "结构柱",    "根"),
            "IfcBeam":            ("03", "结构梁",    "m"),
            "IfcMember":          ("03", "结构构件",  "件"),
            "IfcStair":           ("06", "楼梯",      "组"),
            "IfcSpace":           ("01", "房间(信息项)","㎡"),
            "IfcOpeningElement":  ("09", "门窗洞口",  "个"),
            "IfcRailing":         ("06", "栏杆",      "m"),
            "IfcVirtualElement":  ("01", "辅助几何",  "项"),
        },
        "fallback_section": ("99", "其他分项工程", "项"),
        "unit_rates": {
            "01": 65000.00,
            "02": 1850.00,
            "03": 8400.00,
            "04": 420.00,
            "05": 580.00,
            "06": 24000.00,
            "07": 720.00,
            "08": 1850.00,
            "09": 2400.00,
            "11": 185.00,
            "13": 1500.00,
            "99": 150.00,
        },
        "project": {
            "name": "上海徐汇职业学校扩建工程",
            "description": (
                "现有职业学校的扩建项目,新增教学楼 4 层,总建筑面积约 "
                "5,800 ㎡。包含 24 个标准教室、6 个专业实训车间、行政办公区。"
                "符合 GB 50099 中小学校设计规范,绿色建筑二星标准。"
                "示范项目基于 Autodesk Technical School 样板模型。"
            ),
            "address": {
                "street": "宛平南路 1099 号",
                "city": "上海",
                "state": "上海市",
                "country": "中国",
                "postal_code": "200030",
            },
            "project_code": "CN-2026-001",
            "project_type": "institutional",
            "phase": "design",
            "budget_estimate": "42000000",
            "contingency_pct": "8",
            "contract_value": "38500000",
            "planned_start_date": "2026-11-01",
            "planned_end_date": "2028-08-31",
            "actual_start_date": None,
            "actual_end_date": None,
        },
        "contacts": [
            ("client",        "上海徐汇职业教育集团",         None,       None,      "info@xhvoc.edu.cn",          "建设单位"),
            ("client",        "上海徐汇职业教育集团",         "丽华",     "陈",       "chen.lihua@xhvoc.edu.cn",    "建设方项目经理"),
            ("consultant",    "华东建筑设计研究院",            None,       None,      "info@ecadi.com.cn",          "建筑设计院"),
            ("consultant",    "华东建筑设计研究院",            "建国",     "李",       "li.jianguo@ecadi.com.cn",    "项目总建筑师"),
            ("consultant",    "上海同济结构设计公司",           "晓明",     "王",       "wang.xiaoming@tj-struct.cn", "结构工程师"),
            ("subcontractor", "上海建工第七建筑公司",           None,       None,      "contact@scg7.com",           "总包施工单位"),
            ("subcontractor", "沪东钢结构有限公司",             "强",       "张",       "zhang.qiang@hudong-steel.cn","钢结构分包"),
            ("supplier",      "海螺水泥上海公司",               "梅",       "刘",       "liu.mei@conch-sh.cn",        "混凝土供应商"),
            ("supplier",      "中国南玻集团",                  "勇",       "赵",       "zhao.yong@csg.cn",           "玻璃幕墙供应商"),
        ],
        "tasks": [
            ("draft",       "task",        "复核教学楼荷载 — 二层活荷载调整",
             "结构师上调了二层活荷载至 3.5 kN/㎡。需重新核算配筋。"),
            ("open",        "decision",    "新风系统选型 (热回收 vs 普通) 决策",
             "经济性比较已出。建设方需在施工图阶段前确认选型。"),
            ("open",        "task",        "向徐汇规划局提交施工图审查",
             "结构和暖通施工图待最终签字。计划下周一提交。"),
            ("in_progress","task",        "机电管线综合 — 二层吊顶碰撞",
             "BIM 协调发现送风管与给排水管碰撞。本周内闭合。"),
            ("in_progress","topic",       "消防部门评审意见 — 疏散宽度",
             "需要在西侧楼梯增加一个排烟窗。等待造价反馈。"),
            ("completed",   "task",        "方案设计通过专家评审",
             "评审通过,有 3 项小修改意见,已纳入施工图。"),
            ("completed",   "task",        "岩土工程勘察 — 8 个钻孔",
             "勘察深度 18 m,持力层位于 -8.5 m。建议采用钻孔灌注桩基础。"),
            ("completed",   "personal",    "现场踏勘 — 与测绘院",
             "完成红线复核及周边管线现状摸排。"),
        ],
        "field_reports": [
            (1, "daily", "clear",  18, "A 轴线土方开挖至设计标高。运土车 12 车次,无异常。"),
            (3, "daily", "rain",   14, "雨天暂停室外作业,转入钢筋加工棚下料工作。8 t 钢筋已加工完毕。"),
            (5, "safety","clear",  20, "周安全例会:高处作业及临边防护。各班组负责人到齐,签到表附后。"),
            (8, "concrete_pour","clear", 22, "C30 商品混凝土浇筑 95 m³ — 桩承台 P-1 至 P-9。坍落度 180±20 mm,留置标养试块 6 组。"),
        ],
        "finance": {
            "budget_categories": [
                ("labor",         "10500000","10500000","1450000","1450000","10500000"),
                ("material",      "15800000","16200000","2400000","2400000","16200000"),
                ("equipment",     "2100000", "2100000", "320000", "320000", "2100000"),
                ("subcontractor", "9200000", "9200000", "950000", "950000", "9200000"),
                ("overhead",      "2200000", "2200000", "240000", "240000", "2200000"),
                ("contingency",   "2200000", "1800000", "0",      "0",      "1800000"),
            ],
            "invoices": [
                ("payable",    "SCG-2026-008", "1250000.00",-40, "总包工程款 — 进度第 1 期",                     "approved"),
                ("payable",    "SCG-2026-014", "1480000.00",-12, "总包工程款 — 进度第 2 期",                     "approved"),
                ("payable",    "CONCH-2026-22","185000.00", -5,  "商品混凝土 C30 — 4 月供货",                    "pending"),
                ("receivable", "REV-OWN-0006", "3800000.00",-26, "建设方付款 — 设计阶段服务费",                 "paid"),
                ("payable",    "ECADI-2026-04","265000.00", -2,  "设计费 — 4 月",                                "pending"),
            ],
        },
        "transmittals": [
            ("施工图 — 基础工程发布版 SG-100",                  "for_construction", -21),
            ("幕墙深化图 — 提交业主审核 第二版",                 "for_review",        -9),
            ("业主咨询 — 教室隔声等级标准",                       "for_information",   -4),
        ],
        "boq_markups": [
            ("企业管理费",   "percentage", "overhead",    7.5),
            ("利润",        "percentage", "profit",      5.0),
            ("规费",        "percentage", "tax",         3.5),
            ("增值税",      "percentage", "tax",         9.0),
        ],
        "validation_rule_sets": ["boq_quality"],
    },
}


# ── Project specs (locale + currency + CAD file mapping) ──────────────────

PROJECT_SPECS: list[dict[str, Any]] = [
    {
        "key": "us",
        "locale": "en",
        "currency": "USD",
        "region": "US",
        "classification_standard": "masterformat",
        "cad_file": "2022 rstadvancedsampleproject.rvt",
    },
    {
        "key": "de",
        "locale": "de",
        "currency": "EUR",
        "region": "DACH",
        "classification_standard": "din276",
        "cad_file": "AC20-FZK-Haus.ifc",
    },
    {
        "key": "es",
        "locale": "es",
        "currency": "EUR",
        "region": "EU",
        "classification_standard": "custom",
        "cad_file": "Ifc2x3_Duplex_Architecture.ifc",
    },
    {
        "key": "br",
        "locale": "pt",
        "currency": "BRL",
        "region": "LATAM",
        "classification_standard": "custom",
        "cad_file": "2023 racbasicsampleproject.rvt",
    },
    {
        "key": "cn",
        "locale": "zh",
        "currency": "CNY",
        "region": "ASIA_PAC",
        "classification_standard": "custom",
        "cad_file": "Technicalschoolcurrentm_sample.rvt",
    },
]


# ── Date helpers ──────────────────────────────────────────────────────────

def date_offset(days: int) -> str:
    """Return YYYY-MM-DD for TODAY + ``days`` (negative = past)."""
    return (TODAY + dt.timedelta(days=days)).isoformat()


# ── HTTP helpers ──────────────────────────────────────────────────────────

async def login_or_register(client: httpx.AsyncClient) -> dict[str, str]:
    """Return auth headers; register the admin if login fails."""
    r = await client.post(
        "/api/v1/users/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    if r.status_code != 200:
        await client.post(
            "/api/v1/users/auth/register",
            json={
                "email": ADMIN_EMAIL,
                "password": ADMIN_PASSWORD,
                "full_name": "Demo Admin",
            },
        )
        r = await client.post(
            "/api/v1/users/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        )
        r.raise_for_status()
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _bulk_insert_links(position_id: str, element_ids: list[str]) -> int:
    """INSERT OR IGNORE many (position, element) rows in one transaction.

    Used by the CAD-driven BOQ builder — HTTP POST per link is too slow
    against single-writer SQLite (~3/s).
    """
    if not element_ids:
        return 0
    db_path = REPO_ROOT / "backend" / "openestimate.db"
    if not db_path.exists():
        return 0
    conn = sqlite3.connect(str(db_path))
    try:
        rows = [
            (
                str(uuid.uuid4()),       # id
                position_id,             # boq_position_id
                eid,                     # bim_element_id
                "auto_grouped",          # link_type
                "high",                  # confidence
                "{}",                    # metadata (JSON text)
            )
            for eid in element_ids
        ]
        cur = conn.executemany(
            "INSERT OR IGNORE INTO oe_bim_boq_link "
            "(id, boq_position_id, bim_element_id, link_type, confidence, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
        return cur.rowcount or 0
    finally:
        conn.close()


def promote_admin_direct() -> None:
    """Bump the seed user to role=admin so per-user filters don't hide rows."""
    db_path = REPO_ROOT / "backend" / "openestimate.db"
    if not db_path.exists():
        return
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "UPDATE oe_users_user SET role = 'admin' WHERE email = ?",
            (ADMIN_EMAIL,),
        )
        conn.commit()
    finally:
        conn.close()


def wipe_all_projects_direct() -> int:
    """Delete every project + cascade dependent rows.

    Direct SQLite because the HTTP list endpoint applies per-user
    visibility filters and would miss orphan rows from prior runs.
    """
    db_path = REPO_ROOT / "backend" / "openestimate.db"
    if not db_path.exists():
        return 0
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM oe_projects_project"
        ).fetchone()[0]
        conn.execute("DELETE FROM oe_projects_project")
        # Soft references that aren't FK-cascaded
        for soft_table in (
            "oe_bim_model",
            "oe_bim_element",
            "oe_bim_link",
            "oe_boq_boq",
            "oe_boq_position",
            "oe_documents_document",
            "oe_tasks_task",
            "oe_rfi_rfi",
            "oe_contacts_contact",
            "oe_transmittals_transmittal",
            "oe_fieldreports_field_report",
            "oe_finance_invoice",
            "oe_finance_payment",
            "oe_finance_budget",
            "oe_validation_report",
            "oe_validation_result",
            "oe_markups_markup",
            "oe_reporting_generated_report",
        ):
            try:
                conn.execute(f"DELETE FROM {soft_table}")
            except sqlite3.OperationalError:
                pass
        conn.commit()
        return n
    finally:
        conn.close()


def wipe_orphan_bim_files() -> int:
    if not BIM_DATA_DIR.exists():
        return 0
    removed = 0
    for child in BIM_DATA_DIR.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
    return removed


# ── Per-module seeders ───────────────────────────────────────────────────

async def create_project(
    client: httpx.AsyncClient, headers: dict, spec: dict, l10n: dict,
) -> dict:
    body = {
        "name": l10n["project"]["name"],
        "description": l10n["project"]["description"],
        "region": spec["region"],
        "classification_standard": spec["classification_standard"],
        "currency": spec["currency"],
        "locale": spec["locale"],
        "validation_rule_sets": l10n["validation_rule_sets"],
        "project_code": l10n["project"]["project_code"],
        "project_type": l10n["project"]["project_type"],
        "phase": l10n["project"]["phase"],
        "budget_estimate": l10n["project"]["budget_estimate"],
        "contingency_pct": l10n["project"]["contingency_pct"],
        "contract_value": l10n["project"]["contract_value"],
        "planned_start_date": l10n["project"]["planned_start_date"],
        "planned_end_date": l10n["project"]["planned_end_date"],
        "address": l10n["project"]["address"],
    }
    r = await client.post("/api/v1/projects/", json=body, headers=headers)
    if r.status_code >= 400:
        log_issue(
            "BLOCKER", f"Project create failed for {spec['key']}",
            "Phase 2", f"HTTP {r.status_code}: {r.text[:200]}",
            "Seeder aborts", "Check ProjectCreate schema",
        )
        r.raise_for_status()
    return r.json()


async def seed_contacts(
    client: httpx.AsyncClient, headers: dict, project_id: str, l10n: dict,
) -> list[dict]:
    """Create the contact roster.  Returns the list of created records."""
    created: list[dict] = []
    for typ, company, first, last, email, role in l10n["contacts"]:
        body: dict[str, Any] = {
            "contact_type": typ,
            "company_name": company,
            "email": email,
            "notes": role,
        }
        if first:
            body["first_name"] = first
        if last:
            body["last_name"] = last
        r = await client.post("/api/v1/contacts/", json=body, headers=headers)
        if r.status_code >= 400:
            log_issue(
                "BUG", f"Contact create failed: {company}",
                "Phase 2 — contacts",
                f"HTTP {r.status_code}: {r.text[:200]}",
                "Seeder skips this contact", "Inspect ContactCreate schema vs payload",
            )
            continue
        created.append(r.json())
    return created


async def seed_tasks(
    client: httpx.AsyncClient, headers: dict, project_id: str, l10n: dict,
) -> int:
    created = 0
    for status, task_type, title, description in l10n["tasks"]:
        body = {
            "project_id": project_id,
            "task_type": task_type,
            "title": title,
            "description": description,
            "status": status,
            # priority defaults to "normal" — must match
            # ^(low|normal|high|urgent)$ regex; we leave it default.
        }
        r = await client.post("/api/v1/tasks/", json=body, headers=headers)
        if r.status_code >= 400:
            log_issue(
                "BUG", f"Task create failed: {title[:40]}",
                "Phase 2 — tasks",
                f"HTTP {r.status_code}: {r.text[:200]}",
                "Skip this task", "Verify TaskCreate schema",
            )
            continue
        created += 1
    return created


async def seed_field_reports(
    client: httpx.AsyncClient, headers: dict, project_id: str, l10n: dict,
) -> int:
    """Create a few field reports back-dated relative to today."""
    created = 0
    for days_ago, report_type, weather, temp, work in l10n["field_reports"]:
        body = {
            "project_id": project_id,
            "report_date": date_offset(-days_ago),
            "report_type": report_type,
            "weather_condition": weather,
            "temperature_c": float(temp),
            "work_performed": work,
        }
        r = await client.post(
            "/api/v1/fieldreports/reports/", json=body, headers=headers,
        )
        if r.status_code >= 400:
            log_issue(
                "BUG", f"Field report create failed ({days_ago}d ago)",
                "Phase 2 — fieldreports",
                f"HTTP {r.status_code}: {r.text[:200]}",
                "Skip this report", "Verify FieldReportCreate schema",
            )
            continue
        created += 1
    return created


async def seed_finance(
    client: httpx.AsyncClient, headers: dict, project_id: str, currency: str,
    l10n: dict,
) -> dict:
    """Create budget categories + invoices.  Returns counts."""
    out = {"budgets": 0, "invoices": 0}
    for cat, original, revised, committed, actual, forecast in l10n["finance"]["budget_categories"]:
        body = {
            "project_id": project_id,
            "category": cat,
            "original_budget": original,
            "revised_budget": revised,
            "committed": committed,
            "actual": actual,
            "forecast_final": forecast,
        }
        r = await client.post("/api/v1/finance/budgets/", json=body, headers=headers)
        if r.status_code >= 400:
            log_issue(
                "BUG", f"Budget create failed: {cat}",
                "Phase 2 — finance/budgets",
                f"HTTP {r.status_code}: {r.text[:200]}",
                "Skip this budget line", "Verify BudgetCreate schema",
            )
            continue
        out["budgets"] += 1

    for direction, num, subtotal, days_ago, desc, status in l10n["finance"]["invoices"]:
        # Note: InvoiceCreate has `notes` not `description` — readable
        # text goes there.  `amount_total` defaults to 0; we set it
        # equal to subtotal because the seed doesn't model tax/retention.
        body = {
            "project_id": project_id,
            "invoice_direction": direction,
            "invoice_number": num,
            "invoice_date": date_offset(days_ago),
            "due_date": date_offset(days_ago + 30),
            "currency_code": currency,
            "amount_subtotal": subtotal,
            "amount_total": subtotal,
            "notes": desc,
            "status": status,
        }
        r = await client.post("/api/v1/finance/", json=body, headers=headers)
        if r.status_code >= 400:
            log_issue(
                "BUG", f"Invoice create failed: {num}",
                "Phase 2 — finance/invoices",
                f"HTTP {r.status_code}: {r.text[:200]}",
                "Skip this invoice", "Verify InvoiceCreate schema",
            )
            continue
        out["invoices"] += 1
    return out


async def seed_transmittals(
    client: httpx.AsyncClient, headers: dict, project_id: str, l10n: dict,
) -> int:
    created = 0
    for subject, purpose, days_ago in l10n["transmittals"]:
        body = {
            "project_id": project_id,
            "subject": subject,
            "purpose_code": purpose,
            "issued_date": date_offset(days_ago),
            "response_due_date": date_offset(days_ago + 14),
            "cover_note": subject,
        }
        r = await client.post("/api/v1/transmittals/", json=body, headers=headers)
        if r.status_code >= 400:
            log_issue(
                "BUG", f"Transmittal create failed: {subject[:40]}",
                "Phase 2 — transmittals",
                f"HTTP {r.status_code}: {r.text[:200]}",
                "Skip this transmittal",
                "Verify TransmittalCreate schema",
            )
            continue
        created += 1
    return created


# ── CAD upload + wait ─────────────────────────────────────────────────────

async def upload_cad(
    client: httpx.AsyncClient, headers: dict, project_id: str,
    file_path: pathlib.Path,
) -> dict:
    with file_path.open("rb") as f:
        files = {"file": (file_path.name, f, "application/octet-stream")}
        params = {
            "project_id": project_id,
            "name": file_path.stem,
            "discipline": "architecture",
            "conversion_depth": "standard",
        }
        r = await client.post(
            "/api/v1/bim_hub/upload-cad/",
            headers=headers,
            params=params,
            files=files,
            timeout=180,
        )
    r.raise_for_status()
    return r.json()


async def wait_for_model_ready(
    client: httpx.AsyncClient, headers: dict, model_id: str, label: str,
) -> str:
    deadline = time.monotonic() + MODEL_READY_TIMEOUT_S
    last_status = ""
    while time.monotonic() < deadline:
        # NOTE: bim_hub GET single model is at `/{model_id}`, not
        # `/models/{model_id}` — `/models/...` is the elements/geometry sub-tree.
        r = await client.get(
            f"/api/v1/bim_hub/{model_id}", headers=headers,
        )
        if r.status_code == 404:
            await asyncio.sleep(MODEL_POLL_INTERVAL_S)
            continue
        r.raise_for_status()
        st = r.json().get("status", "")
        if st != last_status:
            print(f"      {label:50} → {st}", flush=True)
            last_status = st
        if st in (
            "ready", "error", "converter_required",
            "needs_converter", "failed", "conversion_failed",
        ):
            return st
        await asyncio.sleep(MODEL_POLL_INTERVAL_S)
    return "timeout"


# ── CAD-driven BOQ builder + group linker ─────────────────────────────────

async def _fetch_elements_tolerant(
    client: httpx.AsyncClient, headers: dict, model_id: str,
) -> list[dict]:
    """Fetch all elements for a model, skipping rows that 500 at the API.

    Strategy: try page=500 first.  On 500, halve the window until we're
    fetching single rows.  Rows that still 500 at limit=1 are logged
    and skipped; all other rows in the model still come through.
    """
    url = f"/api/v1/bim_hub/models/{model_id}/elements/"
    elements: list[dict] = []

    async def fetch(off: int, lim: int) -> list[dict] | None:
        r = await client.get(url, headers=headers,
                             params={"limit": lim, "offset": off})
        if r.status_code == 500:
            return None
        r.raise_for_status()
        body = r.json()
        items = body.get("items") if isinstance(body, dict) else body
        return items or []

    async def recurse(off: int, lim: int) -> None:
        items = await fetch(off, lim)
        if items is None:
            # 500 on this window: subdivide or skip single row
            if lim <= 1:
                log_issue(
                    "BUG", f"Element serialization 500 (model {model_id[:8]} off={off})",
                    "Phase 3 — fetch elements",
                    f"GET {url}?limit=1&offset={off} → 500",
                    "Skip this single element; rest of the model still ingests",
                    "Backend /elements/ endpoint fails to serialize this row — "
                    "likely a property with unexpected type (check Pydantic model)",
                )
                return
            half = max(1, lim // 2)
            await recurse(off, half)
            await recurse(off + half, lim - half)
            return
        if not items:
            return
        elements.extend(items)

    # First, coarse pagination
    off = 0
    page = 500
    while True:
        probe = await fetch(off, page)
        if probe is None:
            # Bad window — fall into recursive subdivision for this block
            await recurse(off, page)
            off += page
            continue
        if not probe:
            break
        elements.extend(probe)
        if len(probe) < page:
            break
        off += page

    return elements


async def build_cad_driven_boq(
    client: httpx.AsyncClient, headers: dict, project_id: str, currency: str,
    model_id: str, l10n: dict,
) -> dict:
    """Read every BIM element, group by element_type, produce a BOQ
    section + position per group, link the entire group to the position.

    Returns ``{"boq_id": str, "sections": int, "positions": int, "links": int}``.
    """
    # 1. Fetch ALL elements (paginated).  Some individual elements
    # trigger a 500 at the /elements/ endpoint (see issue "element
    # serialization fails for specific rows").  Be tolerant: on 500
    # at a page, retry with smaller pages and skip the offending
    # row so the rest of the model still gets through.
    elements = await _fetch_elements_tolerant(client, headers, model_id)

    if not elements:
        log_issue(
            "BUG", "BIM model has zero elements after conversion",
            "Phase 3 — CAD-driven BOQ",
            f"model_id={model_id}",
            "Project ends up with empty BOQ",
            "Check converter pipeline output for this CAD file",
        )
        return {"boq_id": "", "sections": 0, "positions": 0, "links": 0}

    # 2. Group by element_type — BOQ section per group
    groups: dict[str, list[dict]] = {}
    for el in elements:
        et = (el.get("element_type") or "").strip() or "Generic Models"
        groups.setdefault(et, []).append(el)

    # 3. Create BOQ shell
    boq_r = await client.post(
        "/api/v1/boq/boqs/",
        json={
            "project_id": project_id,
            "name": l10n["boq_name"],
            "description": l10n["boq_description"],
            "estimate_type": "detailed",
        },
        headers=headers,
    )
    if boq_r.status_code >= 400:
        log_issue(
            "BLOCKER", "BOQ shell create failed",
            "Phase 3 — BOQ",
            f"HTTP {boq_r.status_code}: {boq_r.text[:200]}",
            "Cannot proceed", "Verify BOQCreate schema",
        )
        boq_r.raise_for_status()
    boq = boq_r.json()
    boq_id = boq["id"]

    # 4. Build sections.  Dedupe by section_code (ordinal) only — that's
    # the server's uniqueness constraint.  Element types that share an
    # ordinal but had different labels in the l10n map (e.g. "Walls" vs
    # "Walls — generic") would otherwise collide with HTTP 409.  On 409
    # we also fall through to looking up the already-created section.
    section_cache: dict[str, str] = {}
    sections_created = 0
    positions_created = 0
    links_created = 0
    cats = l10n["element_categories"]
    fallback = l10n["fallback_section"]

    # Stable iteration order — biggest groups first so the BOQ reads
    # top-down from the most-impactful trades.
    sorted_types = sorted(groups.items(), key=lambda kv: -len(kv[1]))
    for et, els in sorted_types:
        section_code, section_label, _section_unit = cats.get(et, fallback)

        if section_code not in section_cache:
            sec_r = await client.post(
                f"/api/v1/boq/boqs/{boq_id}/sections/",
                json={
                    "ordinal": section_code,
                    "description": section_label,
                },
                headers=headers,
            )
            if sec_r.status_code == 409:
                # Section with this ordinal already exists (two element
                # types mapped to the same code).  Look it up.
                list_r = await client.get(
                    f"/api/v1/boq/boqs/{boq_id}/sections/",
                    headers=headers,
                )
                existing_id = ""
                if list_r.status_code == 200:
                    body = list_r.json()
                    items = body.get("items") if isinstance(body, dict) else body
                    for s in items or []:
                        if str(s.get("ordinal")) == section_code:
                            existing_id = s.get("id", "")
                            break
                section_cache[section_code] = existing_id
            elif sec_r.status_code >= 400:
                log_issue(
                    "BUG", f"Section create failed: {section_code} {section_label}",
                    "Phase 3 — sections",
                    f"HTTP {sec_r.status_code}: {sec_r.text[:200]}",
                    "Skip section, positions will fall under root",
                    "Verify section endpoint and ordinal collision rules",
                )
                section_cache[section_code] = ""
            else:
                section_cache[section_code] = sec_r.json()["id"]
                sections_created += 1
        section_id = section_cache[section_code]

        # Compute aggregated quantity + best unit for this group.
        qty, unit = _aggregate_group_quantity(els, cats.get(et, fallback)[2])
        rate = float(l10n["unit_rates"].get(section_code, 25.0))
        # For per-piece sections (ea/Stk/un/樘/件/根) the rate is per
        # item; otherwise the rate is per m²/m³/m and quantity is the
        # summed dimension.
        ordinal = f"{section_code}.{(positions_created % 999) + 1:03d}"

        position_desc = _make_position_description(et, len(els), l10n)
        pr = await client.post(
            f"/api/v1/boq/boqs/{boq_id}/positions/",
            json={
                "boq_id": boq_id,
                "parent_id": section_id or None,
                "ordinal": ordinal,
                "description": position_desc,
                "unit": unit,
                "quantity": qty,
                "unit_rate": rate,
                "source": "cad_import",
                "metadata": {
                    "bim_element_count": len(els),
                    "bim_element_type": et,
                    "bim_model_id": model_id,
                },
            },
            headers=headers,
        )
        if pr.status_code >= 400:
            log_issue(
                "BUG", f"Position create failed: {ordinal} {position_desc[:40]}",
                "Phase 3 — positions",
                f"HTTP {pr.status_code}: {pr.text[:200]}",
                "Skip position, group goes unlinked",
                "Verify PositionCreate schema",
            )
            continue
        position_id = pr.json()["id"]
        positions_created += 1

        # GROUP LINK: every element in the bucket → this single position.
        # Single POST per element hits SQLite's single-writer wall
        # (~3 links/s).  For 11k elements across 5 projects that takes
        # an hour.  Bulk-insert directly via the sqlite3 driver in one
        # transaction instead — ~100× faster, and `oe_bim_boq_link` has
        # no triggers / service-side side effects we'd miss.
        links_created += _bulk_insert_links(position_id, [el["id"] for el in els])

    return {
        "boq_id": boq_id,
        "sections": sections_created,
        "positions": positions_created,
        "links": links_created,
    }


def _aggregate_group_quantity(
    elements: list[dict], default_unit: str,
) -> tuple[float, str]:
    """Pick the most informative aggregate quantity for a group.

    Preference: volume → area → length → element count.  Units returned
    as the same string the section header used (defaults to default_unit
    when count is the chosen dimension).
    """
    sum_volume = 0.0
    sum_area = 0.0
    sum_length = 0.0
    count = 0
    for el in elements:
        count += 1
        q = el.get("quantities") or {}
        v = q.get("volume_m3") or q.get("volume") or 0
        a = q.get("area_m2") or q.get("area") or 0
        ln = q.get("length_m") or q.get("length") or 0
        try:
            sum_volume += float(v) if v else 0.0
            sum_area += float(a) if a else 0.0
            sum_length += float(ln) if ln else 0.0
        except (TypeError, ValueError):
            pass
    if sum_volume > 0:
        return round(sum_volume, 3), "m³"
    if sum_area > 0:
        return round(sum_area, 3), "m²"
    if sum_length > 0:
        return round(sum_length, 3), "m"
    return float(count), default_unit


def _make_position_description(element_type: str, count: int, l10n: dict) -> str:
    """Build a localized position description from element_type + count."""
    cats = l10n["element_categories"]
    label = cats.get(element_type, l10n["fallback_section"])[1]
    # "{label} — {count} elements from BIM model"
    if l10n is LOCALES["de"]:
        return f"{label} — {count} Elemente aus BIM-Modell"
    if l10n is LOCALES["es"]:
        return f"{label} — {count} elementos del modelo BIM"
    if l10n is LOCALES["pt"]:
        return f"{label} — {count} elementos do modelo BIM"
    if l10n is LOCALES["zh"]:
        return f"{label} — BIM 模型 {count} 个构件"
    return f"{label} — {count} elements from BIM model"


# ── BOQ markups + validation runner ───────────────────────────────────────

async def seed_boq_markups(
    client: httpx.AsyncClient, headers: dict, boq_id: str, l10n: dict,
) -> int:
    created = 0
    for name, markup_type, category, percentage in l10n["boq_markups"]:
        body = {
            "name": name,
            "markup_type": markup_type,
            "category": category,
            "percentage": float(percentage),
            "apply_to": "direct_cost",
        }
        r = await client.post(
            f"/api/v1/boq/boqs/{boq_id}/markups/", json=body, headers=headers,
        )
        if r.status_code >= 400:
            log_issue(
                "BUG", f"BOQ markup create failed: {name}",
                "Phase 3 — markups",
                f"HTTP {r.status_code}: {r.text[:200]}",
                "Skip markup", "Verify BOQ MarkupCreate schema",
            )
            continue
        created += 1
    return created


async def run_validation(
    client: httpx.AsyncClient, headers: dict, project_id: str, boq_id: str,
    rule_sets: list[str],
) -> dict:
    body = {
        "project_id": project_id,
        "boq_id": boq_id,
        "rule_sets": rule_sets,
    }
    r = await client.post(
        "/api/v1/validation/run/", json=body, headers=headers,
    )
    if r.status_code >= 400:
        log_issue(
            "BUG", "Validation run failed",
            "Phase 4 — validation",
            f"HTTP {r.status_code}: {r.text[:200]}",
            "Project shows no validation report",
            "Verify validation/run schema and that BOQ has positions",
        )
        return {"status": "error"}
    return r.json()


# ── Main orchestrator ────────────────────────────────────────────────────

async def main() -> None:
    if not CAD_SOURCE_DIR.exists():
        sys.exit(f"CAD source directory not found: {CAD_SOURCE_DIR}")

    async with httpx.AsyncClient(base_url=BASE, timeout=180.0) as client:
        print("=" * 70)
        print("  OpenEstimate — Demo Showcase Seeder v2 (5 projects, 5 CAD)")
        print("=" * 70)

        # ── Phase 0 — Auth ──
        print("\n[1/8] Authenticate + promote admin...")
        headers = await login_or_register(client)
        promote_admin_direct()
        headers = await login_or_register(client)
        print(f"      Authenticated as {ADMIN_EMAIL} (admin).")

        # ── Phase 1 — Wipe ──
        print("\n[2/8] Wiping existing demo data...")
        deleted = wipe_all_projects_direct()
        orphans = wipe_orphan_bim_files()
        print(f"      Deleted {deleted} project(s); removed {orphans} orphan BIM dir(s).")

        # ── Phase 2 — Per-project setup (project + module data) ──
        print("\n[3/8] Creating 5 projects + non-CAD module data...")
        created: list[dict] = []
        for spec in PROJECT_SPECS:
            l10n = LOCALES[spec["locale"]]
            print(f"\n  -- [{spec['key'].upper()}] {l10n['project']['name']}")
            try:
                project = await create_project(client, headers, spec, l10n)
            except Exception as exc:
                print(f"     !! Project create failed — skipping: {exc}")
                continue
            project_id = project["id"]
            print(f"     project_id={project_id[:8]}")

            contacts = await seed_contacts(client, headers, project_id, l10n)
            print(f"     contacts:   {len(contacts):>2}")

            n_tasks = await seed_tasks(client, headers, project_id, l10n)
            print(f"     tasks:      {n_tasks:>2}")

            n_fr = await seed_field_reports(client, headers, project_id, l10n)
            print(f"     field reports: {n_fr:>2}")

            n_fin = await seed_finance(client, headers, project_id, spec["currency"], l10n)
            print(f"     finance:    {n_fin['budgets']} budgets, {n_fin['invoices']} invoices")

            n_tx = await seed_transmittals(client, headers, project_id, l10n)
            print(f"     transmittals: {n_tx:>2}")

            created.append({
                "spec": spec, "l10n": l10n, "project": project,
                "contacts": contacts,
            })

        # ── Phase 2b — CAD upload (parallel kick-off, then wait sequentially)
        print("\n[4/8] Uploading CAD models (kicks off conversion)...")
        upload_handles: list[tuple[dict, str, str]] = []
        for entry in created:
            spec = entry["spec"]
            project = entry["project"]
            cad_path = CAD_SOURCE_DIR / spec["cad_file"]
            if not cad_path.exists():
                log_issue(
                    "BLOCKER", f"CAD file missing: {spec['cad_file']}",
                    "Phase 2b — upload",
                    f"Path not found: {cad_path}",
                    "Project ends up without BIM model",
                    "Restore the file or update CAD_SOURCE_DIR",
                )
                continue
            print(f"      [{spec['key']}] uploading {spec['cad_file']}"
                  f" ({cad_path.stat().st_size / 1_048_576:.1f} MB)")
            try:
                resp = await upload_cad(client, headers, project["id"], cad_path)
            except Exception as exc:
                log_issue(
                    "BLOCKER", f"CAD upload failed: {spec['cad_file']}",
                    "Phase 2b — upload",
                    f"Exception: {exc}",
                    "Project ends up without BIM model",
                    "Inspect bim_hub/upload-cad endpoint",
                )
                continue
            model_id = resp.get("model_id") or resp.get("id")
            if not model_id:
                log_issue(
                    "BLOCKER", f"CAD upload returned no model_id: {spec['cad_file']}",
                    "Phase 2b — upload",
                    f"Response: {resp}",
                    "Project ends up without BIM model",
                    "Check upload response shape",
                )
                continue
            upload_handles.append((entry, model_id, spec["cad_file"]))

        # ── Phase 2c — wait for conversion ──
        print(f"\n[5/8] Waiting for {len(upload_handles)} model(s) to finish converting...")
        ready: list[tuple[dict, str]] = []
        for entry, model_id, fname in upload_handles:
            st = await wait_for_model_ready(client, headers, model_id, fname)
            if st == "ready":
                ready.append((entry, model_id))
            else:
                log_issue(
                    "BLOCKER", f"CAD conversion did not reach ready: {fname}",
                    "Phase 2c — conversion",
                    f"Final status: {st}",
                    "Project's BOQ won't include CAD-driven sections",
                    "Inspect cad_converter / rvt_parser logs for this file",
                )

        # ── Phase 3 — CAD-driven BOQ + group links + markups ──
        print(f"\n[6/8] Building CAD-driven BOQ for {len(ready)} project(s)...")
        boq_handles: list[tuple[dict, str]] = []
        for entry, model_id in ready:
            spec = entry["spec"]
            l10n = entry["l10n"]
            project = entry["project"]
            print(f"\n  -- [{spec['key'].upper()}] BOQ from {spec['cad_file']}")
            try:
                result = await build_cad_driven_boq(
                    client, headers, project["id"], spec["currency"],
                    model_id, l10n,
                )
            except Exception as exc:
                log_issue(
                    "BLOCKER", f"BOQ build crashed for {spec['key']}",
                    "Phase 3", f"Exception: {exc}\n{traceback.format_exc()[:500]}",
                    "Project ends up without BOQ",
                    "Inspect build_cad_driven_boq logic",
                )
                continue
            print(f"     sections: {result['sections']:>2}, "
                  f"positions: {result['positions']:>2}, "
                  f"BIM links: {result['links']:>3}")
            if result["boq_id"]:
                boq_handles.append((entry, result["boq_id"]))
                n_markup = await seed_boq_markups(
                    client, headers, result["boq_id"], l10n,
                )
                print(f"     markups:  {n_markup}")

        # ── Phase 4 — Validations ──
        print(f"\n[7/8] Running validations for {len(boq_handles)} BOQ(s)...")
        for entry, boq_id in boq_handles:
            spec = entry["spec"]
            l10n = entry["l10n"]
            res = await run_validation(
                client, headers, entry["project"]["id"], boq_id,
                l10n["validation_rule_sets"],
            )
            print(f"     [{spec['key']}] validation status: {res.get('status', 'n/a')}")

        # ── Phase 5 — Summary ──
        print("\n" + "=" * 70)
        print("  Seed complete. Summary:")
        print("=" * 70)
        for entry in created:
            spec = entry["spec"]
            project = entry["project"]
            print(
                f"  [{spec['key']}] {LOCALES[spec['locale']]['project']['name']}\n"
                f"       /projects/{project['id']}\n"
                f"       /bim?project={project['id']}\n"
                f"       (locale={spec['locale']}, currency={spec['currency']}, "
                f"standard={spec['classification_standard']})"
            )
        print("\n  Issues collected during this run: see\n"
              f"  {ISSUES_FILE.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
