// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Bid for a public works contract under the Kbt." (HU).
//
// The Hungarian public bid round as a bidder actually runs it. The estimated
// value decides the regime, the documents arrive through the EKR and go back
// the same way, the unpriced itemised bill is priced line by line, the price
// has to survive a request to justify it, and the exclusion grounds and the
// suitability evidence travel with the offer rather than after it. Content
// strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "bid-for-a-public-works-contract-under-the-kbt",
  order: 1241,
  region: "HU",
  category: "tendering",
  companyTypes: ["general-contractor", "subcontractor", "cost-consultant"],
  roles: ["estimator", "procurement-buyer", "commercial-manager", "quantity-surveyor"],
  icon: "Landmark",
  titleKey: "cases.bid_for_a_public_works_contract_under_the_kbt.title",
  titleDefault: "Bid for a public works contract under the Kbt.",
  descKey: "cases.bid_for_a_public_works_contract_under_the_kbt.desc",
  descDefault:
    "Settle which procurement regime the job falls under, price the arazatlan koltsegvetesi kiiras tetel by tetel, build the price so it survives a request to justify it, and get the offer into the EKR complete and on time.",
  longDescKey: "cases.bid_for_a_public_works_contract_under_the_kbt.longdesc",
  longDescDefault:
    "Public work in Hungary is bought under Act CXLIII of 2015 on public procurement, the Kbt., with the detail for construction sitting in Government Decree 322/2015 (X. 30.). Two things about it decide whether a good price ever gets read. The whole procedure runs through the EKR, the electronic public procurement system, so a submission is a system event with a timestamp rather than an envelope, and a late one does not exist. And a bid is judged on completeness before it is judged on money: a tetel left at zero, a missing exclusion-ground declaration or an unanswered request to complete the file takes the offer out of the evaluation before anyone opens the total. This case builds the offer in the order the procedure reads it.",
  estMinutes: 14,
  steps: [
    {
      id: "value",
      icon: "Landmark",
      inputs: [
        { labelKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.value.in.notice", label: "Contract notice" },
        { labelKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.value.in.scope", label: "Scope of works" },
      ],
      outputs: [
        { labelKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.value.out.regime", label: "Procedure and regime on record" },
        { labelKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.value.out.value", label: "Estimated contract value" },
      ],
      titleKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.value.title",
      titleDefault: "Settle which regime the job is bought under",
      whatKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.value.what",
      whatDefault:
        "Open the tender as a procedure of its own and record the becsult ertek of the whole work, the procedure type the contracting authority chose and whether it sits above or below the national threshold. Read the value across the whole work rather than per lot, because that is how the threshold is measured.",
      whyKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.value.why",
      whyDefault:
        "The national thresholds are set in the central budget act for the year and republished by the Kozbeszerzesi Hatosag each January, so last year's figure is the wrong figure and nobody is going to warn you. Kbt. 19. governs how the estimated value is worked out, and choosing a method that keeps a work under a threshold is the finding that undoes a whole procedure, so the number you record here is the number the file has to defend.",
      moduleLabel: "Tendering",
      moduleLabelKey: "tendering.title",
      to: "/tendering",
    },
    {
      id: "docs",
      icon: "FolderInput",
      inputs: [
        { labelKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.docs.in.ekr", label: "EKR document set" },
        { labelKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.docs.in.notice", label: "Contract notice" },
      ],
      outputs: [
        { labelKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.docs.out.filed", label: "Filed tender documents" },
        { labelKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.docs.out.dates", label: "Submission and validity dates" },
      ],
      titleKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.docs.title",
      titleDefault: "File the EKR document set as issued",
      whatKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.docs.what",
      whatDefault:
        "Save the kozbeszerzesi dokumentumok exactly as they came out of the EKR, with the date each item arrived. Record the deadline for offers and the ajanlati kotottseg, the period your price is bound for, next to them.",
      whyKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.docs.why",
      whyDefault:
        "Documents are corrected and reissued during the bidding period, and every clarification the authority answers goes to all bidders. Keeping the version you actually priced is what lets you show weeks later which set your offer answers, and the bound period is what tells you how long a win can still cost you if your suppliers move.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
    {
      id: "boq",
      icon: "Table2",
      inputs: [
        { labelKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.boq.in.kiiras", label: "Arazatlan koltsegvetesi kiiras" },
        { labelKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.boq.in.drawings", label: "Tender drawings" },
      ],
      outputs: [
        { labelKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.boq.out.priced", label: "Priced tetel list" },
        { labelKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.boq.out.total", label: "Offer total" },
      ],
      titleKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.boq.title",
      titleDefault: "Price the arazatlan koltsegvetesi kiiras",
      whatKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.boq.what",
      whatDefault:
        "Read the unpriced itemised bill in as the bill you price, keeping the tetel numbering, the unit and the quantity the authority issued. Put a unit price on every line, including the ones you would normally carry inside another rate, and read each tetel description before you price it.",
      whyKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.boq.why",
      whyDefault:
        "Government Decree 322/2015 (X. 30.) is what puts the itemised bill at the centre of a Hungarian construction procurement, and the priced version you return is read line against line rather than as a total. One tetel left at zero, one renumbered line or one unit quietly changed is enough to make the offer unreadable against the others, and an unreadable offer is not a cheap offer.",
      moduleLabel: "Bill of Quantities",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "basis",
      icon: "Database",
      inputs: [
        { labelKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.basis.in.rates", label: "Unit rates" },
        { labelKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.basis.in.norms", label: "Norm and rezsioradij basis" },
      ],
      outputs: [
        { labelKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.basis.out.basis", label: "Stated basis of estimate" },
        { labelKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.basis.out.answer", label: "Justification ready to send" },
      ],
      titleKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.basis.title",
      titleDefault: "Write down where the price came from",
      whatKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.basis.what",
      whatDefault:
        "Record the basis under the offer while you still remember it: which norm set the labour hours, which rezsioradij the dij is built on, which quotes carry the anyag, what the preliminaries assume and which risks are priced rather than excluded.",
      whyKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.basis.why",
      whyDefault:
        "Kbt. 72. lets the contracting authority demand a justification where a price or a cost element looks disproportionately low, and it may reject an offer whose justification does not stand up. That request arrives with a short deadline, weeks after you priced, and the difference between keeping the job and losing it is whether the calculation behind the number already exists in writing or has to be rebuilt from memory in three days.",
      moduleLabel: "Basis of Estimate",
      moduleLabelKey: "nav.estimate_basis",
      to: "/estimate-basis",
    },
    {
      id: "eekd",
      icon: "ClipboardCheck",
      inputs: [
        { labelKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.eekd.in.company", label: "Company and reference records" },
        { labelKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.eekd.in.criteria", label: "Suitability requirements" },
      ],
      outputs: [
        { labelKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.eekd.out.eekd", label: "Completed EEKD" },
        { labelKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.eekd.out.declarations", label: "Exclusion-ground declarations" },
      ],
      titleKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.eekd.title",
      titleDefault: "Assemble the qualification half of the offer",
      whatKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.eekd.what",
      whatDefault:
        "Build the non-price half of the bid as its own package: the egyseges europai kozbeszerzesi dokumentum, the declarations on the kizaro okok, the references and the professionals the alkalmassag criteria ask for, and the ajanlati biztositek where the notice requires one. Name any capacity provider and any subcontractor the notice makes you name.",
      whyKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.eekd.why",
      whyDefault:
        "In an EU-threshold procedure the EEKD is a preliminary declaration and the underlying certificates are called in later, which tempts a bidder to treat the form as a formality. It is not one: a declaration that does not match the certificates that follow it is worse than a missing reference, because it reads as a false statement rather than as a gap, and the consequence is exclusion rather than a request to complete the file.",
      moduleLabel: "Bid Management",
      moduleLabelKey: "nav.bid_management",
      to: "/bid-management",
    },
    {
      id: "check",
      icon: "ShieldCheck",
      inputs: [
        { labelKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.check.in.priced", label: "Priced bill" },
        { labelKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.check.in.package", label: "Qualification package" },
      ],
      outputs: [
        { labelKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.check.out.report", label: "Validation report" },
        { labelKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.check.out.cleared", label: "Findings cleared" },
      ],
      titleKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.check.title",
      titleDefault: "Check the offer against the tender it answers",
      whatKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.check.what",
      whatDefault:
        "Run validation over the whole submission before it goes anywhere: every tetel priced, quantities and units unchanged from the kiiras, the totals adding up, and every document the notice lists actually present in the package.",
      whyKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.check.why",
      whyDefault:
        "Everything an evaluator can reject an offer for is mechanical, and every one of those things is cheaper to find here than in an answer to a hianypotlas under a three-day clock. This is also the last moment at which a decimal place in the total is still an internal problem.",
      moduleLabel: "Validation",
      moduleLabelKey: "validation.title",
      to: "/validation",
    },
    {
      id: "submit",
      icon: "Send",
      inputs: [
        { labelKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.submit.in.package", label: "Complete offer package" },
        { labelKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.submit.in.deadline", label: "Submission deadline" },
      ],
      outputs: [
        { labelKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.submit.out.submitted", label: "Submitted offer" },
        { labelKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.submit.out.receipt", label: "Dated submission record" },
      ],
      titleKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.submit.title",
      titleDefault: "Submit through the EKR and log what went",
      whatKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.submit.what",
      whatDefault:
        "Send the offer up through the EKR before the deadline and keep the transmittal record of what went, when, and under which procedure identifier. Communication in the procedure runs through the same system, so the record and the correspondence stay in one place.",
      whyKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.submit.why",
      whyDefault:
        "The EKR timestamps the submission, and a bid that lands after the deadline is not a late bid, it is not a bid. Bidders lose work every year to an upload begun twenty minutes before the hour on a file that turned out to be larger than the connection, which is a scheduling failure rather than a commercial one.",
      moduleLabel: "Transmittals",
      moduleLabelKey: "transmittals.title",
      to: "/files/transmittals",
    },
    {
      id: "hianypotlas",
      icon: "MessageSquarePlus",
      inputs: [
        { labelKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.hianypotlas.in.request", label: "Request to complete the file" },
        { labelKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.hianypotlas.in.record", label: "Submitted offer record" },
      ],
      outputs: [
        { labelKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.hianypotlas.out.reply", label: "Answer on the thread" },
        { labelKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.hianypotlas.out.kept", label: "Offer kept in the evaluation" },
      ],
      titleKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.hianypotlas.title",
      titleDefault: "Answer the hianypotlas inside its deadline",
      whatKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.hianypotlas.what",
      whatDefault:
        "When the authority asks for the file to be completed, put the request on the correspondence thread with the deadline attached, answer exactly what was asked and nothing else, and record what went back and when.",
      whyKey: "cases.bid_for_a_public_works_contract_under_the_kbt.step.hianypotlas.why",
      whyDefault:
        "Kbt. 71. is the second chance the procedure gives you, and it is the only one. The deadlines are short, they run in working days, and they are usually set while the person who assembled the bid is on another job. An answer that arrives a day late is treated the same as no answer, and an answer that changes something nobody asked about invites a different problem.",
      moduleLabel: "Correspondence",
      moduleLabelKey: "nav.correspondence",
      to: "/projects/:projectId/correspondence",
    },
  ],
};

export default playbook;
