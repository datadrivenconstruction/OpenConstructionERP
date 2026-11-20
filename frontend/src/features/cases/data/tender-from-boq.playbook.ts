// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Run a tender from a BOQ".
//
// Shows how a priced bill of quantities becomes a competitive tender. It starts
// in the BOQ, then stays in Tendering for the four moves that matter: create a
// package from the bill, invite subcontractors, compare the offers and award a
// winner. Awarding writes the agreed rates back into the BOQ and hands a draft
// purchase order to Procurement, so the loop closes without rekeying.
//
// Every content string is a key plus an inline English default. These live ONLY
// here and are never added to en.ts (only the framework chrome lives there).
// Module chips reuse existing translated nav/title keys so they localize for
// free. The package, distribution, comparison and award steps all open the
// Tendering module, which has no project-scoped route, so they use the plain
// `/tendering` path and rely on the active-project context set by "Go".

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "tender-from-boq",
  order: 20,
  category: "tendering",
  companyTypes: ["general-contractor", "cost-consultant", "project-manager"],
  roles: ["estimator", "quantity-surveyor", "procurement-buyer"],
  icon: "Handshake",
  titleKey: "cases.tender_from_boq.title",
  titleDefault: "Run a tender from a BOQ",
  descKey: "cases.tender_from_boq.desc",
  descDefault:
    "Take a priced bill of quantities out to market: package it, invite the subcontractors, level their bids and award the winner. Five steps, end to end.",
  estMinutes: 12,
  steps: [
    {
      id: "boq",
      icon: "Table2",
      inputs: [
        {
          labelKey: "cases.tender_from_boq.step.boq.in.boq",
          label: "Priced BOQ",
        },
        {
          labelKey: "cases.tender_from_boq.step.boq.in.validation",
          label: "Validation report",
        },
      ],
      outputs: [
        {
          labelKey: "cases.tender_from_boq.step.boq.out.scope",
          label: "Confirmed tender scope",
        },
        {
          labelKey: "cases.tender_from_boq.step.boq.out.baseline",
          label: "Budget baseline",
        },
      ],
      titleKey: "cases.tender_from_boq.step.boq.title",
      titleDefault: "Open the priced BOQ",
      whatKey: "cases.tender_from_boq.step.boq.what",
      whatDefault:
        "Open the bill you intend to tender and confirm it is fully priced and validated. The package is generated straight off this BOQ, so its positions and quantities are exactly what the bidders will price.",
      whyKey: "cases.tender_from_boq.step.boq.why",
      whyDefault:
        "One clean bill is the level playing field. When every firm prices the same scope and the same quantities, the offers that come back are genuinely comparable rather than a guessing game.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "package",
      icon: "Layers",
      inputs: [
        {
          labelKey: "cases.tender_from_boq.step.package.in.boq",
          label: "Source BOQ",
        },
        {
          labelKey: "cases.tender_from_boq.step.package.in.deadline",
          label: "Submission deadline",
        },
      ],
      outputs: [
        {
          labelKey: "cases.tender_from_boq.step.package.out.package",
          label: "Tender package",
        },
        {
          labelKey: "cases.tender_from_boq.step.package.out.schedule",
          label: "Bidder pricing schedule",
        },
      ],
      titleKey: "cases.tender_from_boq.step.package.title",
      titleDefault: "Create the tender package",
      whatKey: "cases.tender_from_boq.step.package.what",
      whatDefault:
        "In Tendering, start a new package, set this BOQ as its source and put a submission deadline on it. The package carries the priced positions and quantities out for firms to bid against.",
      whyKey: "cases.tender_from_boq.step.package.why",
      whyDefault:
        "The package is what makes an in-house estimate issuable. Building it from the BOQ keeps scope, quantities and your budget number stitched to the estimate you already stand behind.",
      moduleLabel: "Tenders",
      moduleLabelKey: "tenders.title",
      to: "/tenders",
    },
    {
      id: "distribute",
      icon: "Send",
      inputs: [
        {
          labelKey: "cases.tender_from_boq.step.distribute.in.package",
          label: "Tender package",
        },
        {
          labelKey: "cases.tender_from_boq.step.distribute.in.directory",
          label: "Subcontractor directory",
        },
      ],
      outputs: [
        {
          labelKey: "cases.tender_from_boq.step.distribute.out.invites",
          label: "Invitations sent",
        },
        {
          labelKey: "cases.tender_from_boq.step.distribute.out.status",
          label: "Delivery status",
        },
      ],
      titleKey: "cases.tender_from_boq.step.distribute.title",
      titleDefault: "Invite subcontractors",
      whatKey: "cases.tender_from_boq.step.distribute.what",
      whatDefault:
        "Draw the invitation list from your subcontractor directory or key in firms by hand, then send it out. Every recipient reads as sent, pending or failed, so no invitation quietly goes missing.",
      whyKey: "cases.tender_from_boq.step.distribute.why",
      whyDefault:
        "A wider field of qualified bidders is what sharpens the price. Issuing from a single list also leaves a clean audit of who was asked and on what date, which matters if the award is ever questioned.",
      moduleLabel: "Tenders",
      moduleLabelKey: "tenders.title",
      to: "/tenders",
    },
    {
      id: "compare",
      icon: "FileBarChart",
      inputs: [
        {
          labelKey: "cases.tender_from_boq.step.compare.in.bids",
          label: "Returned bids",
        },
        {
          labelKey: "cases.tender_from_boq.step.compare.in.budget",
          label: "Budget baseline",
        },
      ],
      outputs: [
        {
          labelKey: "cases.tender_from_boq.step.compare.out.matrix",
          label: "Levelled comparison",
        },
        {
          labelKey: "cases.tender_from_boq.step.compare.out.outliers",
          label: "Outlier flags",
        },
      ],
      titleKey: "cases.tender_from_boq.step.compare.title",
      titleDefault: "Compare the bids",
      whatKey: "cases.tender_from_boq.step.compare.what",
      whatDefault:
        "As offers land, set them side by side against your budget. The comparison flags the high and low outliers position by position, and the leveling matrix normalises qualifications so you compare like for like.",
      whyKey: "cases.tender_from_boq.step.compare.why",
      whyDefault:
        "The lowest bottom line is often the riskiest, not the best. Comparing rate against rate exposes the missing item, the keying error and the suicide price before you sign anything.",
      moduleLabel: "Tenders",
      moduleLabelKey: "tenders.title",
      to: "/tenders",
    },
    {
      id: "award",
      icon: "Handshake",
      inputs: [
        {
          labelKey: "cases.tender_from_boq.step.award.in.comparison",
          label: "Levelled comparison",
        },
        {
          labelKey: "cases.tender_from_boq.step.award.in.winner",
          label: "Winning offer",
        },
      ],
      outputs: [
        {
          labelKey: "cases.tender_from_boq.step.award.out.award",
          label: "Awarded subcontract",
        },
        {
          labelKey: "cases.tender_from_boq.step.award.out.rates",
          label: "Updated BOQ rates",
        },
        {
          labelKey: "cases.tender_from_boq.step.award.out.po",
          label: "Draft purchase order",
        },
      ],
      titleKey: "cases.tender_from_boq.step.award.title",
      titleDefault: "Award the winner",
      whatKey: "cases.tender_from_boq.step.award.what",
      whatDefault:
        "Select the winning offer and award it. The agreed rates write back into the BOQ, the unsuccessful bids are closed off and a draft purchase order is seeded in Procurement.",
      whyKey: "cases.tender_from_boq.step.award.why",
      whyDefault:
        "Awarding ties the loop shut. Your estimate is refreshed with real market rates and procurement starts from live figures, so nobody rekeys a bill and nobody transposes a number.",
      moduleLabel: "Tenders",
      moduleLabelKey: "tenders.title",
      to: "/tenders",
    },
  ],
};

export default playbook;
