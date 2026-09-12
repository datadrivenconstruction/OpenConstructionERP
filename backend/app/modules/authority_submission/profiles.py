# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Built-in, jurisdiction-neutral submission profiles (seed data).

These ship with the platform so the factory is useful out of the box without any
regional pack. They are deliberately neutral:

- ``generic_xml`` - a plain structured document, the fallback when no dialect
  applies.
- ``gaeb_x83`` - shaped after the DACH GAEB X83 tender-exchange pattern (a root
  element wrapping award info and a list of priced positions). This is the
  proven pattern the whole engine generalises; it is kept content-neutral so it
  is not tied to any one country's tender law.
- ``cobie`` - shaped after the COBie asset-handover pattern (a register of
  facilities / spaces handed to a client at closeout).

Where national dialects plug in
===============================
A regional pack registers additional profiles the same way - as rows with their
own ``field_spec`` and ``root_element``. For example an ``RU Minstroy expertise``
profile would set ``format_key="minstroy_xml"``, ``jurisdiction="RU"``, its own
``root_element`` and the Minstroy field set; a UK ``eplan`` profile would set
``format_key="eplan"``, ``jurisdiction="GB"``. Nothing in the engine is
country-specific - only these data rows are.

``field_spec`` descriptor keys
==============================
    name        - payload key (required)
    type        - string | integer | number | boolean | date | array | object
    required    - bool (default False)
    xml_tag     - element name in the output (default: name)
    label       - human label for the render view (default: humanised name)
    item_tag    - array only: element name for each item (default: "item")
    fields      - array/object only: nested field_spec for each item / the object
