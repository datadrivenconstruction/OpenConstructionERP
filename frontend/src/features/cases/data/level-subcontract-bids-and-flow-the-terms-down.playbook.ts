// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Level subcontract bids and flow the terms down" (CA).
//
// An award is a gate, not a button. The distinctive step is the one where the
// product declines to proceed because a required document is not valid on the
// award date, and the wording of that step matters more than anywhere else in
// the Canadian set: the check is a check AT AN INSTANT. "Valid on the award
// date" is true; "compliance verified" or anything implying cover for the whole
// contract period is not, and the difference is the one a caption would quietly
// erase. Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "level-subcontract-bids-and-flow-the-terms-down",
  order: 1109,
  region: "CA",
  category: "tendering",
  companyTypes: ["general-contractor", "project-manager", "cost-consultant"],
  roles: ["estimator", "procurement-buyer", "commercial-manager", "contract-administrator"],
  icon: "Gavel",
  titleKey: "cases.level_subcontract_bids_and_flow_the_terms_down.title",
  titleDefault: "Level subcontract bids and flow the terms down",
  descKey: "cases.level_subcontract_bids_and_flow_the_terms_down.desc",
  descDefault:
    "Level the bids for a package onto one scope, check the intended winner's documents as at the day you mean to award, let the award wait rather than be waved through when one has lapsed, and write the subcontract with the holdback and payment terms taken from the contract above.",
  longDescKey: "cases.level_subcontract_bids_and_flow_the_terms_down.longdesc",
  longDescDefault:
    "An award is a gate rather than a button, and it is guarding two things at once. The low bid is regularly the one that left the most out, which is not dishonesty but two readings of the same drawings, and the difference only becomes visible when the scopes are set side by side and the gaps are priced. The second thing is quieter: a certificate that lapsed last month is still in the folder looking current, and the moment to catch it is before the subcontract exists, because afterwards the leverage is gone and the exposure is yours. Worth stating accurately rather than dramatically, since the dramatic version circulates widely and is not true anywhere in the country: what a missing workers compensation clearance exposes a contractor to is the subcontractor's unpaid premiums, not the cost of an injury. That is real money and it is enough of a reason on its own.",
  estMinutes: 20,
  steps: [
    {
      id: "level",
      icon: "Scale",
      inputs: [
        { labelKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.level.in.bids", label: "Bids as they arrived" },
        { labelKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.level.in.scope", label: "The scope they were invited on" },
      ],
      outputs: [
        { labelKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.level.out.matrix", label: "Bids compared on one scope" },
        { labelKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.level.out.gaps", label: "Gaps priced rather than argued" },
      ],
      titleKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.level.title",
      titleDefault: "Level the bids onto one scope",
      whatKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.level.what",
      whatDefault:
        "Set the bids for the package side by side against the scope they were invited on, bring every exclusion and alternate onto the face of the comparison, and carry a price for each gap so the totals compare complete scopes.",
      whyKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.level.why",
      whyDefault:
        "Five bids that are each a single number look comparable and are not. The one that excluded the hoisting and the one that carried the permit have answered different questions, and the difference does not surface until it arrives as a change order in the autumn with no competitive tension left in it.",
      moduleLabel: "Tenders",
      moduleLabelKey: "tenders.title",
      to: "/tenders",
    },
    {
      id: "register",
      icon: "FileCheck",
      inputs: [
        { labelKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.register.in.certs", label: "Certificates from the bidders" },
        { labelKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.register.in.required", label: "Documents the package requires" },
      ],
      outputs: [
        { labelKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.register.out.filed", label: "Documents on file with expiry dates" },
        { labelKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.register.out.queryable", label: "A register that can answer a date" },
      ],
      titleKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.register.title",
      titleDefault: "Hold the documents with the date each one expires",
      whatKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.register.what",
      whatDefault:
        "Keep the insurance certificate and the other documents the package requires on each subcontractor's record with the date it expires, and file the document itself rather than a note saying it was seen.",
      whyKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.register.why",
      whyDefault:
        "A register of documents without their expiry dates cannot answer the only question anybody ever asks it, which is whether the cover was in place on a particular day. Recording the expiry is the whole difference between a filing cabinet and a check.",
      moduleLabel: "Subcontractor Directory",
      moduleLabelKey: "nav.subcontractors",
      to: "/subcontractors",
    },
    {
      id: "gate",
      icon: "ShieldAlert",
      inputs: [
        { labelKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.gate.in.winner", label: "The intended winner" },
        { labelKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.gate.in.date", label: "The date you mean to award" },
      ],
      outputs: [
        { labelKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.gate.out.result", label: "A pass, or a named lapse with its date" },
        { labelKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.gate.out.wait", label: "An award that waits" },
      ],
      titleKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.gate.title",
      titleDefault: "Check the winner as at the award date",
      whatKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.gate.what",
      whatDefault:
        "Before writing the award, check the intended winner's required documents as at the date you intend to award. Where one has lapsed the award waits, and what goes back to the subcontractor names the document and the day it lapsed rather than saying they are blocked.",
      whyKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.gate.why",
      whyDefault:
        "The honest statement is that a document was valid on the award date, and not that compliance is established for the contract or for the duration of the work, which is a different claim nobody has checked. A gate that can be waved through is worse than no gate at all, because everybody downstream believes it.",
      moduleLabel: "Tenders",
      moduleLabelKey: "tenders.title",
      to: "/tenders",
    },
    {
      id: "renew",
      icon: "BadgeCheck",
      inputs: [
        { labelKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.renew.in.renewed", label: "The renewed certificate" },
      ],
      outputs: [
        { labelKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.renew.out.updated", label: "Register updated, history kept" },
        { labelKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.renew.out.passing", label: "The same check, now passing" },
      ],
      titleKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.renew.title",
      titleDefault: "Take the current document and run the same check",
      whatKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.renew.what",
      whatDefault:
        "Load the renewed certificate against the same document type on the record, keeping the lapsed one in the history rather than replacing it, and run the same check on the same award date.",
      whyKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.renew.why",
      whyDefault:
        "Nothing should be overridden here; the underlying fact should change. Keeping the lapsed certificate beside the renewed one is also what lets you answer, a year later, what cover was actually in place during the week the work started.",
      moduleLabel: "Subcontractor Directory",
      moduleLabelKey: "nav.subcontractors",
      to: "/subcontractors",
    },
    {
      id: "flowdown",
      icon: "Workflow",
      inputs: [
        { labelKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.flowdown.in.award", label: "The levelled scope and the award" },
        { labelKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.flowdown.in.terms", label: "Holdback and payment terms above" },
      ],
      outputs: [
        { labelKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.flowdown.out.subcontract", label: "Subcontract issued with terms flowed down" },
        { labelKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.flowdown.out.matching", label: "Held money matching the contract above" },
      ],
      titleKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.flowdown.title",
      titleDefault: "Write the subcontract with the terms flowed down",
      whatKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.flowdown.what",
      whatDefault:
        "Turn the levelled scope into the subcontract, taking the holdback percentage and the payment terms from the contract above rather than typing them again, so the 10 percent held below matches the 10 percent held above and the dates line up.",
      whyKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.flowdown.why",
      whyDefault:
        "The scope that was levelled is the scope that has to be bought, and a subcontract retyped from a bid letter quietly drops the exclusions levelling had just made visible. Terms that do not match the contract above are also how a general contractor ends up owing money on a date it has not itself been paid on.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "record",
      icon: "FileBarChart",
      inputs: [
        { labelKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.record.in.levelled", label: "The levelled comparison" },
        { labelKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.record.in.committed", label: "Committed value and its estimate line" },
      ],
      outputs: [
        { labelKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.record.out.recommendation", label: "Award recommendation on record" },
        { labelKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.record.out.buyout", label: "Buyout gain or loss per package" },
      ],
      titleKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.record.title",
      titleDefault: "Record the award and the buyout result",
      whatKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.record.what",
      whatDefault:
        "Issue the recommendation with the adjusted total for each bidder, the reason the winner was chosen, the check that was run and the date it was run as at, and compare the committed value against the estimate line it came from.",
      whyKey: "cases.level_subcontract_bids_and_flow_the_terms_down.step.record.why",
      whyDefault:
        "On public and institutional work the reasoning gets read by somebody who was not in the room, sometimes after a protest. Writing it while the comparison is still in front of you takes minutes, and the buyout comparison tells you the result package by package while there is still a job left to act on it.",
      moduleLabel: "Reports",
      moduleLabelKey: "nav.reports",
      to: "/reports",
    },
  ],
};

export default playbook;
