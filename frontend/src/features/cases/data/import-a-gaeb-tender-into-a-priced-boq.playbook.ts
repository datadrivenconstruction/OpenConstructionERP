// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Import a GAEB tender into a priced BOQ".
//
// Take a client GAEB tender file (X83 / X81), bring it into the platform as a
// bill, price the positions and validate the structure, then return a priced
// GAEB. Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "import-a-gaeb-tender-into-a-priced-boq",
  order: 1000,
  category: "estimating",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant"],
  icon: "FileInput",
  titleKey: "cases.import_a_gaeb_tender_into_a_priced_boq.title",
  titleDefault: "Import a GAEB tender into a priced BOQ",
  descKey: "cases.import_a_gaeb_tender_into_a_priced_boq.desc",
  descDefault:
    "Receive a GAEB tender file, bring it in as a bill without rekeying, price the positions, validate the structure and hand back a priced GAEB the client can read straight into their own system.",
  longDescKey: "cases.import_a_gaeb_tender_into_a_priced_boq.longdesc",
  longDescDefault:
    "GAEB is the open exchange standard for tender bills in the German-speaking market. The point of importing it rather than retyping it is that the position numbers, quantities and text stay byte-for-byte what the client issued, so your price answers exactly the bill they asked you to price.",
  estMinutes: 12,
  steps: [
    {
      id: "receive",
      icon: "FileInput",
      inputs: [
        { labelKey: "cases.import_a_gaeb_tender_into_a_priced_boq.step.receive.in.file", label: "GAEB tender file" },
        { labelKey: "cases.import_a_gaeb_tender_into_a_priced_boq.step.receive.in.invite", label: "Invitation to tender" },
      ],
      outputs: [
        { labelKey: "cases.import_a_gaeb_tender_into_a_priced_boq.step.receive.out.filed", label: "Filed tender document" },
      ],
      titleKey: "cases.import_a_gaeb_tender_into_a_priced_boq.step.receive.title",
      titleDefault: "Receive the GAEB file",
      whatKey: "cases.import_a_gaeb_tender_into_a_priced_boq.step.receive.what",
      whatDefault:
        "Save the GAEB file the client issued into the project files alongside the invitation, so the version you priced is the version on record.",
      whyKey: "cases.import_a_gaeb_tender_into_a_priced_boq.step.receive.why",
      whyDefault:
        "Tenders get reissued. Filing the exact file you worked from means a later query about which revision you priced has a one-click answer instead of an argument.",
      moduleLabel: "Files",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
    {
      id: "import",
      icon: "Upload",
      inputs: [
        { labelKey: "cases.import_a_gaeb_tender_into_a_priced_boq.step.import.in.file", label: "GAEB tender file" },
      ],
      outputs: [
        { labelKey: "cases.import_a_gaeb_tender_into_a_priced_boq.step.import.out.boq", label: "Bill with positions" },
        { labelKey: "cases.import_a_gaeb_tender_into_a_priced_boq.step.import.out.structure", label: "Preserved LV structure" },
      ],
      titleKey: "cases.import_a_gaeb_tender_into_a_priced_boq.step.import.title",
      titleDefault: "Import it as a bill",
      whatKey: "cases.import_a_gaeb_tender_into_a_priced_boq.step.import.what",
      whatDefault:
        "Import the GAEB into a new bill. The groups, positions, quantities, units and long text come across intact, so you have an empty priced-out column to fill and nothing else to retype.",
      whyKey: "cases.import_a_gaeb_tender_into_a_priced_boq.step.import.why",
      whyDefault:
        "Retyping a bill of a few hundred positions is where transposed quantities and dropped items creep in. Importing keeps your offer tied to the client's exact wording and numbering.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "price",
      icon: "Calculator",
      inputs: [
        { labelKey: "cases.import_a_gaeb_tender_into_a_priced_boq.step.price.in.positions", label: "Unpriced positions" },
        { labelKey: "cases.import_a_gaeb_tender_into_a_priced_boq.step.price.in.rates", label: "Cost catalog rates" },
      ],
      outputs: [
        { labelKey: "cases.import_a_gaeb_tender_into_a_priced_boq.step.price.out.priced", label: "Priced positions" },
      ],
      titleKey: "cases.import_a_gaeb_tender_into_a_priced_boq.step.price.title",
      titleDefault: "Price the positions",
      whatKey: "cases.import_a_gaeb_tender_into_a_priced_boq.step.price.what",
      whatDefault:
        "Match each position to a rate from the cost catalog or an assembly, adjusting for the wording where the standard rate does not quite fit, until every line carries a unit price.",
      whyKey: "cases.import_a_gaeb_tender_into_a_priced_boq.step.price.why",
      whyDefault:
        "A rate pulled from a maintained catalog is defensible and fast. Reading the position text as you price it is where you catch the qualification hidden in a description that would otherwise cost you on site.",
      moduleLabel: "Catalog",
      moduleLabelKey: "nav.catalog",
      to: "/catalog",
    },
    {
      id: "validate",
      icon: "ShieldCheck",
      inputs: [
        { labelKey: "cases.import_a_gaeb_tender_into_a_priced_boq.step.validate.in.priced", label: "Priced bill" },
      ],
      outputs: [
        { labelKey: "cases.import_a_gaeb_tender_into_a_priced_boq.step.validate.out.report", label: "Validation report" },
        { labelKey: "cases.import_a_gaeb_tender_into_a_priced_boq.step.validate.out.gaps", label: "Gaps flagged" },
      ],
      titleKey: "cases.import_a_gaeb_tender_into_a_priced_boq.step.validate.title",
      titleDefault: "Validate before you send",
      whatKey: "cases.import_a_gaeb_tender_into_a_priced_boq.step.validate.what",
      whatDefault:
        "Run the bill through validation to catch any position left at zero, a quantity that does not tie, or a GAEB structure rule the return file must honour.",
      whyKey: "cases.import_a_gaeb_tender_into_a_priced_boq.step.validate.why",
      whyDefault:
        "A single unpriced position can void a submission or hide a loss you carry all the way to site. Validation turns a last-minute scramble into a green light you can trust.",
      moduleLabel: "Validation",
      moduleLabelKey: "validation.title",
      to: "/validation",
    },
    {
      id: "return",
      icon: "Send",
      inputs: [
        { labelKey: "cases.import_a_gaeb_tender_into_a_priced_boq.step.return.in.priced", label: "Validated priced bill" },
      ],
      outputs: [
        { labelKey: "cases.import_a_gaeb_tender_into_a_priced_boq.step.return.out.gaeb", label: "Priced GAEB return" },
        { labelKey: "cases.import_a_gaeb_tender_into_a_priced_boq.step.return.out.offer", label: "Tender offer" },
      ],
      titleKey: "cases.import_a_gaeb_tender_into_a_priced_boq.step.return.title",
      titleDefault: "Return the priced GAEB",
      whatKey: "cases.import_a_gaeb_tender_into_a_priced_boq.step.return.what",
      whatDefault:
        "Export the priced bill back to GAEB and issue it as your offer, so the client reads your prices straight into their evaluation without touching a keyboard.",
      whyKey: "cases.import_a_gaeb_tender_into_a_priced_boq.step.return.why",
      whyDefault:
        "An offer that loads cleanly into the client's system is easier to award. Returning the same open format you were given is a small courtesy that keeps your bid at the front of the pile.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
