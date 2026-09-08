// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Compare the tender bill against the settlement" (CN).
//
// The completion settlement is audited line against line, and the mechanical
// half of that audit is finding every line that moved between the bill that was
// awarded and the bill that was submitted for settlement. That half is what the
// line-by-line comparison does, and it does it well: added, removed, quantity
// changed, rate changed, unchanged, with old and new figures side by side and a
// difference rebased into one currency.
//
// The half a machine cannot do is say WHY a line moved. Nothing in the product
// joins a change order to the bill line it moved, so the case walks the
// reviewer through pairing the movements against the change order register
// themselves, and ends by agreeing the list in writing rather than by exporting
// it. Content strings are key plus inline English default and live only here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "compare-the-tender-bill-against-the-settlement",
  order: 1121,
  region: "CN",
  category: "commercial",
  stage: "handover",
  companyTypes: ["cost-consultant", "developer-client", "project-manager", "general-contractor"],
  roles: ["quantity-surveyor", "commercial-manager", "contract-administrator"],
  icon: "GitCompare",
  titleKey: "cases.compare_the_tender_bill_against_the_settlement.title",
  titleDefault: "Compare the tender bill against the settlement",
  descKey: "cases.compare_the_tender_bill_against_the_settlement.desc",
  descDefault:
    "Set the awarded bill beside the settlement bill, get every line that moved classified as added, removed, quantity changed or rate changed, pair each movement against the instruction that caused it, and agree the list in writing.",
  longDescKey: "cases.compare_the_tender_bill_against_the_settlement.longdesc",
  longDescDefault:
    "A settlement review is two jobs wearing one name. The first is finding the movements, which is mechanical, enormous on a bill of several hundred items, and the thing a reviewer usually does by eye over two evenings with a ruler. The second is deciding whether each movement was authorised, which is judgement and cannot be automated. This case does the first job in one pass and then hands you the second with the evidence in front of you. It matters that the comparison matches on the item code where a line carries one: a coded bill survives insertion and renumbering between award and settlement, while an uncoded bill matches on position number alone and a renumbered settlement reads as a wall of removals and additions instead of as a comparison.",
  estMinutes: 16,
  steps: [
    {
      id: "file",
      icon: "FolderInput",
      inputs: [
        { labelKey: "cases.compare_the_tender_bill_against_the_settlement.step.file.in.awarded", label: "Bill as awarded" },
        { labelKey: "cases.compare_the_tender_bill_against_the_settlement.step.file.in.submitted", label: "Settlement bill as submitted" },
      ],
      outputs: [
        { labelKey: "cases.compare_the_tender_bill_against_the_settlement.step.file.out.filed", label: "Both versions on record" },
      ],
      titleKey: "cases.compare_the_tender_bill_against_the_settlement.step.file.title",
      titleDefault: "File both bills before you touch either",
      whatKey: "cases.compare_the_tender_bill_against_the_settlement.step.file.what",
      whatDefault:
        "Save the contract bill as awarded and the settlement bill as submitted into the project files, dated, with the covering letter that came with each.",
      whyKey: "cases.compare_the_tender_bill_against_the_settlement.step.file.why",
      whyDefault:
        "A settlement review is read months later by somebody who was not there, and the first question is always which two documents were compared. Filing them takes a minute now and removes an argument that otherwise has no evidence on either side.",
      moduleLabel: "Documents",
      moduleLabelKey: "nav.documents",
      to: "/projects/:projectId/files",
    },
    {
      id: "load",
      icon: "Table2",
      inputs: [
        { labelKey: "cases.compare_the_tender_bill_against_the_settlement.step.load.in.files", label: "The two filed bills" },
      ],
      outputs: [
        { labelKey: "cases.compare_the_tender_bill_against_the_settlement.step.load.out.bills", label: "Two bills in the project" },
        { labelKey: "cases.compare_the_tender_bill_against_the_settlement.step.load.out.codes", label: "Item codes preserved" },
      ],
      titleKey: "cases.compare_the_tender_bill_against_the_settlement.step.load.title",
      titleDefault: "Bring both bills in with their codes intact",
      whatKey: "cases.compare_the_tender_bill_against_the_settlement.step.load.what",
      whatDefault:
        "Load each bill so both live in the project side by side, and check that the item codes came across on both. If one side lost its codes in transit, fix that before comparing rather than after.",
      whyKey: "cases.compare_the_tender_bill_against_the_settlement.step.load.why",
      whyDefault:
        "The item code is what makes a line the same line on both sides. With codes, a contractor who inserted twelve items and renumbered everything below them still produces a readable comparison. Without them, the match falls back to position number and the report tells you almost nothing.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "compare",
      icon: "GitCompareArrows",
      inputs: [
        { labelKey: "cases.compare_the_tender_bill_against_the_settlement.step.compare.in.two", label: "Awarded bill and settlement bill" },
      ],
      outputs: [
        { labelKey: "cases.compare_the_tender_bill_against_the_settlement.step.compare.out.diff", label: "Every line classified" },
        { labelKey: "cases.compare_the_tender_bill_against_the_settlement.step.compare.out.delta", label: "The difference in one currency" },
      ],
      titleKey: "cases.compare_the_tender_bill_against_the_settlement.step.compare.title",
      titleDefault: "Run the line-by-line comparison",
      whatKey: "cases.compare_the_tender_bill_against_the_settlement.step.compare.what",
      whatDefault:
        "Open the comparison on the awarded bill and pick the settlement bill as the other side. Every line comes back classified as added, removed, quantity changed, rate changed or unchanged, with the old and new quantity, rate and total, and the difference rebased into the project's currency. Lines settled in process and confirmed by both parties are not measured or priced again under the 2024 standard, so mark them and keep them out of the query list.",
      whyKey: "cases.compare_the_tender_bill_against_the_settlement.step.compare.why",
      whyDefault:
        "This is the part of a settlement review that consumes the days and produces none of the judgement. Getting it in one pass leaves your attention for the lines that are actually contentious, and it catches the quiet ones - a rate that moved by a few percent on a very large quantity - that eyes reading a printout do not.",
      moduleLabel: "BOQ",
      moduleLabelKey: "boq.title",
      to: "/projects/:projectId/boq",
    },
    {
      id: "authorise",
      icon: "SearchCheck",
      inputs: [
        { labelKey: "cases.compare_the_tender_bill_against_the_settlement.step.authorise.in.moved", label: "The lines that moved" },
        { labelKey: "cases.compare_the_tender_bill_against_the_settlement.step.authorise.in.register", label: "Change order register" },
      ],
      outputs: [
        { labelKey: "cases.compare_the_tender_bill_against_the_settlement.step.authorise.out.matched", label: "Movements matched to instructions" },
        { labelKey: "cases.compare_the_tender_bill_against_the_settlement.step.authorise.out.unmatched", label: "Movements with nothing behind them" },
      ],
      titleKey: "cases.compare_the_tender_bill_against_the_settlement.step.authorise.title",
      titleDefault: "Pair every movement with the instruction that caused it",
      whatKey: "cases.compare_the_tender_bill_against_the_settlement.step.authorise.what",
      whatDefault:
        "Work down the moved lines with the change order register open beside them, and mark which instruction each movement answers to. The list that is left over - movements with no instruction behind them - is your query list.",
      whyKey: "cases.compare_the_tender_bill_against_the_settlement.step.authorise.why",
      whyDefault:
        "The comparison tells you what moved and the register tells you what was instructed; pairing them is judgement and stays yours. Doing it while the classified list is in front of you is what turns a settlement review into a short, specific set of questions instead of a general objection nobody can answer.",
      moduleLabel: "Change Orders",
      moduleLabelKey: "nav.change_orders",
      to: "/changeorders",
    },
    {
      id: "agree",
      icon: "MessageSquare",
      inputs: [
        { labelKey: "cases.compare_the_tender_bill_against_the_settlement.step.agree.in.queries", label: "Query list with amounts" },
      ],
      outputs: [
        { labelKey: "cases.compare_the_tender_bill_against_the_settlement.step.agree.out.letter", label: "Queries issued and tracked" },
        { labelKey: "cases.compare_the_tender_bill_against_the_settlement.step.agree.out.agreed", label: "Agreed position on each line" },
      ],
      titleKey: "cases.compare_the_tender_bill_against_the_settlement.step.agree.title",
      titleDefault: "Put the queries in writing and track the answers",
      whatKey: "cases.compare_the_tender_bill_against_the_settlement.step.agree.what",
      whatDefault:
        "Issue the query list as correspondence, item by item with the amount at stake on each, and record the answer against the query rather than in somebody's inbox.",
      whyKey: "cases.compare_the_tender_bill_against_the_settlement.step.agree.why",
      whyDefault:
        "An owner who neither checks the settlement nor objects within the review period the contract sets is taken, under the 2024 standard, to have accepted it as submitted, so the queries have to leave inside that window. A settlement is agreed line by line or it is not agreed at all. Queries raised in writing get answered; queries raised in a meeting get remembered differently by each side, and the difference surfaces at the worst possible moment, when the final figure is being signed.",
      moduleLabel: "Correspondence",
      moduleLabelKey: "nav.correspondence",
      to: "/projects/:projectId/correspondence",
    },
  ],
};

export default playbook;