"""

from __future__ import annotations

from typing import Any

# Each entry is the kwargs for a SubmissionProfile row. Matched on
# (name, format_key) so re-seeding is idempotent.
BUILTIN_PROFILES: list[dict[str, Any]] = [
    {
        "name": "Generic XML document",
        "jurisdiction": None,
        "format_key": "generic_xml",
        "schema_version": "1.0",
        "root_element": "Document",
        "description": (
            "A plain structured XML document. Use when no jurisdiction-specific "
            "dialect applies, or as a starting point for a custom profile."
        ),
        "field_spec": [
            {"name": "title", "type": "string", "required": True, "xml_tag": "Title"},
            {"name": "reference", "type": "string", "required": False, "xml_tag": "Reference"},
            {"name": "date", "type": "date", "required": False, "xml_tag": "Date"},
            {"name": "author", "type": "string", "required": False, "xml_tag": "Author"},
            {"name": "body", "type": "string", "required": False, "xml_tag": "Body"},
        ],
    },
    {
        "name": "Tender exchange (GAEB X83 pattern)",
        "jurisdiction": None,
        "format_key": "gaeb_x83",
        "schema_version": "3.3",
        "root_element": "TenderExchange",
        "description": (
            "Shaped after the DACH GAEB X83 tender-award exchange: award "
            "metadata plus a list of priced positions. Content-neutral - the "
            "proven pattern the engine generalises. A national tender dialect "
            "plugs in as its own profile row."
        ),
        "field_spec": [
            {"name": "project_name", "type": "string", "required": True, "xml_tag": "ProjectName"},
            {"name": "currency", "type": "string", "required": True, "xml_tag": "Currency"},
            {"name": "award_date", "type": "date", "required": False, "xml_tag": "AwardDate"},
            {
                "name": "positions",
                "type": "array",
                "required": True,
                "xml_tag": "Positions",
                "item_tag": "Position",
                "fields": [
                    {"name": "ordinal", "type": "string", "required": True, "xml_tag": "Ordinal"},
                    {
                        "name": "description",
                        "type": "string",
                        "required": True,
                        "xml_tag": "Description",
                    },
                    {"name": "unit", "type": "string", "required": True, "xml_tag": "Unit"},
                    {"name": "quantity", "type": "number", "required": True, "xml_tag": "Quantity"},
                    {
                        "name": "unit_rate",
                        "type": "number",
                        "required": True,
                        "xml_tag": "UnitRate",
                    },
                ],
            },
            {"name": "total", "type": "number", "required": False, "xml_tag": "Total"},
        ],
    },
    {
        "name": "Asset handover (COBie pattern)",
        "jurisdiction": None,
        "format_key": "cobie",
        "schema_version": "2.4",
        "root_element": "AssetHandover",
        "description": (
            "Shaped after the COBie asset-handover pattern: facility metadata "
            "plus a register of spaces handed to the client at closeout. "
            "Content-neutral."
        ),
        "field_spec": [
            {"name": "facility_name", "type": "string", "required": True, "xml_tag": "FacilityName"},
            {"name": "site", "type": "string", "required": False, "xml_tag": "Site"},
            {
                "name": "spaces",
                "type": "array",
                "required": True,
                "xml_tag": "Spaces",
                "item_tag": "Space",
                "fields": [
                    {"name": "name", "type": "string", "required": True, "xml_tag": "Name"},
                    {"name": "category", "type": "string", "required": False, "xml_tag": "Category"},
                    {"name": "area", "type": "number", "required": False, "xml_tag": "Area"},
                ],
            },
        ],
    },
    # ── Regional profiles (OC-19) ──────────────────────────────────────────
    #
    # Each profile names a jurisdiction so the frontend can filter by country.
    # The document_checklist array is a soft requirement list: names the
    # documents the jurisdiction typically requires, and the user checks them
    # off when the document has been attached. The platform does not enforce
    # submission - "internally registered" is the furthest it goes without a
    # proven external integration.
    {
        "name": "Bauantrag / Bauvoranfrage (Germany)",
        "jurisdiction": "DE",
        "format_key": "bauantrag_xml",
        "schema_version": "1.0",
        "root_element": "Bauantrag",
        "description": (
            "German building permit application. Lists the documents a "
            "Bauaufsichtsbehorde typically requires: site plan, floor plans, "
            "sections, structural analysis, energy certificate, fire safety "
            "concept, statistics form. Mark each document as attached when "
            "its revision is ready. No automatic submission to the authority - "
            "the platform registers the package internally."
        ),
        "field_spec": [
            {"name": "project_name", "type": "string", "required": True, "xml_tag": "Projektbezeichnung"},
            {"name": "bauherr", "type": "string", "required": True, "xml_tag": "Bauherr", "label": "Building owner"},
            {
                "name": "entwurfsverfasser",
                "type": "string",
                "required": False,
                "xml_tag": "Entwurfsverfasser",
                "label": "Architect / designer",
            },
            {
                "name": "gemarkung",
                "type": "string",
                "required": False,
                "xml_tag": "Gemarkung",
                "label": "Cadastral district",
            },
            {
                "name": "flurstueck",
                "type": "string",
                "required": False,
                "xml_tag": "Flurstueck",
                "label": "Plot number",
            },
            {
                "name": "bauvorhaben",
                "type": "string",
                "required": True,
                "xml_tag": "Bauvorhaben",
                "label": "Description of works",
            },
            {
                "name": "antragsdatum",
                "type": "date",
                "required": False,
                "xml_tag": "Antragsdatum",
                "label": "Application date",
            },
            {
                "name": "document_checklist",
                "type": "array",
                "required": False,
                "xml_tag": "Unterlagen",
                "item_tag": "Unterlage",
                "label": "Required documents",
                "fields": [
                    {
                        "name": "document_name",
                        "type": "string",
                        "required": True,
                        "xml_tag": "Bezeichnung",
                        "label": "Document",
                    },
                    {"name": "revision", "type": "string", "required": False, "xml_tag": "Revision"},
                    {
                        "name": "attached",
                        "type": "boolean",
                        "required": False,
                        "xml_tag": "Beigefuegt",
                        "label": "Attached",
                    },
                    {"name": "notes", "type": "string", "required": False, "xml_tag": "Anmerkung", "label": "Notes"},
                ],
                "default_items": [
                    {"document_name": "Lageplan (site plan)", "attached": False},
                    {"document_name": "Grundrisse (floor plans)", "attached": False},
                    {"document_name": "Schnitte (sections)", "attached": False},
                    {"document_name": "Ansichten (elevations)", "attached": False},
                    {"document_name": "Baubeschreibung (building description)", "attached": False},
                    {"document_name": "Statik / Standsicherheitsnachweis (structural analysis)", "attached": False},
                    {"document_name": "Waermeschutznachweis / Energieausweis (energy certificate)", "attached": False},
                    {"document_name": "Brandschutzkonzept (fire safety concept)", "attached": False},
                    {"document_name": "Schallschutznachweis (acoustic report)", "attached": False},
                    {"document_name": "Statistik-Formblatt (statistics form)", "attached": False},
                    {"document_name": "Entwasserungsplan (drainage plan)", "attached": False},
                    {"document_name": "Freiflachenplan (landscape plan)", "attached": False},
                ],
            },
        ],
    },
    {
        "name": "Document submission package (generic)",
        "jurisdiction": None,
        "format_key": "doc_package_xml",
        "schema_version": "1.0",
        "root_element": "SubmissionPackage",
        "description": (
            "A jurisdiction-neutral document package. List the documents your "
            "authority or client requires, check them off as attached, and "
            "record the submission reference when you hand the package over. "
            "No legal promises - the completeness is what you mark it as."
        ),
        "field_spec": [
            {"name": "package_title", "type": "string", "required": True, "xml_tag": "PackageTitle"},
            {
                "name": "recipient",
                "type": "string",
                "required": False,
                "xml_tag": "Recipient",
                "label": "Authority / recipient",
            },
            {
                "name": "reference_number",
                "type": "string",
                "required": False,
                "xml_tag": "ReferenceNumber",
                "label": "External reference",
            },
            {"name": "submission_date", "type": "date", "required": False, "xml_tag": "SubmissionDate"},
            {"name": "responsible_person", "type": "string", "required": False, "xml_tag": "ResponsiblePerson"},
            {
                "name": "document_checklist",
                "type": "array",
                "required": False,
                "xml_tag": "Documents",
                "item_tag": "Document",
                "label": "Document checklist",
                "fields": [
                    {
                        "name": "document_name",
                        "type": "string",
                        "required": True,
                        "xml_tag": "Name",
                        "label": "Document",
                    },
                    {"name": "revision", "type": "string", "required": False, "xml_tag": "Revision"},
                    {"name": "attached", "type": "boolean", "required": False, "xml_tag": "Attached"},
                    {"name": "notes", "type": "string", "required": False, "xml_tag": "Notes"},
                ],
            },
        ],
    },
]


__all__ = ["BUILTIN_PROFILES"]
