// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Run a tender under the AS 4120 code of tendering" (AU).
//
// AS 4120-1994 is the Australian Standard that states the ethics and the
// obligations of the principal and of the tenderers. It is short, it is rarely
// read after the first year of practice, and almost every complaint about a
// tender process in Australia is a breach of one of its plain rules: a
// shortlist the principal never intended to award to, information given to one
// tenderer and not the rest, a late tender accepted, a price shopped after the
// close. Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "run-a-tender-under-the-as-4120-code-of-tendering",
  order: 1616,
  region: "AU",
  category: "tendering",
  companyTypes: ["general-contractor", "cost-consultant", "project-manager", "developer-client"],
  roles: ["procurement-buyer", "quantity-surveyor", "commercial-manager", "estimator"],
  stage: "procure",
  icon: "Scale",
  titleKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.title",
  titleDefault: "Run a tender under the AS 4120 code of tendering",
  descKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.desc",
  descDefault:
    "Invite only the tenderers you would award to, issue one identical document set with a closing time, answer every question by addendum to everyone, open after the close, level conforming and alternative offers separately and award through a recorded approval rather than a second round of prices.",
  longDescKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.longdesc",
  longDescDefault:
    "AS 4120 is a code of ethics with the force of whatever the tender documents give it, and Australian principals routinely call it up by name. What it asks of the principal is simple and inconvenient: invite a genuine shortlist, give every tenderer the same information at the same time, keep what they submit confidential, and do not use one tenderer's price to move another's. What it asks of tenderers is the mirror of that. Running a tender to the code costs a little discipline at the start and removes the two outcomes that actually hurt, a tender period reopened because the information was unequal, and an award that a losing tenderer can describe as a shop.",
  estMinutes: 15,
  steps: [
    {
      id: "list",
      icon: "Users",
      inputs: [
        { labelKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.list.in.market", label: "Market of available builders" },
        { labelKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.list.in.capability", label: "Capability and capacity" },
      ],
      outputs: [
        { labelKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.list.out.shortlist", label: "Shortlist you would award to" },
        { labelKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.list.out.declined", label: "Reasons the rest are out" },
      ],
      titleKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.list.title",
      titleDefault: "Invite only the tenderers you would actually award to",
      whatKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.list.what",
      whatDefault:
        "Build the invitation list from capability, current capacity, licence and insurance rather than from the last job's list, and keep it short enough that every name on it has a real chance. Record why each candidate is in or out.",
      whyKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.list.why",
      whyDefault:
        "The code asks a principal to invite only tenderers it is prepared to accept, and the reason is economic rather than moral. A tender costs a builder real money to price, so a list of eight where two were ever in contention teaches the market to load the price or to decline the next invitation, and the principal pays for it either way.",
      moduleLabel: "Subcontractor Directory",
      moduleLabelKey: "nav.subcontractors",
      to: "/subcontractors",
    },
    {
      id: "documents",
      icon: "FileStack",
      inputs: [
        { labelKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.documents.in.shortlist", label: "Shortlist you would award to" },
        { labelKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.documents.in.docs", label: "Drawings, bill and conditions" },
      ],
      outputs: [
        { labelKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.documents.out.issued", label: "One identical document set issued" },
        { labelKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.documents.out.close", label: "Closing time and place stated" },
      ],
      titleKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.documents.title",
      titleDefault: "Issue one identical set with a stated closing time",
      whatKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.documents.what",
      whatDefault:
        "Issue the same documents to every tenderer at the same time: the drawings and their revisions, the bill, the conditions of contract with the Annexure filled in, and the conditions of tendering, including the closing time and place, whether alternative tenders are accepted and on what terms, and how long the offer must stand open.",
      whyKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.documents.why",
      whyDefault:
        "Everything the code protects flows from every tenderer pricing the same document. A revision that reached three of five is not a documentation slip, it is an unequal tender, and the only honest remedy once it is discovered is to extend the period for everyone and pay for the time.",
      moduleLabel: "Tendering",
      moduleLabelKey: "tendering.title",
      to: "/tendering",
    },
    {
      id: "addenda",
      icon: "Send",
      inputs: [
        { labelKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.addenda.in.questions", label: "Tenderer questions" },
        { labelKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.addenda.in.answers", label: "Answers from the design team" },
      ],
      outputs: [
        { labelKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.addenda.out.addendum", label: "Addendum issued to everyone" },
        { labelKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.addenda.out.trail", label: "Question and answer trail" },
      ],
      titleKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.addenda.title",
      titleDefault: "Answer a question once and send it to everybody",
      whatKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.addenda.what",
      whatDefault:
        "Log every question in the correspondence register as it arrives, answer it as a numbered addendum issued to all tenderers, and never answer a substantive question by telephone. Where an answer changes the scope late in the period, extend the closing time rather than assume the tenderers can absorb it.",
      whyKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.addenda.why",
      whyDefault:
        "The tenderer who asks the good question is the one who read the documents properly, and answering only them rewards the reading by handing the answer to nobody else. The code calls that unequal information, and a losing tenderer who finds out about it has a complaint that survives the award.",
      moduleLabel: "Correspondence",
      moduleLabelKey: "nav.correspondence",
      to: "/projects/:projectId/correspondence",
    },
    {
      id: "receive",
      icon: "FolderInput",
      inputs: [
        { labelKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.receive.in.offers", label: "Submitted tenders" },
        { labelKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.receive.in.close", label: "Closing time" },
      ],
      outputs: [
        { labelKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.receive.out.opened", label: "Tenders opened after the close" },
        { labelKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.receive.out.register", label: "Register of what arrived when" },
      ],
      titleKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.receive.title",
      titleDefault: "Hold them closed until the closing time",
      whatKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.receive.what",
      whatDefault:
        "Take the tenders in without opening them, record the time each one arrived, and open them together after the close. Deal with a late tender under the rule the conditions of tendering stated, before you know what it says.",
      whyKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.receive.why",
      whyDefault:
        "A tender opened early is a price that can be repeated to somebody else, and the code treats the confidentiality of a submitted offer as absolute. The rule about late tenders has to be applied blind for the same reason: a decision made after reading the number is a decision about the number.",
      moduleLabel: "Bid Management",
      moduleLabelKey: "nav.bid_management",
      to: "/bid-management",
    },
    {
      id: "compare",
      icon: "GitCompare",
      inputs: [
        { labelKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.compare.in.opened", label: "Tenders opened after the close" },
        { labelKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.compare.in.bill", label: "The bill they all priced" },
      ],
      outputs: [
        { labelKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.compare.out.levelled", label: "Conforming offers levelled" },
        { labelKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.compare.out.alternatives", label: "Alternatives assessed on their own" },
      ],
      titleKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.compare.title",
      titleDefault: "Level the conforming offers before you look at the alternatives",
      whatKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.compare.what",
      whatDefault:
        "Compare the conforming tenders against each other first, item by item, and clear up an ambiguity by asking that tenderer what it means rather than by adjusting their price yourself. Assess an alternative tender separately, on what it changes and what it is worth, and only where the conditions of tendering allowed one.",
      whyKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.compare.why",
      whyDefault:
        "Mixing an alternative into the conforming comparison compares two different buildings on price, which is how a cheaper offer wins by leaving something out. Clarification is allowed and correction is not, and the line between them is whether the tenderer or the assessor decided what the price now means.",
      moduleLabel: "Bid Management",
      moduleLabelKey: "nav.bid_management",
      to: "/bid-management",
    },
    {
      id: "award",
      icon: "Stamp",
      inputs: [
        { labelKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.award.in.levelled", label: "Conforming offers levelled" },
        { labelKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.award.in.recommendation", label: "Recommendation to award" },
      ],
      outputs: [
        { labelKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.award.out.approved", label: "Award approved and dated" },
        { labelKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.award.out.advised", label: "Unsuccessful tenderers advised" },
      ],
      titleKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.award.title",
      titleDefault: "Award through a recorded approval, not a second round of prices",
      whatKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.award.what",
      whatDefault:
        "Put the recommendation through the approval route that has the authority to commit the money, with the levelled comparison attached, and advise the unsuccessful tenderers once it is decided. Do not take the lowest price back to the others to be beaten.",
      whyKey: "cases.run_a_tender_under_the_as_4120_code_of_tendering.step.award.why",
      whyDefault:
        "Using one tender to move another is the practice the code exists to stop, and it is self defeating over a market as small as Australian construction: the builders find out, and the discount is recovered on the first variation of the job you just shopped. An approval with the comparison attached is also the only durable answer to the question of why this builder was chosen.",
      moduleLabel: "Approval routes",
      moduleLabelKey: "approvalRoutes.title",
      to: "/governance?tab=approvals",
    },
  ],
};

export default playbook;
