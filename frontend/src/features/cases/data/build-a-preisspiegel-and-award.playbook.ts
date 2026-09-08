// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Build a Preisspiegel and award" (DE).
//
// Cut one Gewerk out of the LV, send the same Anfrage to a shortlist of
// Nachunternehmer, level what comes back onto one scope, read the Preisspiegel
// side by side and award on the Wertung. Content strings are key plus inline
// English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "build-a-preisspiegel-and-award",
  order: 1050,
  category: "tendering",
  region: "DE",
  companyTypes: ["general-contractor", "project-manager", "cost-consultant"],
  roles: ["procurement-buyer", "estimator", "commercial-manager"],
  icon: "Table2",
  titleKey: "cases.build_a_preisspiegel_and_award.title",
  titleDefault: "Build a Preisspiegel and award",
  descKey: "cases.build_a_preisspiegel_and_award.desc",
  descDefault:
    "Send one work package to several Nachunternehmer, level what comes back onto the same scope, read the Preisspiegel side by side, and award on the Wertung instead of on the smallest number.",
  longDescKey: "cases.build_a_preisspiegel_and_award.longdesc",
  longDescDefault:
    "Small firms tell themselves they are too small for a system like this, so the Preisspiegel lives in a spreadsheet one person maintains and nobody else can check. That is how the cheapest incomplete offer wins: the NU who left two positions unpriced and excluded a third looks like the keen bidder until the Nachtrag arrives on site. Leveling first and awarding on the Wertung keeps the price you sign and the price you pay the same price.",
  estMinutes: 13,
  steps: [
    {
      id: "paket",
      icon: "Split",
      inputs: [
        { labelKey: "cases.build_a_preisspiegel_and_award.step.paket.in.lv", label: "Priced LV" },
        { labelKey: "cases.build_a_preisspiegel_and_award.step.paket.in.gewerk", label: "Trade to buy" },
      ],
      outputs: [
        { labelKey: "cases.build_a_preisspiegel_and_award.step.paket.out.paket", label: "Draft Vergabepaket" },
        { labelKey: "cases.build_a_preisspiegel_and_award.step.paket.out.positions", label: "Positions to be priced" },
      ],
      titleKey: "cases.build_a_preisspiegel_and_award.step.paket.title",
      titleDefault: "Cut the package out of the LV",
      whatKey: "cases.build_a_preisspiegel_and_award.step.paket.what",
      whatDefault:
        "Create the tender package straight from the LV: pick the positions that make up the one Gewerk you are buying, name the scope, and set the dates the work has to run to. The package starts as a draft you can still change.",
      whyKey: "cases.build_a_preisspiegel_and_award.step.paket.why",
      whyDefault:
        "Every NU has to price the same positions with the same quantities. A package cut from the LV is what makes that true; three hand-made spreadsheet extracts are what makes a Preisspiegel impossible two weeks later.",
      moduleLabel: "Tendering",
      moduleLabelKey: "nav.tendering",
      to: "/tendering",
    },
    {
      id: "nuwahl",
      icon: "UserCheck",
      inputs: [
        { labelKey: "cases.build_a_preisspiegel_and_award.step.nuwahl.in.register", label: "NU register" },
        { labelKey: "cases.build_a_preisspiegel_and_award.step.nuwahl.in.trade", label: "Trade and region" },
        { labelKey: "cases.build_a_preisspiegel_and_award.step.nuwahl.in.prequal", label: "Prequalification records" },
      ],
      outputs: [
        { labelKey: "cases.build_a_preisspiegel_and_award.step.nuwahl.out.shortlist", label: "Shortlist for the Anfrage" },
        { labelKey: "cases.build_a_preisspiegel_and_award.step.nuwahl.out.checked", label: "Checked credentials" },
      ],
      titleKey: "cases.build_a_preisspiegel_and_award.step.nuwahl.title",
      titleDefault: "Pick the Nachunternehmer you will ask",
      whatKey: "cases.build_a_preisspiegel_and_award.step.nuwahl.what",
      whatDefault:
        "Work through the NU register and shortlist the firms for this Gewerk: the right trade, capacity free in your window, references you can actually call, a valid Freistellungsbescheinigung under paragraph 48b EStG on file, and the Unbedenklichkeitsbescheinigungen of the Krankenkasse, the Berufsgenossenschaft and, where the trade falls under it, SOKA-BAU.",
      whyKey: "cases.build_a_preisspiegel_and_award.step.nuwahl.why",
      whyDefault:
        "Asking everybody wastes their time and yours, and asking the wrong firm costs more than that. A missing Freistellungsbescheinigung becomes a Bauabzugsteuer deduction you have to handle, and MiLoG leaves you answerable for the wages your NU pays. That belongs in the shortlist, not in the week of the award.",
      moduleLabel: "Subcontractors",
      moduleLabelKey: "subcontractors.title",
      to: "/projects/:projectId/subcontractors",
    },
    {
      id: "anfrage",
      icon: "Send",
      inputs: [
        { labelKey: "cases.build_a_preisspiegel_and_award.step.anfrage.in.paket", label: "Draft Vergabepaket" },
        { labelKey: "cases.build_a_preisspiegel_and_award.step.anfrage.in.shortlist", label: "NU shortlist" },
      ],
      outputs: [
        { labelKey: "cases.build_a_preisspiegel_and_award.step.anfrage.out.issued", label: "Issued Anfrage" },
        { labelKey: "cases.build_a_preisspiegel_and_award.step.anfrage.out.addenda", label: "Addenda on record" },
        { labelKey: "cases.build_a_preisspiegel_and_award.step.anfrage.out.angebote", label: "Returned Angebote" },
      ],
      titleKey: "cases.build_a_preisspiegel_and_award.step.anfrage.title",
      titleDefault: "Send one Anfrage to all of them",
      whatKey: "cases.build_a_preisspiegel_and_award.step.anfrage.what",
      whatDefault:
        "Issue the package to the whole shortlist at once, with the same position list, the same dates and the same terms. Answer what comes back as an addendum that reaches every bidder, then let the package collect the Angebote as they arrive.",
      whyKey: "cases.build_a_preisspiegel_and_award.step.anfrage.why",
      whyDefault:
        "The moment one NU prices a scope the others never saw, the comparison is dead and no amount of leveling brings it back. Issuing once and clarifying to everyone at once is what keeps all the columns answering the same question.",
      moduleLabel: "Tendering",
      moduleLabelKey: "nav.tendering",
      to: "/tendering",
    },
    {
      id: "abgleich",
      icon: "Combine",
      inputs: [
        { labelKey: "cases.build_a_preisspiegel_and_award.step.abgleich.in.angebote", label: "Returned Angebote" },
        { labelKey: "cases.build_a_preisspiegel_and_award.step.abgleich.in.positions", label: "Package positions" },
      ],
      outputs: [
        { labelKey: "cases.build_a_preisspiegel_and_award.step.abgleich.out.leveled", label: "Leveled offers" },
        { labelKey: "cases.build_a_preisspiegel_and_award.step.abgleich.out.gaps", label: "Gaps and exclusions flagged" },
      ],
      titleKey: "cases.build_a_preisspiegel_and_award.step.abgleich.title",
      titleDefault: "Level the offers to one scope",
      whatKey: "cases.build_a_preisspiegel_and_award.step.abgleich.what",
      whatDefault:
        "Open the leveling matrix and work down it line by line: the positions an NU left unpriced, the ones excluded in the Anschreiben, the Bedarfspositionen each firm handled differently, and the arithmetic where unit price times quantity does not give the total they wrote. Put the Nachlass and the Skonto where they belong, and price the gaps in at your own rate.",
      whyKey: "cases.build_a_preisspiegel_and_award.step.abgleich.why",
      whyDefault:
        "This is the work the spreadsheet never does. Until the missing positions are priced back in, the lowest column belongs to whoever read the LV least carefully, and you meet the difference again as a Nachtrag once the trade is on site.",
      moduleLabel: "Tendering",
      moduleLabelKey: "nav.tendering",
      to: "/tendering",
    },
    {
      id: "preisspiegel",
      icon: "Table2",
      inputs: [
        { labelKey: "cases.build_a_preisspiegel_and_award.step.preisspiegel.in.leveled", label: "Leveled offers" },
        { labelKey: "cases.build_a_preisspiegel_and_award.step.preisspiegel.in.budget", label: "Budget from the LV" },
      ],
      outputs: [
        { labelKey: "cases.build_a_preisspiegel_and_award.step.preisspiegel.out.spiegel", label: "Preisspiegel" },
        { labelKey: "cases.build_a_preisspiegel_and_award.step.preisspiegel.out.outliers", label: "Outliers per position" },
      ],
      titleKey: "cases.build_a_preisspiegel_and_award.step.preisspiegel.title",
      titleDefault: "Read the Preisspiegel side by side",
      whatKey: "cases.build_a_preisspiegel_and_award.step.preisspiegel.what",
      whatDefault:
        "Set the leveled offers out as a Preisspiegel, NU by column and position by row, then read down the rows rather than across the bottom line: where one firm sits far under everybody on a single position, where the spread is tight, where somebody stands alone at the top. Weigh the recommendation the package offers and the warning it raises when a low offer sits well below the median.",
      whyKey: "cases.build_a_preisspiegel_and_award.step.preisspiegel.why",
      whyDefault:
        "A bottom line tells you what a firm will charge. The rows tell you whether they understood the job. A position priced at a third of everyone else is not a discount, it is a misreading that turns up later as a Nachtrag with your name on it.",
      moduleLabel: "Tendering",
      moduleLabelKey: "nav.tendering",
      to: "/tendering",
    },
    {
      id: "vergabe",
      icon: "Gavel",
      inputs: [
        { labelKey: "cases.build_a_preisspiegel_and_award.step.vergabe.in.spiegel", label: "Preisspiegel" },
        { labelKey: "cases.build_a_preisspiegel_and_award.step.vergabe.in.criteria", label: "Wertung criteria" },
        { labelKey: "cases.build_a_preisspiegel_and_award.step.vergabe.in.credentials", label: "Checked credentials" },
      ],
      outputs: [
        { labelKey: "cases.build_a_preisspiegel_and_award.step.vergabe.out.nu", label: "Awarded NU" },
        { labelKey: "cases.build_a_preisspiegel_and_award.step.vergabe.out.order", label: "Order on the leveled scope" },
        { labelKey: "cases.build_a_preisspiegel_and_award.step.vergabe.out.letters", label: "Award and rejection letters" },
      ],
      titleKey: "cases.build_a_preisspiegel_and_award.step.vergabe.title",
      titleDefault: "Award on the Wertung and raise the order",
      whatKey: "cases.build_a_preisspiegel_and_award.step.vergabe.what",
      whatDefault:
        "Award on the whole Wertung and not on the smallest number: the leveled price, capacity for your dates, the references, the credentials you checked. The award writes the agreed rates back to the LV, gives you the award letter for the winner and the rejection notice for the rest, and drafts the order in Procurement. Open it there and check it carries the leveled scope rather than the raw Angebot.",
      whyKey: "cases.build_a_preisspiegel_and_award.step.vergabe.why",
      whyDefault:
        "The award is a decision; the order is the commitment. If the order goes out on the original Angebot, every gap you just priced in comes straight back as a Nachtrag and you paid for the leveling work twice.",
      moduleLabel: "Procurement",
      moduleLabelKey: "procurement.title",
      to: "/projects/:projectId/procurement",
    },
    {
      id: "vermerk",
      icon: "NotebookPen",
      inputs: [
        { labelKey: "cases.build_a_preisspiegel_and_award.step.vermerk.in.spiegel", label: "Preisspiegel at award" },
        { labelKey: "cases.build_a_preisspiegel_and_award.step.vermerk.in.adjustments", label: "Leveling adjustments" },
        { labelKey: "cases.build_a_preisspiegel_and_award.step.vermerk.in.decision", label: "Award decision" },
      ],
      outputs: [
        { labelKey: "cases.build_a_preisspiegel_and_award.step.vermerk.out.vermerk", label: "Vergabevermerk" },
        { labelKey: "cases.build_a_preisspiegel_and_award.step.vermerk.out.trail", label: "Auditable award trail" },
      ],
      titleKey: "cases.build_a_preisspiegel_and_award.step.vermerk.title",
      titleDefault: "Put the reasoning on record",
      whatKey: "cases.build_a_preisspiegel_and_award.step.vermerk.what",
      whatDefault:
        "File the Vergabevermerk: the Preisspiegel as it stood on the day, the adjustments you made and what each one was for, the criteria you weighed, and the reason the package went where it went.",
      whyKey: "cases.build_a_preisspiegel_and_award.step.vermerk.why",
      whyDefault:
        "Six months on, nobody asks what you paid. They ask why the more expensive NU got the work. One short document written on the day answers a partner, an auditor or a losing bidder without anyone having to remember.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
