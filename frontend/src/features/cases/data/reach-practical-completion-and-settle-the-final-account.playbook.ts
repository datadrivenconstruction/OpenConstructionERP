// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Reach practical completion and settle the final account" (GB).
//
// Practical completion is the hinge of a British building contract: it starts
// the rectification period, releases retention and stops damages running.
// The case keeps the defects and the money on the same set of dates, so the
// final account is arithmetic rather than archaeology. Content strings are
// key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "reach-practical-completion-and-settle-the-final-account",
  order: 1167,
  region: "GB",
  category: "handover",
  companyTypes: ["general-contractor", "cost-consultant", "developer-client", "project-manager"],
  roles: ["contract-administrator", "quantity-surveyor", "site-manager", "commercial-manager"],
  stage: "handover",
  icon: "Stamp",
  titleKey: "cases.reach_practical_completion_and_settle_the_final_account.title",
  titleDefault: "Reach practical completion and settle the final account",
  descKey: "cases.reach_practical_completion_and_settle_the_final_account.desc",
  descDefault:
    "Clear the snagging list, issue the certificate against a package that exists, run the rectification period as a register rather than as a memory, release the retention when it falls due and agree the final account from what was recorded all along.",
  longDescKey: "cases.reach_practical_completion_and_settle_the_final_account.longdesc",
  longDescDefault:
    "Practical completion is the hinge of a British building contract. It starts the rectification period, it usually releases the first half of the retention, it stops liquidated damages running and it moves the risk of the building to the employer. Everything after it is easier or harder depending on how tidily that one moment was recorded. This case runs the sequence from the snagging list to the agreed final account, keeping the defects and the money on the same dates, because the second half of the retention and the last defect notice are the same event seen from two desks.",
  estMinutes: 18,
  steps: [
    {
      id: "snag",
      icon: "ClipboardList",
      inputs: [
        { labelKey: "cases.reach_practical_completion_and_settle_the_final_account.step.snag.in.walk", label: "Site walk findings" },
        { labelKey: "cases.reach_practical_completion_and_settle_the_final_account.step.snag.in.spec", label: "Specification and drawings" },
      ],
      outputs: [
        { labelKey: "cases.reach_practical_completion_and_settle_the_final_account.step.snag.out.list", label: "Snagging list with photos" },
        { labelKey: "cases.reach_practical_completion_and_settle_the_final_account.step.snag.out.blockers", label: "Items that block completion" },
      ],
      titleKey: "cases.reach_practical_completion_and_settle_the_final_account.step.snag.title",
      titleDefault: "Clear the snagging list before you ask for the certificate",
      whatKey: "cases.reach_practical_completion_and_settle_the_final_account.step.snag.what",
      whatDefault:
        "Walk the building and record the outstanding items room by room with a photograph, an owner and a date. Sort them into what genuinely prevents practical completion and what can be finished during the rectification period, and close them off as they are done.",
      whyKey: "cases.reach_practical_completion_and_settle_the_final_account.step.snag.why",
      whyDefault:
        "Practical completion is not perfection and it is not a wish list, but the argument about which items are which gets a great deal shorter when the items exist as a photographed list with owners. A certificate issued over an undocumented set of snags is the one the employer challenges.",
      moduleLabel: "Punch List",
      moduleLabelKey: "nav.punchlist",
      to: "/punchlist",
    },
    {
      id: "certify",
      icon: "BadgeCheck",
      inputs: [
        { labelKey: "cases.reach_practical_completion_and_settle_the_final_account.step.certify.in.blockers", label: "Items that block completion" },
        { labelKey: "cases.reach_practical_completion_and_settle_the_final_account.step.certify.in.docs", label: "Handover documents" },
      ],
      outputs: [
        { labelKey: "cases.reach_practical_completion_and_settle_the_final_account.step.certify.out.certified", label: "Practical completion certified" },
        { labelKey: "cases.reach_practical_completion_and_settle_the_final_account.step.certify.out.package", label: "Close-out package issued" },
      ],
      titleKey: "cases.reach_practical_completion_and_settle_the_final_account.step.certify.title",
      titleDefault: "Issue the certificate with the package behind it",
      whatKey: "cases.reach_practical_completion_and_settle_the_final_account.step.certify.what",
      whatDefault:
        "Assemble the close-out package first, the as-built drawings, the operation and maintenance manuals, the warranties, the test and commissioning certificates and the asset information, and issue practical completion against a package that exists rather than against a promise to send one.",
      whyKey: "cases.reach_practical_completion_and_settle_the_final_account.step.certify.why",
      whyDefault:
        "The certificate changes several things at once: the rectification period starts, the first half of the retention usually falls due and damages stop running. Issuing it before the package is real means chasing manuals out of subcontractors who have been paid and have moved on, which is a job with no leverage left in it.",
      moduleLabel: "Close-out",
      moduleLabelKey: "nav.closeout",
      to: "/closeout",
    },
    {
      id: "defects",
      icon: "Wrench",
      inputs: [
        { labelKey: "cases.reach_practical_completion_and_settle_the_final_account.step.defects.in.certified", label: "Practical completion certified" },
        { labelKey: "cases.reach_practical_completion_and_settle_the_final_account.step.defects.in.warranties", label: "Warranties and product data" },
      ],
      outputs: [
        { labelKey: "cases.reach_practical_completion_and_settle_the_final_account.step.defects.out.register", label: "Defects register" },
        { labelKey: "cases.reach_practical_completion_and_settle_the_final_account.step.defects.out.periods", label: "Periods with an end date" },
      ],
      titleKey: "cases.reach_practical_completion_and_settle_the_final_account.step.defects.title",
      titleDefault: "Run the rectification period as a register",
      whatKey: "cases.reach_practical_completion_and_settle_the_final_account.step.defects.what",
      whatDefault:
        "Open the register: every warranty and defects liability entry with its start date, its length and what it covers, and every defect notice raised against it with a severity and a status. The register shows what is still inside its period, what is expiring and what has run clean.",
      whyKey: "cases.reach_practical_completion_and_settle_the_final_account.step.defects.why",
      whyDefault:
        "The rectification period is six months by JCT default and twelve where the contract particulars say so, as they usually do, and nobody is thinking about it in month four. A register that knows which entries are expiring is what turns the final inspection into something you schedule rather than something you miss, and it is also the evidence that an entry finished clean and its retention is due.",
      moduleLabel: "Warranties & Defects Liability",
      moduleLabelKey: "defects_liability.title",
      to: "/projects/:projectId/defects-liability",
    },
    {
      id: "retention",
      icon: "Banknote",
      inputs: [
        { labelKey: "cases.reach_practical_completion_and_settle_the_final_account.step.retention.in.held", label: "Retention held" },
        { labelKey: "cases.reach_practical_completion_and_settle_the_final_account.step.retention.in.events", label: "Release events on the contract" },
      ],
      outputs: [
        { labelKey: "cases.reach_practical_completion_and_settle_the_final_account.step.retention.out.released", label: "Retention released at completion" },
        { labelKey: "cases.reach_practical_completion_and_settle_the_final_account.step.retention.out.balance", label: "Balance due at the end of the period" },
      ],
      titleKey: "cases.reach_practical_completion_and_settle_the_final_account.step.retention.title",
      titleDefault: "Release the retention when it actually falls due",
      whatKey: "cases.reach_practical_completion_and_settle_the_final_account.step.retention.what",
      whatDefault:
        "Read the retention ledger against the release events recorded on the contract. The first release normally follows practical completion and the second follows the end of the rectification period with the defects made good, so what the ledger shows is money that is due rather than money that is held indefinitely.",
      whyKey: "cases.reach_practical_completion_and_settle_the_final_account.step.retention.why",
      whyDefault:
        "Retention released late is a real cost to a subcontractor and a real reputational cost to the payer, and it is almost always late because nobody was watching rather than because anybody decided. Tying the release to the event on the contract makes it a date instead of a favour.",
      moduleLabel: "Finance",
      moduleLabelKey: "nav.finance",
      to: "/projects/:projectId/finance",
    },
    {
      id: "account",
      icon: "Handshake",
      inputs: [
        { labelKey: "cases.reach_practical_completion_and_settle_the_final_account.step.account.in.sum", label: "Contract sum and variations" },
        { labelKey: "cases.reach_practical_completion_and_settle_the_final_account.step.account.in.instructions", label: "Instructions issued on the job" },
      ],
      outputs: [
        { labelKey: "cases.reach_practical_completion_and_settle_the_final_account.step.account.out.agreed", label: "Agreed final account" },
        { labelKey: "cases.reach_practical_completion_and_settle_the_final_account.step.account.out.closed", label: "Contract closed" },
      ],
      titleKey: "cases.reach_practical_completion_and_settle_the_final_account.step.account.title",
      titleDefault: "Agree the final account as arithmetic, not archaeology",
      whatKey: "cases.reach_practical_completion_and_settle_the_final_account.step.account.what",
      whatDefault:
        "Build the final account from what has already been recorded: the contract sum, the variation orders posted as they were agreed, the provisional sums adjusted to what was actually instructed, the prime cost sums, any fluctuations the contract carries, and the retention released. Agree it, sign it and close the contract. Under JCT the contractor has six months from practical completion to send in the documents the final account is built from, and the final certificate follows; under NEC4 the project manager makes the final assessment within four weeks of the defects certificate.",
      whyKey: "cases.reach_practical_completion_and_settle_the_final_account.step.account.why",
      whyDefault:
        "A final account reconstructed at the end takes months and settles in favour of whichever party kept better records. One that has been current all along is a statement both sides have already seen every month, and agreeing it becomes a signature rather than a negotiation nobody budgeted for.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
  ],
};

export default playbook;
