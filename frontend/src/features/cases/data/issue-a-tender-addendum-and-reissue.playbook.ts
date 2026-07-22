// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Issue a tender addendum and reissue".
//
// A query or a design change lands mid-tender: capture it, draft the addendum,
// reissue to every bidder on the same terms and confirm receipt. Content strings
// are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "issue-a-tender-addendum-and-reissue",
  order: 1008,
  category: "tendering",
  companyTypes: ["general-contractor", "cost-consultant", "project-manager"],
  icon: "Send",
  titleKey: "cases.issue_a_tender_addendum_and_reissue.title",
  titleDefault: "Issue a tender addendum and reissue",
  descKey: "cases.issue_a_tender_addendum_and_reissue.desc",
  descDefault:
    "A bidder query or a design change lands mid-tender. Capture it, draft the addendum, reissue it to every bidder on the same terms and confirm they all have it before the clock runs out.",
  longDescKey: "cases.issue_a_tender_addendum_and_reissue.longdesc",
  longDescDefault:
    "Tenders move while they are live. The danger is that one bidder gets a clarification the others do not, and the whole process is compromised. A controlled addendum keeps every firm on exactly the same information, which is what keeps the award defensible.",
  estMinutes: 9,
  steps: [
    {
      id: "trigger",
      icon: "MessageSquare",
      inputs: [
        { labelKey: "cases.issue_a_tender_addendum_and_reissue.step.trigger.in.query", label: "Bidder query" },
        { labelKey: "cases.issue_a_tender_addendum_and_reissue.step.trigger.in.change", label: "Design change" },
      ],
      outputs: [
        { labelKey: "cases.issue_a_tender_addendum_and_reissue.step.trigger.out.logged", label: "Logged trigger" },
      ],
      titleKey: "cases.issue_a_tender_addendum_and_reissue.step.trigger.title",
      titleDefault: "Capture what forces it",
      whatKey: "cases.issue_a_tender_addendum_and_reissue.step.trigger.what",
      whatDefault:
        "Log the bidder question or the design change that makes the issued information wrong or incomplete, and decide whether it needs a formal addendum to all or a private answer to one.",
      whyKey: "cases.issue_a_tender_addendum_and_reissue.step.trigger.why",
      whyDefault:
        "The moment a query changes the scope, everyone needs to know. Capturing the trigger cleanly is what stops a helpful side conversation turning into an unfair advantage.",
      moduleLabel: "Correspondence",
      moduleLabelKey: "nav.correspondence",
      to: "/projects/:projectId/correspondence",
    },
    {
      id: "draft",
      icon: "FileSignature",
      inputs: [
        { labelKey: "cases.issue_a_tender_addendum_and_reissue.step.draft.in.logged", label: "Logged trigger" },
        { labelKey: "cases.issue_a_tender_addendum_and_reissue.step.draft.in.revised", label: "Revised documents" },
      ],
      outputs: [
        { labelKey: "cases.issue_a_tender_addendum_and_reissue.step.draft.out.addendum", label: "Numbered addendum" },
      ],
      titleKey: "cases.issue_a_tender_addendum_and_reissue.step.draft.title",
      titleDefault: "Draft the addendum",
      whatKey: "cases.issue_a_tender_addendum_and_reissue.step.draft.what",
      whatDefault:
        "Write the addendum with a clear number, the change it makes, the documents it supersedes and the revised files attached, so a bidder can act on it without guessing.",
      whyKey: "cases.issue_a_tender_addendum_and_reissue.step.draft.why",
      whyDefault:
        "A numbered addendum with the superseded documents named is what keeps the tender set unambiguous. Loose emails leave firms pricing off different revisions of the same drawing.",
      moduleLabel: "Files",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
    {
      id: "reissue",
      icon: "Send",
      inputs: [
        { labelKey: "cases.issue_a_tender_addendum_and_reissue.step.reissue.in.addendum", label: "Numbered addendum" },
        { labelKey: "cases.issue_a_tender_addendum_and_reissue.step.reissue.in.bidders", label: "Bidder list" },
      ],
      outputs: [
        { labelKey: "cases.issue_a_tender_addendum_and_reissue.step.reissue.out.sent", label: "Reissued to all" },
        { labelKey: "cases.issue_a_tender_addendum_and_reissue.step.reissue.out.deadline", label: "Reset deadline" },
      ],
      titleKey: "cases.issue_a_tender_addendum_and_reissue.step.reissue.title",
      titleDefault: "Reissue to every bidder",
      whatKey: "cases.issue_a_tender_addendum_and_reissue.step.reissue.what",
      whatDefault:
        "Send the addendum to the whole bidder list at once and, if the change is material, extend the submission deadline so nobody is squeezed for the time to reprice.",
      whyKey: "cases.issue_a_tender_addendum_and_reissue.step.reissue.why",
      whyDefault:
        "Issuing to all on the same day and the same terms is the heart of a fair tender. Extending the deadline where it matters keeps the prices sharp instead of rushed.",
      moduleLabel: "Tendering",
      moduleLabelKey: "tendering.title",
      to: "/tendering",
    },
    {
      id: "confirm",
      icon: "ClipboardCheck",
      inputs: [
        { labelKey: "cases.issue_a_tender_addendum_and_reissue.step.confirm.in.sent", label: "Reissued addendum" },
      ],
      outputs: [
        { labelKey: "cases.issue_a_tender_addendum_and_reissue.step.confirm.out.acknowledged", label: "Acknowledged by all" },
      ],
      titleKey: "cases.issue_a_tender_addendum_and_reissue.step.confirm.title",
      titleDefault: "Confirm every bidder has it",
      whatKey: "cases.issue_a_tender_addendum_and_reissue.step.confirm.what",
      whatDefault:
        "Track that each bidder acknowledged the addendum, and chase the ones who have not, so no firm submits against out-of-date information.",
      whyKey: "cases.issue_a_tender_addendum_and_reissue.step.confirm.why",
      whyDefault:
        "A bid priced without the latest addendum is worthless and has to be rejected. Confirming receipt from all is the cheap step that protects the whole exercise.",
      moduleLabel: "Tendering",
      moduleLabelKey: "tendering.title",
      to: "/tendering",
    },
  ],
};

export default playbook;
